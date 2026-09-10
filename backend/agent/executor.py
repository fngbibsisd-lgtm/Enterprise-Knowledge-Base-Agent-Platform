"""
Agent 执行循环（异步）

反复调用 LLM，直到它决定直接回答（不再调用工具）或达到最大迭代次数。
流程：
    1. 用户问题 → 构建初始 messages（system + user）
    2. 循环：发 messages + tools 给 LLM → 有 tool_calls 就执行工具并追加结果 → 否则返回回答
    3. 达到 max_iterations 还没结束 → 返回超时提示
"""
import json

from openai import AsyncOpenAI

from backend.agent.tools import TOOLS, get_tool_map
from backend.core.config import Settings


def create_agent_client(settings: Settings) -> AsyncOpenAI:
    """创建 Agent 用的异步 OpenAI 客户端。"""
    return AsyncOpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)


def build_system_prompt() -> str:
    """告诉 LLM 角色、可用工具、调用时机，并禁止编造答案。"""
    return """
你是一个企业内部知识库管理助手,可以搜索文档和查询数据库来回答用户问题,
可使用工具:
knowledge_search:当用户查询文档内容时使用
sql_query:当用户查询统计数据时使用
规则:
1.回答必须基于工具返回的实际结果,不能凭空编造
2.如果一次检索结果不够,可以调整关键词多次检索
3.如果多次检索都找不到答案,如实告知用户"未找到相关信息"
4.不要向用户展示SQL语句或工具调用的具体细节
""".strip()


async def execute_tool_calls(tool_calls: list, tool_map: dict) -> list[dict]:
    """执行 LLM 返回的所有 tool_calls，返回 tool 消息列表。"""
    tool_messages = []
    for tool_call in tool_calls:
        tool_name = tool_call.function.name
        tool_call_id = tool_call.id

        # 1. 解析参数 JSON 字符串 → dict
        try:
            arguments = json.loads(tool_call.function.arguments or "{}")
        except json.JSONDecodeError as e:
            tool_messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": f"参数解析失败: {e}",
            })
            continue

        # 2. 根据工具名找到对应函数
        tool_fn = tool_map.get(tool_name)
        if tool_fn is None:
            tool_messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": f"未知工具: {tool_name}",
            })
            continue

        # 3. 调用工具
        try:
            result = await tool_fn(**arguments)
        except Exception as e:
            tool_messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": f"工具执行失败: {e}",
            })
            continue

        # 4. dict 转 JSON 字符串，其他类型直接 str()
        content = json.dumps(result, ensure_ascii=False, default=str) if isinstance(result, dict) else str(result)
        tool_messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content,
        })

    return tool_messages


async def run_agent(query: str, settings: Settings, max_iterations: int = 5) -> dict:
    """Agent 主循环 —— 反复调用 LLM 直到拿到最终答案。"""
    client = create_agent_client(settings)
    tool_map = get_tool_map()
    history: list[dict] = []
    messages = [
        {"role": "system", "content": build_system_prompt()},
        {"role": "user", "content": query},
    ]

    for i in range(max_iterations):
        try:
            response = await client.chat.completions.create(
                model=settings.llm_model,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
            )
        except Exception as e:
            return {"answer": f"LLM调用失败:{e}", "tool_calls": history, "iterations": i + 1}

        msg = response.choices[0].message
        if not msg.tool_calls:
            return {"answer": msg.content, "tool_calls": history, "iterations": i + 1}

        messages.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ],
        })

        tool_messages = await execute_tool_calls(msg.tool_calls, tool_map)
        messages.extend(tool_messages)
        for tc, tm in zip(msg.tool_calls, tool_messages):
            history.append({
                "tool_name": tc.function.name,
                "arguments": json.loads(tc.function.arguments or "{}"),
                "result": tm["content"],
            })

    return {"answer": "抱歉,处理超时,请简化问题后重试", "tool_calls": history, "iterations": max_iterations}
