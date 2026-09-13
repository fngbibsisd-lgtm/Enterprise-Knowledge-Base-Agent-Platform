"""
LangGraph 对照 demo —— 用 LangGraph 的状态机复刻「自研 Agent 执行循环」。

目的：对照说明框架在底层做了什么。对照关系：

    executor.py 的循环                      LangGraph 的图
    ───────────────────────────────────     ──────────────────────────────
    _stream_completion (调 LLM)        =    agent 节点
    _execute_tool_calls (执行工具)      =    tools 节点
    "有 tool_calls 就继续,否则回答"     =    conditional_edges (agent→tools/END)
    for i in range(max_iterations)     =    graph.invoke 内部递归(recursion_limit)
    get_tool_map() (工具名→函数)        =    TOOLS_BY_NAME

运行（需已配置 backend/.env 的真实 LLM key，且已 pip install langgraph langchain-openai）：
    python -m examples.langgraph_agent.langgraph_demo "3加4再乘2等于几"
"""
import sys

from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import Annotated, TypedDict

from backend.core.config import get_settings


# ---- 1. 工具定义（对应 backend/tools/*.py）----
@tool
def add(a: int, b: int) -> int:
    """两个整数相加"""
    return a + b


@tool
def multiply(a: int, b: int) -> int:
    """两个整数相乘"""
    return a * b


TOOLS = [add, multiply]
TOOLS_BY_NAME = {t.name: t for t in TOOLS}


# ---- 2. 状态定义（对应 run_agent_stream 里的 messages 列表，add_messages 是累加 reducer）----
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]


# ---- 3. 条件边：继续调工具 or 结束（对应 executor 里的 `if tool_calls is None`）----
def should_continue(state: AgentState) -> str:
    last = state["messages"][-1]
    return "tools" if last.tool_calls else END


def build_graph(llm: ChatOpenAI):
    # 节点：调 LLM（对应 _stream_completion）
    def agent_node(state: AgentState):
        response = llm.bind_tools(TOOLS).invoke(state["messages"])
        return {"messages": [response]}

    # 节点：执行工具（对应 _execute_tool_calls）
    def tools_node(state: AgentState):
        last = state["messages"][-1]
        tool_messages = []
        for tc in last.tool_calls:
            fn = TOOLS_BY_NAME.get(tc["name"])
            result = fn.invoke(tc["args"]) if fn else "未知工具"
            tool_messages.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))
        return {"messages": tool_messages}

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tools_node)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", should_continue, ["tools", END])
    graph.add_edge("tools", "agent")  # 工具结果回喂给 agent，形成循环
    return graph.compile()


def main() -> int:
    settings = get_settings()
    llm = ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        temperature=0,
    )

    query = sys.argv[1] if len(sys.argv) > 1 else "3加4再乘2等于几"
    app = build_graph(llm)
    result = app.invoke({"messages": [HumanMessage(content=query)]})

    print(f"问题：{query}\n")
    print("执行轨迹：")
    for m in result["messages"]:
        if m.type == "tool":
            print(f"  [tool] -> {m.content}")
        elif m.type == "ai" and m.tool_calls:
            print(f"  [ai 调工具] {[(t['name'], t['args']) for t in m.tool_calls]}")
        elif m.type == "ai":
            print(f"  [ai 回答] {m.content}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
