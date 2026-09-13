"""
上下文预算修复的复现与断言 —— 改动前 FAIL、改动后 PASS 的那几条。

用法（必须在 agent/ 根目录，且后端 uvicorn 已停止——Milvus Lite 是单进程独占锁）：
    python eval/repro_context_budget.py

为什么要有这个脚本：
    这三处缺陷都是「Agent 想看的资料给不到它」，症状（答"未找到"）远在病灶之外，
    靠读代码很容易误判。把当时用一次性脚本量出来的事实固化成断言，
    以后改检索/截断时能立刻发现回归。

分组（尚未修好的组会如实 FAIL——这就是它们当前的状态）：
    A 预算不变量  纯合成数据，不连 Milvus、不调 LLM，几秒跑完
    B 实检索预算  跑 rag.search，需要 Milvus + embedding API
    C 长文档可达  十二五规划里那句"减少8%"必须在工具返回文本内
    D source 精查 带 source 时不能因文档级去重/候选池过小把目标 chunk 挤掉
"""
import asyncio
import json
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

from backend.core.config import get_settings
from backend.core.tool_output import render_tool_result, serialize, tool_result_limit
from backend.services import rag, vector_store

# 上一轮实测定位到的靶子：答案在《十二五规划纲要》这篇里，且该 chunk 是 BM25 全量第 0 名
DOC = "国民经济和社会发展第十二个五年规划纲要_滚动新闻.txt"
TARGET = "减少8%"

_checks: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    _checks.append((name, ok, detail))


def _fake_hits(n: int, text_len: int) -> dict:
    """构造一条 knowledge_search 结果，模拟 n 个长片段。"""
    return {
        "found": True,
        "sources": [
            {
                "id": i,
                "source": f"某公司管理制度汇编第{i}版.pdf",
                "text": "管理制度正文。" * (text_len // 7 + 1),
                "score": 0.8123,
            }
            for i in range(1, n + 1)
        ],
        "summary": f"共找到{n}条相关资料",
    }


def section_a(settings) -> None:
    """A 预算不变量：序列化后必须 <= 预算，且始终是合法 JSON。"""
    for name, n, text_len in [
        ("knowledge_search", 8, 5000),
        ("knowledge_search", 3, 5000),
        ("knowledge_search", 1, 20000),
        ("knowledge_search", 10, 1000),
    ]:
        limit = tool_result_limit(name, settings)
        text, visible = render_tool_result(name, _fake_hits(n, text_len), settings)
        tag = f"A[{name} n={n} len={text_len}]"
        check(f"{tag} 文本不超预算", len(text) <= limit, f"{len(text)} / {limit}")
        try:
            parsed = json.loads(text)
            parse_ok = True
        except json.JSONDecodeError as e:
            parsed, parse_ok = {}, False
            check(f"{tag} JSON 合法", False, str(e)[:60])
        if parse_ok:
            check(f"{tag} JSON 合法", True)
            check(f"{tag} sources 是列表", isinstance(parsed.get("sources"), list))
            check(f"{tag} 每条 text 非空", all(s.get("text") for s in parsed["sources"]))
            check(f"{tag} id 完整", [s["id"] for s in parsed["sources"]] == list(range(1, len(parsed["sources"]) + 1)))
            check(f"{tag} visible 与文本一致", serialize(visible) == text)

    # 兜底预算：非结构化工具仍走 agent_tool_result_max_chars
    long_sql = {"success": True, "rows": [{"x": "数据" * 5000}], "row_count": 1}
    text, _ = render_tool_result("sql_query", long_sql, settings)
    check("A[sql_query] 走兜底预算", len(text) <= settings.agent_tool_result_max_chars,
          f"{len(text)} / {settings.agent_tool_result_max_chars}")
    check("A[默认] 未知工具走兜底预算", tool_result_limit("mcp_some_tool", settings) == settings.agent_tool_result_max_chars)


async def section_bc(settings) -> str:
    """B 实检索预算 + C 长文档可达性。返回 get_document 的正文供后续断句。"""
    from backend.tools.search_document import get_document_fn, knowledge_search_fn

    await vector_store.ensure_collection(settings)
    limit = tool_result_limit("knowledge_search", settings)
    res = await knowledge_search_fn("十二五规划 化学需氧量 二氧化硫 排放量 减少")
    text, _ = render_tool_result("knowledge_search", res, settings)
    check("B knowledge_search 不超预算", len(text) <= limit, f"{len(text)} / {limit}")
    check("B knowledge_search 有结果", bool(res.get("sources")), f"{len(res.get('sources', []))} 条")
    check("B 片段文本未被静默清空", all(s.get("text") for s in res.get("sources", [])))

    doc = await get_document_fn(DOC)
    check("C 目标文档读得到", doc.get("found"), DOC[:20])
    check(f"C 返回文本含「{TARGET}」", TARGET in (doc.get("text") or ""),
          f"返回 {len(doc.get('text') or '')} 字 / 全文 {doc.get('total_chars')} 字")
    return doc.get("text") or ""


async def section_d(settings) -> None:
    """D 带 source 精查：目标 chunk 不能被文档级去重或候选池挤掉。"""
    await vector_store.ensure_collection(settings)
    for q in [
        "十二五 主要污染物排放总量 化学需氧量 二氧化硫 减少8%",
        "化学需氧量 二氧化硫 排放分别减少多少",
    ]:
        r = await rag.search(q, settings, source=DOC, verbose=False)
        hits = [c for c in r if TARGET in (c.get("text") or "")]
        check(f"D[source 精查] 「{q[:16]}…」命中 {TARGET}", bool(hits), f"返回 {len(r)} 条，命中 {len(hits)} 条")


async def main() -> int:
    settings = get_settings()
    print("== A 预算不变量（合成数据）==")
    section_a(settings)
    try:
        print("\n== B 实检索预算 / C 长文档可达 ==")
        await section_bc(settings)
        print("\n== D source 精查 ==")
        await section_d(settings)
    except Exception as e:
        check("B/C/D 执行", False, f"{type(e).__name__}: {e}")

    failed = [c for c in _checks if not c[1]]
    for name, ok, detail in _checks:
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {name}" + (f"  ({detail})" if detail else ""))
    print(f"\n{len(_checks) - len(failed)}/{len(_checks)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
