"""
Agent 评测脚本 —— 对 eval/agent_tasks.json 逐题跑 run_agent()，统计 Agent 层面的指标。

用法（必须在 agent/ 根目录）：
    python eval/evaluate_agent.py

指标：
    - 工具选择正确率 ：agent 是否调用了预期工具(文档→knowledge_search, 统计→sql_query, 结构→list_tables)
    - 任务完成率     ：未超时、未报错
    - 引用命中率     ：文档类答案引用的来源是否命中金标准文档
    - 拒答正确率     ：库外问题是否老实拒答而非编造
    - 答案质量(LLM裁判)：文档类的正确性(correct) / 忠实性(grounded) 打分
    - 平均延迟/迭代  ：工程指标

前置：已运行 eval/build_index.py 建好索引；MySQL + LLM 可用。
"""
import asyncio
import json
import os
import re
import sys
import time

# 项目根目录：既加入 sys.path，也 chdir 过去，保证 ./milvus.db 等相对路径解析正确（无论从哪里运行）
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

from openai import AsyncOpenAI

from backend.agent.executor import run_agent
from backend.core.config import get_settings
from backend.core.tool_output import render_tool_result
from backend.services import rag

TASKS_FILE = os.path.join(os.path.dirname(__file__), "agent_tasks.json")

# 拒答判定关键词（agent 应明确说"查不到/做不到"而非编造）
# 注意：这是关键词启发式，措辞漏一个就会把「老实拒答」记成失败
# （例如 agent 答"写诗不在我的能力范围内…没法进行文学创作"就漏过「无法」）。
REFUSAL_MARKERS = (
    "未找到", "没有找到", "无法", "没法", "不能提供", "不清楚", "抱歉",
    "没有相关", "无相关", "不在我的能力范围", "超出我的能力范围",
)

JUDGE_PROMPT = """你是严格的评测裁判，判断一个企业知识库 Agent 的回答质量。

【用户问题】
{query}

【Agent 检索到的资料】（Agent 回答时实际拿到的工具返回内容）
{context}

【Agent 回答】
{answer}

请从两个维度判断（只输出 JSON，不要输出其他内容）：
1. correct：回答是否准确回答了问题，且关键结论与给定资料一致（无冲突/无错误）？
2. grounded：回答中的事实是否都能在给定资料中找到——资料里没有的一律算编造（无幻觉）？

输出格式：{{"correct": true或false, "grounded": true或false, "reason": "一句话原因"}}
"""


def _is_timeout_or_error(answer: str) -> bool:
    return "处理超时" in answer or answer.startswith("LLM调用失败") or answer.startswith("请求失败")


def _is_refusal(answer: str) -> bool:
    return any(m in answer for m in REFUSAL_MARKERS)


REFUSAL_JUDGE_PROMPT = """这是一个企业知识库 Agent 面对库外问题的回答。

【用户问题】
{query}

【Agent 回答】
{answer}

这个回答是否属于"拒绝作答"——即明确表示自己查不到/做不到、没有给出针对该问题的实质内容？
（措辞不重要：说"未找到""没这个能力""帮不上忙""不在我的职责范围"都算；只要没有编造或硬答就不算失败）

只输出 JSON：{{"refused": true或false, "reason": "一句话"}}
"""


async def _judge_refusal(client, settings, query: str, answer: str) -> bool:
    """关键词没命中时的兜底判定：拒绝的措辞每轮都不一样，光靠关键词表会漏。"""
    jr = await client.chat.completions.create(
        model=settings.llm_model,
        messages=[{"role": "user", "content": REFUSAL_JUDGE_PROMPT.format(query=query, answer=answer)}],
        temperature=0,
    )
    text = jr.choices[0].message.content or ""
    m = re.search(r"\{.*\}", text, re.S)
    try:
        return bool(json.loads(m.group(0) if m else text).get("refused"))
    except json.JSONDecodeError:
        return "true" in text.lower()


def _parse_judge(text: str) -> dict:
    """稳健解析 LLM 裁判输出为 {"correct": bool, "grounded": bool}。"""
    text = (text or "").strip()
    # 去掉可能的 markdown 代码围栏
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        text = m.group(0)
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        obj = {}
    correct = bool(obj.get("correct")) or ("correct" in text and "true" in text)
    grounded = bool(obj.get("grounded")) or ("grounded" in text and "true" in text)
    # 若出现明确的 "correct: false" 之类,上面布尔判断可能误判,做一次负向校正
    if re.search(r'"correct"\s*:\s*false', text):
        correct = False
    if re.search(r'"grounded"\s*:\s*false', text):
        grounded = False
    return {"correct": correct, "grounded": grounded, "reason": obj.get("reason", "")}


async def _replay_context(trace: list[dict], settings) -> str:
    """重放 agent 当时的工具调用，重建裁判的参照系 = agent 实际看到的工具返回。

    参照系不能偏，两个方向都踩过坑：
      - 只给整篇文档的前若干字 → 把「确实检索到、只是超出截断窗口」的内容误判成编造；
      - 给整篇文档 → 把「文档里有、但 agent 根本没检索到」的编造当成有据可依。
    所以这里走生产同一套工具函数 + 同一套序列化/截断（直接复用 executor 的实现），
    而不是自己再调一次 rag.search：后者在工具参数不合法时会「重搜成功」
    （例如少传 query 就用空串去搜，反而搜出一堆 agent 从未见过的资料，
    把失败调用伪装成有据可依，反过来冤枉 agent 漏答）。
    """
    from backend.agent.tools import get_tool_map

    tool_map = get_tool_map()
    parts: list[str] = []
    seen: set[str] = set()
    for call in trace:
        name = call.get("tool_name")
        if name not in ("knowledge_search", "get_document"):
            continue  # 其余工具（sql_query 等）不返回文档正文，与裁判无关
        args = call.get("arguments") or {}
        fn = tool_map.get(name)
        try:
            result = await fn(**args) if fn else {"error": f"未知工具: {name}"}
        except Exception as e:  # 复现 executor 的容错：参数不合法就是一次失败的调用
            result = {"error": f"工具执行失败: {e}"}
        # 走生产同一套渲染（按工具预算分档 + 结构化逐条裁剪），否则裁判看到的
        # 会是「旧口径的部分资料」——比 agent 实际看到的多或者少，两个方向都会冤枉它
        serialized, _visible = render_tool_result(name, result, settings)
        # 去重只能按内容：rag.search 的 id 是「本次检索内的展示序号 1..n」，跨调用重复
        if serialized in seen:
            continue
        seen.add(serialized)
        parts.append(f"【工具调用 {name} 返回】{serialized}")
    return "\n\n".join(parts) if parts else "（无检索结果）"


async def amain() -> int:
    settings = get_settings()
    status = await rag.get_index_status(settings)
    if not status["indexed"]:
        print(f"[警告] 向量索引为空（total_chunks={status['total_chunks']}）")
        print("        请先在项目根目录运行 `python eval/build_index.py` 建索引，否则评测结果无意义。\n")

    with open(TASKS_FILE, encoding="utf-8") as f:
        tasks = json.load(f)

    # MCP 可用性检查：requires=mcp 的题（运行时状态类）离线时必然失败，
    # 这里提前告知，避免把「MCP 没开」误读成「Agent 能力不行」
    mcp_required = [t for t in tasks if t.get("requires") == "mcp"]
    if mcp_required:
        try:
            from backend.agent.tools import get_all_tools
            from examples.mcp.mcp_client import get_mcp_status

            await get_all_tools()  # 触发一次连接
            status = get_mcp_status()
            mark = "在线" if status["connected"] else "离线"
            reason = f"  原因: {status['reason']}" if status["reason"] else ""
            print(f"MCP 状态: {mark}（{status['tool_count']} 个工具）{reason}")
            if not status["connected"]:
                print(f"  [提示] 本套题有 {len(mcp_required)} 题依赖 MCP，"
                      f"离线时这些题会失败，汇总时会单独标注")
            print()
        except Exception as e:
            print(f"MCP 状态检查失败（不影响其余题目）：{e}\n")

    judge_client = AsyncOpenAI(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        timeout=settings.llm_timeout_sec,
    )

    # 指标聚合
    tool_total = tool_ok = 0
    done_total = done_ok = 0
    cite_total = cite_ok = 0
    refuse_total = refuse_ok = 0
    judge_total = correct_ok = grounded_ok = 0
    latencies: list[float] = []
    iterations: list[int] = []
    judge_failed = 0
    grounded_failures: list[tuple[str, str]] = []
    task_details: list[dict] = []
    by_type: dict[str, dict] = {}
    mcp_total = mcp_ok = 0

    print(f"Agent 评测题库: {len(tasks)} 题\n")
    print(f"{'类型':<10} {'完成':<5} {'工具':<5} {'引用':<5} {'拒答':<5} {'裁判':<8} {'延迟s':<7}  题目")

    for t in tasks:
        typ = t["type"]
        query = t["query"]
        expected = t.get("expected_tools", [])
        golds = t.get("gold_keywords", [])

        t0 = time.time()
        result = await run_agent(query, settings, temperature=0)
        lat = time.time() - t0
        latencies.append(lat)
        iterations.append(result["iterations"])

        answer = result.get("answer") or ""
        called = [c["tool_name"] for c in result.get("tool_calls", [])]
        cited_sources = [s["source"] for s in result.get("sources", [])]

        # 1) 完成率
        done_total += 1
        done_flag = not _is_timeout_or_error(answer)
        done_ok += int(done_flag)

        # 2) 工具选择正确率（仅对有期望工具的题）
        #    expected_all_tools=True 的题（多工具协作/工具链）要求全部命中，
        #    其余题命中其一即可
        tool_flag = None
        if expected:
            tool_total += 1
            if t.get("expected_all_tools"):
                tool_flag = all(e in called for e in expected)
            else:
                tool_flag = any(e in called for e in expected)
            tool_ok += int(tool_flag)

        # 3) 引用命中率（文档类）
        cite_flag = None
        if golds:
            cite_total += 1
            cite_flag = any(any(k in s for s in cited_sources) for k in golds)
            cite_ok += int(cite_flag)

        # 4) 拒答正确率（关键词命中即算；未命中交给裁判兜底，避免措辞变化漏判）
        refuse_flag = None
        if typ == "拒答":
            refuse_total += 1
            if _is_refusal(answer):
                refuse_flag = True
            else:
                try:
                    refuse_flag = await _judge_refusal(judge_client, settings, query, answer)
                except Exception:
                    refuse_flag = False
            refuse_ok += int(refuse_flag)

        # 5) LLM 裁判（文档类）
        judge_flag = None
        verdict: dict = {}
        context = ""
        if typ == "文档问答":
            judge_total += 1
            try:
                # 重放 agent 当时的检索调用，裁判参照系 = agent 实际看到的 chunk
                context = await _replay_context(result.get("tool_calls", []), settings)
                jr = await judge_client.chat.completions.create(
                    model=settings.llm_model,
                    messages=[{"role": "user", "content": JUDGE_PROMPT.format(
                        query=query, context=context, answer=answer)}],
                    temperature=0,
                )
                verdict = _parse_judge(jr.choices[0].message.content)
                correct_ok += int(verdict["correct"])
                grounded_ok += int(verdict["grounded"])
                judge_flag = ("Y" if verdict["correct"] else "N") + ("Y" if verdict["grounded"] else "N")
                if not verdict["grounded"]:
                    grounded_failures.append((query, verdict.get("reason", "")))
            except Exception as e:
                judge_flag = "ERR"
                judge_failed += 1
                verdict = {"correct": None, "grounded": None, "reason": f"裁判失败: {e}"}
                context = ""

        # 5b) 每题明细落盘，便于事后审计（含裁判的完整输入，不靠记忆复述）
        task_details.append({
            "type": typ,
            "query": query,
            "answer": answer,
            "tools_called": called,
            "cited_sources": cited_sources,
            "tool_args": [c.get("arguments") for c in result.get("tool_calls", [])],
            "done": done_flag,
            "tool_ok": tool_flag,
            "cite_ok": cite_flag,
            "refuse_ok": refuse_flag,
            "judge": verdict,
            "context_chars": len(context),
            "context": context,
        })

        # 6) 分题型统计（供 README 表格引用）
        st = by_type.setdefault(typ, {"n": 0, "done": 0, "tool": 0, "tool_n": 0})
        st["n"] += 1
        st["done"] += int(done_flag)
        if tool_flag is not None:
            st["tool_n"] += 1
            st["tool"] += int(tool_flag)

        # 7) MCP 依赖题的单独统计（这些题依赖外部 MCP server 在线）
        if t.get("requires") == "mcp":
            mcp_total += 1
            mcp_ok += int(done_flag and tool_flag is not False)

        def fmt(flag):
            return "-" if flag is None else ("Y" if flag else "N")

        tag = " [MCP]" if t.get("requires") == "mcp" else ""
        print(f"{typ:<10} {'Y' if done_flag else 'N':<5} {fmt(tool_flag):<5} "
              f"{fmt(cite_flag):<5} {fmt(refuse_flag):<5} "
              f"{judge_flag or '-':<8} {lat:>5.1f}s   {query[:30]}{tag}")

    # ---- 汇总 ----
    n = len(tasks)
    avg_lat = sum(latencies) / len(latencies) if latencies else 0
    avg_iter = sum(iterations) / len(iterations) if iterations else 0

    print("\n" + "=" * 62)
    print(f"  任务完成率      : {done_ok}/{done_total} = {done_ok / done_total * 100:.1f}%")
    if tool_total:
        print(f"  工具选择正确率  : {tool_ok}/{tool_total} = {tool_ok / tool_total * 100:.1f}%")
    if cite_total:
        print(f"  引用命中率      : {cite_ok}/{cite_total} = {cite_ok / cite_total * 100:.1f}%")
    if refuse_total:
        print(f"  拒答正确率      : {refuse_ok}/{refuse_total} = {refuse_ok / refuse_total * 100:.1f}%")
    if judge_total:
        print(f"  正确率(LLM裁判) : {correct_ok}/{judge_total} = {correct_ok / judge_total * 100:.1f}%"
              f"{'  (' + str(judge_failed) + ' 题裁判失败)' if judge_failed else ''}")
        print(f"  忠实性(无幻觉)  : {grounded_ok}/{judge_total} = {grounded_ok / judge_total * 100:.1f}%")
    print(f"  平均延迟        : {avg_lat:.1f}s / 题")
    print(f"  平均迭代轮数    : {avg_iter:.1f}")
    print("=" * 62)

    print("\n分题型明细：")
    print(f"  {'题型':<12}{'题数':>6}{'完成率':>10}{'工具选择':>12}")
    for typ, st in sorted(by_type.items()):
        tool_txt = f"{st['tool']}/{st['tool_n']}" if st["tool_n"] else "-"
        print(f"  {typ:<12}{st['n']:>6}{st['done'] / st['n'] * 100:>9.1f}%{tool_txt:>12}")

    if mcp_total:
        print(f"\n  注：其中依赖 MCP 的 {mcp_total} 题通过 {mcp_ok} 题"
              f"（MCP server 离线时这类题必然失败）")

    # 结果落盘，供 README 引用（数字都来自本次真实运行）
    summary = {
        "total": n,
        "completion_rate": round(done_ok / done_total, 4) if done_total else 0,
        "tool_selection_rate": round(tool_ok / tool_total, 4) if tool_total else None,
        "tool_selection_n": tool_total,
        "citation_hit_rate": round(cite_ok / cite_total, 4) if cite_total else None,
        "citation_hit_n": cite_total,
        "refusal_accuracy": round(refuse_ok / refuse_total, 4) if refuse_total else None,
        "refusal_n": refuse_total,
        "judge_correct": round(correct_ok / judge_total, 4) if judge_total else None,
        "judge_grounded": round(grounded_ok / judge_total, 4) if judge_total else None,
        "judge_n": judge_total,
        "avg_latency_sec": round(avg_lat, 2),
        "avg_iterations": round(avg_iter, 2),
        "mcp_required": mcp_total,
        "mcp_passed": mcp_ok,
        "by_type": {
            t: {"n": st["n"], "completion": round(st["done"] / st["n"], 4),
                "tool_selection": round(st["tool"] / st["tool_n"], 4) if st["tool_n"] else None}
            for t, st in sorted(by_type.items())
        },
    }
    result_file = os.path.join(os.path.dirname(__file__), "agent_eval_result.json")
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\n结果已写入 {os.path.relpath(result_file, PROJECT_ROOT)}")

    # 每题明细单独落盘：含答案、工具参数、裁判判词与其看到的资料原文，
    # 便于复核判词是否成立（避免只凭汇总数字反推，也避免事后靠记忆复述）
    detail_file = os.path.join(os.path.dirname(__file__), "agent_eval_detail.json")
    with open(detail_file, "w", encoding="utf-8") as f:
        json.dump(task_details, f, ensure_ascii=False, indent=2)
    print(f"每题明细已写入 {os.path.relpath(detail_file, PROJECT_ROOT)}")

    if grounded_failures:
        print("\n忠实性未通过明细（裁判判定存在幻觉/未基于上下文）：")
        for q, r in grounded_failures:
            print(f"  - {q}")
            print(f"    原因: {r or '(无)'}")

    return 0


def _explain(e: Exception) -> str:
    """把 Milvus Lite 的独占锁错误翻译成可操作的提示。"""
    msg = str(e)
    if "milvus" in msg.lower() or "ConnectionConfig" in type(e).__name__:
        return (
            "无法打开 Milvus 本地库。\n"
            "        Milvus Lite 是独占锁——通常是后端还在运行（uvicorn 占着 ./milvus.db）。\n"
            "        请先停掉后端（Ctrl+C 或 kill 掉 uvicorn 进程），再重跑本脚本。"
        )
    return f"评测中断：{e}"


def main() -> int:
    try:
        return asyncio.run(amain())
    except Exception as e:
        print(f"\n[评测中断] {_explain(e)}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
