"""
Agent 执行循环（异步，流式 ReAct）

手写 Function Calling 循环（面试亮点，勿换成框架）：

    run_agent_stream 是一个异步生成器，逐个 yield 事件 dict（type 字段区分）：
        status      阶段提示         {type, message}
        tool_call   决定调用工具      {type, name, arguments}
        tool_result 工具执行结果      {type, name, summary, found?, row_count?}
        answer      最终回答增量      {type, delta}
        sources     引用来源清单      {type, sources: [{source, score}]}
        done        结束             {type, answer, iterations, sources}
        error       出错             {type, message}

    run_agent 是其非流式封装，内部迭代同一生成器聚合成 dict。

要点：
    - 所有 LLM 调用走 stream=True，实时解析 content / tool_calls 增量
    - 多个 tool_calls 用 asyncio.gather 并行执行
    - 工具结果统一截断（agent_tool_result_max_chars），防止上下文爆炸
    - 多轮记忆：system + 最近 N 条历史 + 当前问题
"""
import asyncio
import json
from collections.abc import AsyncIterator

from openai import AsyncOpenAI

from backend.agent.tools import get_all_tools
from backend.core.config import Settings


def create_agent_client(settings: Settings) -> AsyncOpenAI:
    """创建 Agent 用的异步 OpenAI 客户端。"""
    return AsyncOpenAI(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        timeout=settings.llm_timeout_sec,
    )


# 「运行时状态」类工具（由 MCP 动态提供）。只有它们真的在本次可用工具里时,
# 才把「必须调工具、禁止凭记忆猜」这条规则写进 prompt——否则 MCP server 没连上时,
# 模型会被要求去调用一个根本不存在的工具。
_RUNTIME_STATE_TOOLS = ("get_current_time", "get_system_info")

# 每个手写工具在 prompt 里的一句话简介;未列出的(MCP 动态工具)回退用 schema 里的 description
_TOOL_BRIEF = {
    "knowledge_search": "knowledge_search: 搜索知识库文档(制度/流程/规定等),返回带编号 [id] 的文档片段",
    "get_document": "get_document: 读取指定文档的完整内容",
    "list_tables": "list_tables: 查看数据库有哪些表及其字段结构",
    "sql_query": "sql_query: 查询结构化数据(仅SELECT),写SQL前先调用 list_tables 了解结构",
}

# 与工具可用性无关的通用规则(编号里留出 1.5 的位置给运行时规则)
_BASE_RULES = [
    "1. 严禁编造、严禁补充记忆:回答只能基于工具实际返回的内容;不要加入你自己知道、但检索结果里没有的细节(具体年份、数字、条款等,检索结果里没有就不得写出);没有相关信息的就如实说\"未找到相关信息\"",
    "2. 引用标注:凡引用某条资料,用 [编号] 在对应位置标注,并在回答结尾列出引用来源",
    "3. 信息脱敏——严禁泄露内部实现细节:回答中不得出现数据库表名、字段名、SQL 语句、代码、函数/接口名、文件路径等内部标识符。一律用业务语言转述结论(如说\"目前共 2 份资料\",而不是\"uploaded_files 表里有 2 条记录\");引用来源时也只描述资料主题,不写表名/字段名",
    "4. 直接给出结论,不要复述你的检索/思考过程:禁止写\"我来帮你查找\"\"找到了某文档\"\"我来读取该文档\"之类的自我叙述,直接从\"根据/基于…\"开始作答",
    "5. 连续检索多次(≥2次)仍无结果时,如实告知用户,不要空转",
    "6. 使用得体的中文与 Markdown 排版,重点术语用 **加粗**(加粗符须紧贴文字)",
]


def _tool_brief(tool: dict) -> str:
    """工具在 prompt 里的一行简介;MCP 动态工具取 schema description 的第一句。"""
    name = tool["function"]["name"]
    brief = _TOOL_BRIEF.get(name)
    if brief:
        return brief
    desc = (tool["function"].get("description") or "").strip()
    first = desc.split("。")[0].strip() if desc else ""
    return f"{name}: {first}" if first else name


def build_system_prompt(tools_schema: list[dict]) -> str:
    """按「本次真正可用的工具」动态生成系统提示（ReAct 风格）。

    工具可用性会反过来影响 Agent policy:
        - 可用工具清单只列本次真实注册的工具(MCP 连不上就不会出现运行时工具)
        - 依赖运行时工具的强制规则(1.5)只在对应工具可用时才出现
    这样 MCP server 掉线时,模型不会去调用一个不存在的工具。
    """
    names = [t["function"]["name"] for t in tools_schema]
    tool_lines = "\n".join(f"- {_tool_brief(t)}" for t in tools_schema)

    rules = [_BASE_RULES[0]]
    runtime_available = [n for n in _RUNTIME_STATE_TOOLS if n in names]
    if runtime_available:
        rules.append(
            "1.5. 运行时状态必须查工具:涉及当前时间、操作系统、运行环境、所在机器等"
            f"\"运行时状态\"的问题,你无法凭训练知识得知正确答案,必须调用对应工具"
            f"({'/'.join(runtime_available)})获取,禁止凭记忆猜测(不要凭空写\"Linux\""
            "\"/home/user\"这类)"
        )
    rules.extend(_BASE_RULES[1:])

    return f"""
你是一个企业内部知识库问答助手,可以调用工具检索文档、查询数据库,最终基于工具返回的真实结果作答。

可用工具:
{tool_lines}

工作方式(ReAct):
1. 分析用户问题,判断需要哪些信息
2. 调用合适的工具获取信息(可一次并行调用多个工具)
3. 观察工具结果:
   - 信息足够 → 整理回答
   - 结果为空或不足 → 换关键词、换工具重试,不要轻易放弃
4. 回答前自检:答案是否完全基于工具返回的真实结果?是否完整回答了用户问题?

硬性规则:
{chr(10).join(rules)}
""".strip()


def _truncate(text: str, limit: int) -> str:
    """把工具结果截断到 limit 字符,防止撑爆上下文。"""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + f"...(已截断,原文{len(text)}字)"


def _serialize(result) -> str:
    """把工具返回结果转成字符串(dict 转 JSON)。"""
    if isinstance(result, dict):
        return json.dumps(result, ensure_ascii=False, default=str)
    return str(result)


_TOOL_ACTIONS = {
    "knowledge_search": "检索知识库",
    "get_document": "读取文档",
    "list_tables": "查看数据库表结构",
    "sql_query": "查询数据库",
}


def _tool_action(name: str) -> str:
    """工具名 → 人类可读动作,用于状态提示。"""
    return _TOOL_ACTIONS.get(name, "调用工具")


def _tool_summary(name: str, result) -> str:
    """生成给前端看的工具结果一句话摘要。"""
    if isinstance(result, dict):
        if name == "knowledge_search":
            return result.get("summary", "完成检索")
        if name == "get_document":
            return result.get("summary", "已读取文档")
        if name == "sql_query":
            if result.get("success"):
                return f"查询成功,返回 {result.get('row_count', 0)} 行"
            return f"查询失败: {result.get('error', '')}"
        if name == "list_tables":
            return f"共 {result.get('table_count', 0)} 张表"
    return "工具执行完成"


def _build_messages(
    query: str, history: list[dict], settings: Settings, tools_schema: list[dict]
) -> list[dict]:
    """构建 LLM messages：system(按可用工具动态生成) + 最近 N 条历史 + 当前问题。"""
    messages = [{"role": "system", "content": build_system_prompt(tools_schema)}]
    for m in (history or [])[-(settings.agent_max_history):]:
        role = m.get("role")
        content = (m.get("content") or "").strip()
        if not content:
            continue
        if role not in ("user", "assistant"):
            role = "user"
        messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": query})
    return messages


async def _stream_completion(
    client: AsyncOpenAI,
    model: str,
    messages: list[dict],
    tools: list[dict],
    temperature: float | None = None,
):
    """单次流式 LLM 调用,产出 ("answer", 完整文本) 或 ("tool_calls", [...])。

    内容先缓冲再定去留:deepseek-chat 调工具前会先吐一句"思考"铺垫(如
    "I'll search the knowledge base..."),这句 content 与 tool_calls 同轮出现,
    属于思考过程,不能混进最终答案。因此:
        - 本轮带 tool_calls → 丢弃 content,只产出 tool_calls
        - 本轮无 tool_calls → content 即最终答案,整体产出
    """
    kwargs: dict = dict(model=model, messages=messages, tools=tools, tool_choice="auto", stream=True)
    if temperature is not None:
        kwargs["temperature"] = temperature
    stream = await client.chat.completions.create(**kwargs)
    content_parts: list[str] = []
    tool_acc: dict[int, dict] = {}
    async for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta.content:
            content_parts.append(delta.content)
        if delta.tool_calls:
            for tc in delta.tool_calls:
                e = tool_acc.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
                if tc.id:
                    e["id"] = tc.id
                if tc.function and tc.function.name:
                    e["name"] = tc.function.name
                if tc.function and tc.function.arguments:
                    e["arguments"] += tc.function.arguments

    if tool_acc:
        tool_calls = [
            {
                "id": tool_acc[idx]["id"] or f"call_{idx}",
                "type": "function",
                "function": {
                    "name": tool_acc[idx]["name"],
                    "arguments": tool_acc[idx]["arguments"] or "{}",
                },
            }
            for idx in sorted(tool_acc)
        ]
        yield ("tool_calls", tool_calls)
    else:
        yield ("answer", "".join(content_parts))


async def _execute_tool_calls(tool_calls: list[dict], tool_map: dict) -> list[tuple]:
    """并行执行所有 tool_calls,返回 [(tool_call_id, name, args_dict, result)]。"""
    async def _one(tc: dict) -> tuple:
        name = tc["function"]["name"]
        try:
            args = json.loads(tc["function"]["arguments"] or "{}")
        except json.JSONDecodeError as e:
            return tc["id"], name, {}, {"error": f"参数解析失败: {e}"}
        fn = tool_map.get(name)
        if fn is None:
            return tc["id"], name, args, {"error": f"未知工具: {name}"}
        try:
            result = await fn(**args)
        except Exception as e:
            return tc["id"], name, args, {"error": f"工具执行失败: {e}"}
        return tc["id"], name, args, result

    return await asyncio.gather(*(_one(tc) for tc in tool_calls))


async def run_agent_stream(
    query: str,
    history: list[dict],
    settings: Settings,
    temperature: float | None = None,
) -> AsyncIterator[dict]:
    """Agent 主循环(流式),逐事件 yield。history 为当前问题之前的 [{role, content}]。

    temperature: 传 None 用 LLM 默认值;评测时传 0 保证可复现。
    """
    client = create_agent_client(settings)
    # 先拿到本次真实可用的工具(MCP 可能掉线),system prompt 要据此生成
    tools_schema, tool_map = await get_all_tools()
    messages = _build_messages(query, history, settings, tools_schema)

    trace: list[dict] = []
    collected_sources: dict[str, float] = {}  # source -> score(去重)

    # 立即产出首个状态,避免用户面对空白干等
    yield {"type": "status", "message": "正在分析你的问题…"}

    for i in range(settings.agent_max_iterations):
        answer_parts: list[str] = []
        tool_calls: list[dict] | None = None
        if i > 0:
            yield {"type": "status", "message": "正在结合检索结果继续分析…"}

        try:
            async for kind, payload in _stream_completion(client, settings.llm_model, messages, tools_schema, temperature):
                if kind == "answer":
                    answer_parts.append(payload)
                    yield {"type": "answer", "delta": payload}
                elif kind == "tool_calls":
                    tool_calls = payload
        except Exception as e:
            yield {"type": "error", "message": f"LLM调用失败:{e}"}
            return

        # 无工具调用 → 最终回答
        if tool_calls is None:
            full = "".join(answer_parts).strip() or "抱歉,模型未返回有效回答"
            sources = [{"source": s, "score": round(v, 4)} for s, v in collected_sources.items()]
            yield {"type": "sources", "sources": sources}
            yield {"type": "done", "answer": full, "iterations": i + 1,
                   "sources": sources, "trace": trace}
            return

        # 有工具调用 → 先告知动作,再并行执行
        for tc in tool_calls:
            try:
                args = json.loads(tc["function"]["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            name = tc["function"]["name"]
            yield {"type": "status", "message": f"正在{_tool_action(name)}…"}
            yield {"type": "tool_call", "name": name, "arguments": args}

        results = await _execute_tool_calls(tool_calls, tool_map)

        # 追加 assistant(tool_calls) + tool 消息,并按序产出 tool_result
        messages.append({"role": "assistant", "content": None, "tool_calls": tool_calls})
        for tc_id, name, args, result in results:
            serialized = _truncate(_serialize(result), settings.agent_tool_result_max_chars)
            messages.append({"role": "tool", "tool_call_id": tc_id, "content": serialized})

            # 收集引文来源(knowledge_search / get_document)
            if isinstance(result, dict):
                if name == "knowledge_search" and result.get("found"):
                    for s in result.get("sources", []):
                        collected_sources.setdefault(s.get("source", ""), float(s.get("score", 0.0)))
                elif name == "get_document" and result.get("found"):
                    collected_sources.setdefault(result.get("source", ""), 0.0)

            summary = _tool_summary(name, result)
            trace.append({"tool_name": name, "arguments": args, "summary": summary})
            event: dict = {"type": "tool_result", "name": name, "summary": summary}
            if isinstance(result, dict):
                if "found" in result:
                    event["found"] = result["found"]
                if "row_count" in result:
                    event["row_count"] = result["row_count"]
            yield event

    # 达到最大迭代仍未结束
    yield {"type": "error", "message": "抱歉,处理超时,请简化问题后重试"}
    yield {"type": "done", "answer": "抱歉,处理超时,请简化问题后重试", "iterations": settings.agent_max_iterations,
           "sources": [], "trace": trace}


async def run_agent(
    query: str,
    settings: Settings,
    history: list[dict] | None = None,
    temperature: float | None = None,
) -> dict:
    """非流式封装:迭代 run_agent_stream,聚合成 {answer, tool_calls, iterations, sources}。"""
    answer_parts: list[str] = []
    trace: list[dict] = []
    sources: list[dict] = []
    iterations = 0
    answer = ""

    async for event in run_agent_stream(query, history or [], settings, temperature):
        t = event["type"]
        if t == "answer":
            answer_parts.append(event["delta"])
        elif t == "sources":
            sources = event["sources"]
        elif t == "done":
            answer = event["answer"]
            iterations = event["iterations"]
            sources = event.get("sources", sources)
            trace = event.get("trace", [])
        elif t == "error":
            answer = event["message"]

    return {
        "answer": answer or "".join(answer_parts),
        "tool_calls": trace,
        "iterations": iterations or 1,
        "sources": sources,
    }
