"""
多智能体协作 —— 规划(Planner) → 执行(Executor) → 反思(Reflector)。

把复杂的用户问题交给三层协作：
    1. Planner  ：LLM 把问题拆解成 2-4 个可独立执行的子任务
    2. Executor ：复用现有单 agent 循环(run_agent)逐个执行子任务（含 RAG + SQL + MCP 全部工具）
    3. Reflector：LLM 综合各子任务结果，产出最终回答

流式事件（供前端实时展示）：
    status     阶段提示
    plan       规划结果 {steps: [...]}
    sub_result 某个子任务执行完 {index, task, answer}
    answer     最终回答增量
    done       结束 {answer, iterations}

这是对单 agent 循环的「编排层」升级，演示多智能体协作模式。
"""
import json
import re
from collections.abc import AsyncIterator

from openai import AsyncOpenAI

from backend.agent.executor import create_agent_client, run_agent
from backend.core.config import Settings

_PLAN_PROMPT = """你是任务规划专家。把用户的复杂问题拆解成 2~4 个可独立执行的子任务，
每个子任务用一句清晰的话描述，能交给一个「可调用工具检索知识库文档、查询数据库」的执行 agent 直接完成。

要求：
- 只输出严格的 JSON 字符串数组，不要输出任何其他文字、不要 markdown 代码块
- 例如：["查询2023年GDP增长情况", "查询2024年GDP增长情况", "统计最近上传的文件数"]

用户问题：{query}
"""

_REFLECT_PROMPT = """你是综合总结专家。根据用户问题和各子任务的执行结果，综合出最终回答。

用户问题：
{query}

各子任务执行结果：
{subtask_results}

请综合以上结果，直接回答用户问题。要求：
- 严格基于子任务结果作答，不要编造
- 若某个子任务没有找到结果，如实说明
- 信息脱敏：不得泄露数据库表名、字段名、SQL、代码、文件路径等内部细节，用业务语言转述
- 使用得体的中文与 Markdown 排版，重点术语用 **加粗**
"""


def _parse_plan(raw: str, query: str) -> list[str]:
    """从 LLM 输出里稳健解析 JSON 数组；失败则退化为「整题作为一个子任务」。"""
    text = (raw or "").strip()
    m = re.search(r"\[.*\]", text, re.S)
    if m:
        text = m.group(0)
    try:
        arr = json.loads(text)
        if isinstance(arr, list):
            steps = [str(x).strip() for x in arr if str(x).strip()]
            if steps:
                return steps
    except json.JSONDecodeError:
        pass
    return [query]


async def _stream_text(client: AsyncOpenAI, model: str, prompt: str, temperature: float | None):
    """流式产出纯文本 content 增量。"""
    kwargs: dict = dict(model=model, messages=[{"role": "user", "content": prompt}], stream=True)
    if temperature is not None:
        kwargs["temperature"] = temperature
    stream = await client.chat.completions.create(**kwargs)
    async for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content


async def _call(client: AsyncOpenAI, model: str, prompt: str, temperature: float | None) -> str:
    """非流式调用，返回文本。"""
    kwargs: dict = dict(model=model, messages=[{"role": "user", "content": prompt}])
    if temperature is not None:
        kwargs["temperature"] = temperature
    resp = await client.chat.completions.create(**kwargs)
    return resp.choices[0].message.content or ""


async def run_multi_agent_stream(
    query: str,
    settings: Settings,
    history: list[dict] | None = None,
    temperature: float | None = None,
) -> AsyncIterator[dict]:
    """多智能体主流程(流式)。history 当前未使用，预留对齐单 agent 签名。"""
    client = create_agent_client(settings)
    model = settings.llm_model

    # 1. Planner
    yield {"type": "status", "message": "正在规划任务分解…"}
    plan_raw = await _call(client, model, _PLAN_PROMPT.format(query=query), temperature)
    plan = _parse_plan(plan_raw, query)
    yield {"type": "plan", "steps": plan}

    # 2. Executor（逐个执行子任务）
    results: list[dict] = []
    for i, task in enumerate(plan, 1):
        yield {"type": "status", "message": f"正在执行子任务 {i}/{len(plan)}：{task}"}
        r = await run_agent(task, settings, temperature=temperature)
        results.append({"task": task, "answer": r["answer"], "tool_calls": r["tool_calls"], "sources": r["sources"]})
        yield {"type": "sub_result", "index": i, "task": task, "answer": r["answer"]}

    # 3. Reflector（流式综合）
    yield {"type": "status", "message": "正在综合各子任务结果…"}
    subtask_text = "\n\n".join(
        f"【子任务 {i + 1}】{r['task']}\n结果：{r['answer']}" for i, r in enumerate(results)
    )
    reflect_prompt = _REFLECT_PROMPT.format(query=query, subtask_results=subtask_text)

    answer_parts: list[str] = []
    async for delta in _stream_text(client, model, reflect_prompt, temperature):
        answer_parts.append(delta)
        yield {"type": "answer", "delta": delta}

    full = "".join(answer_parts).strip() or "抱歉，模型未返回有效回答"
    yield {"type": "done", "answer": full, "iterations": len(plan), "sources": [], "trace": []}


async def run_multi_agent(
    query: str,
    settings: Settings,
    history: list[dict] | None = None,
    temperature: float | None = None,
) -> dict:
    """非流式封装：聚合为 {answer, plan, sub_results}。"""
    plan: list[str] = []
    sub_results: list[dict] = []
    answer = ""
    async for event in run_multi_agent_stream(query, settings, history, temperature):
        if event["type"] == "plan":
            plan = event["steps"]
        elif event["type"] == "sub_result":
            sub_results.append({"task": event["task"], "answer": event["answer"]})
        elif event["type"] == "done":
            answer = event["answer"]
    return {"answer": answer, "plan": plan, "sub_results": sub_results}
