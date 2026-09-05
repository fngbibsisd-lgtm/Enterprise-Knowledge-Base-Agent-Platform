"""
Agent 执行循环

这是 Agent 的大脑：反复调用 LLM，直到它决定直接回答（不再调用工具）或达到最大迭代次数。

流程：
    1. 用户问题 → 构建初始 messages（system + user）
    2. 循环开始：
       a. 把 messages + tools 发给 LLM
       b. LLM 返回 tool_calls？
          → 执行工具，把结果追加到 messages（role: "tool"）
          → 回到步骤 a
       c. LLM 返回普通回答？
          → 结束，返回回答
    3. 达到 max_iterations 还没结束 → 返回超时提示

关键数据结构：messages 列表

    初始：
    [
        {"role": "system", "content": "你是..."},
        {"role": "user",   "content": "用户问题"},
    ]

    每轮 tool 调用后追加 3 条：
    [
        ...,  # 之前的消息
        {"role": "assistant", "content": None, "tool_calls": [...]},     # LLM 返回的
        {"role": "tool", "tool_call_id": "xxx", "content": "工具结果"},   # 每条 tool_call 一条
    ]

    然后带着完整 messages 再发给 LLM。
"""

import json
from openai import OpenAI

from backend.config import Config
from backend.agent.tools import TOOLS, get_tool_map


def create_agent_client(config: Config) -> OpenAI:
    """
    创建用于 Agent 的 OpenAI 客户端（与 services/llm.py 的 create_llm_client 一致）。
    """

    client = OpenAI(
        api_key=config.llm_api_key,
        base_url=config.llm_base_url,
    )
    return client


def build_system_prompt() -> str:
    """
    构建 Agent 的 system prompt：告诉 LLM 角色、可用工具、调用时机，并禁止编造答案。
    """
    system_prompt = """
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
    return system_prompt


def execute_tool_calls(tool_calls: list, tool_map: dict) -> list[dict]:
    """
    执行 LLM 返回的所有 tool_calls，返回 tool 消息列表。

    Args:
        tool_calls: response.choices[0].message.tool_calls，每个元素含 id / function.name / function.arguments
        tool_map: get_tool_map() 的返回值，工具名 → 函数

    Returns:
        list[dict]，每个是 {"role": "tool", "tool_call_id": "...", "content": "..."}
    """
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

        # 3. 调用工具，拿到返回值
        try:
            result = tool_fn(**arguments)
        except Exception as e:
            # 工具执行失败不中断循环，把错误信息回传给 LLM
            tool_messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": f"工具执行失败: {e}",
            })
            continue

        # 4. dict 转 JSON 字符串（default=str 兜底 datetime 等非 JSON 类型），其他类型直接 str()
        content = json.dumps(result, ensure_ascii=False, default=str) if isinstance(result, dict) else str(result)
        tool_messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content,
        })

    return tool_messages


def run_agent(query: str, config: Config, max_iterations: int = 5) -> dict:
    """
    Agent 主循环 —— 反复调用 LLM 直到拿到最终答案。

    Args:
        query: 用户问题
        config: 配置对象
        max_iterations: 最大迭代次数，防止死循环

    Returns:
        {
            "answer": str,          # LLM 最终回答
            "tool_calls": list,     # 记录所有工具调用历史（用于调试/展示）
            "iterations": int,      # 实际迭代次数
        }

    """
    client=create_agent_client(config)
    tool_map = get_tool_map()
    history = []
    messages=[
        {"role": "system","content": build_system_prompt()},
        {"role": "user","content": query},
    ]
    for i in range(max_iterations):
        #调用LLM
        try:
            response = client.chat.completions.create(
                model=config.llm_model,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
            )
        except Exception as e:
            return {
                "answer":f"LLM调用失败:{e}",
                "tool_calls":history,
                "iterations":i+1,
            }
        msg = response.choices[0].message
        if not msg.tool_calls:
            return {"answer": msg.content, "tool_calls": history, "iterations": i+1}
        messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id":tc.id,
                        "type":"function",
                        "function":{
                            "name":tc.function.name,
                            "arguments":tc.function.arguments,
                        }
                    }
                    for tc in msg.tool_calls
                ]
        })

        tool_message=execute_tool_calls(msg.tool_calls, tool_map)
        messages.extend(tool_message)
        for tc, tm in zip(msg.tool_calls,tool_message):
            history.append({
                "tool_name":tc.function.name,
                "arguments":json.loads(tc.function.arguments or "{ }"),
                "result":tm["content"],
            })
    return {
        "answer":"抱歉,处理超时,请简化问题后重试",
        "tool_calls":history,
        "iterations":max_iterations,
    }

