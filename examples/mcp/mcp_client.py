"""
MCP client —— 让 agent 通过 MCP 协议动态接入外部工具，而不是硬编码在 tools.py。

用 mcp 2.x 的 stdio_client + ClientSession。演示：连接一个本地 demo server（stdio）。

要点：
    - get_mcp_tools() 惰性连接并缓存，进程内复用
    - 把 MCP 工具转成 OpenAI function-calling 的 schema 格式
    - 每个 MCP 工具包装成一个 async 函数，供 executor 统一调用

连接生命周期（重要）：
    MCP 的 stdio 连接内部用了 anyio 的 task group，**进入和退出必须在同一个 asyncio task**，
    否则会报 "Attempted to exit cancel scope in a different task than it was entered in"。
    而 get_mcp_tools() 是被各个请求处理协程调用的，随请求结束而销毁，不能由它持有连接。
    因此这里用一个长驻后台任务（_serve）独占连接：它自己 enter、自己 exit，
    应用关闭时由 close_mcp() 通知它退出。

降级策略：
    MCP server 连不上时不做任何补救，只把错误记进 _state["error"] 并返回空工具集——
    executor 会据此生成「不包含 MCP 工具」的 system prompt，模型不会去调用不存在的工具。
"""
import asyncio
import sys
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters, stdio_client

# 建立连接的超时（秒）。MCP server 卡死时不能让首个请求一直等下去。
_CONNECT_TIMEOUT = 15.0

_state: dict = {
    "tools": None,       # list[dict] | None   None=尚未尝试连接
    "callables": None,   # dict[str, callable]
    "error": None,       # str | None
    "ready": None,       # asyncio.Event
    "stop": None,        # asyncio.Event
    "task": None,        # asyncio.Task 长驻连接任务
}


def _server_params() -> list[StdioServerParameters]:
    """要连接的 MCP server 列表。演示：一个本地 demo server（stdio）。

    后续可改成从配置文件读，接入真实服务（GitHub/数据库/内部系统等）。
    """
    return [
        StdioServerParameters(
            command=sys.executable,
            args=["-m", "examples.mcp.demo_server"],
        )
    ]


def _make_caller(session: ClientSession, name: str):
    """把一个 MCP 工具包装成 async 函数，返回文本结果。"""

    async def caller(**kwargs) -> str:
        result = await session.call_tool(name, kwargs or {})
        parts = []
        for block in result.content or []:
            text = getattr(block, "text", None)
            if text is not None:
                parts.append(text)
        if parts:
            return "\n".join(parts)
        structured = getattr(result, "structured_content", None)
        return str(structured) if structured is not None else ""

    return caller


async def _connect(stack: AsyncExitStack) -> tuple[list[dict], dict]:
    """连接所有 MCP server，发现工具，返回 (OpenAI schema 列表, 名称→函数映射)。

    连接资源全部托管给 stack，由调用方（长驻任务）在同一个 task 内统一释放。
    """
    schemas: list[dict] = []
    callables: dict = {}
    for params in _server_params():
        read, write = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        tools = await session.list_tools()

        for t in tools.tools:
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description or "",
                        "parameters": t.input_schema or {"type": "object", "properties": {}},
                    },
                }
            )
            callables[t.name] = _make_caller(session, t.name)
    return schemas, callables


async def _serve() -> None:
    """长驻任务：独占 MCP 连接，直到应用关闭时被 close_mcp() 唤醒。

    enter 和 exit 都在本 task 内完成，因此不会触发 anyio 的跨 task cancel scope 报错。
    """
    assert _state["ready"] is not None and _state["stop"] is not None
    try:
        async with AsyncExitStack() as stack:
            tools, callables = await _connect(stack)
            _state["tools"], _state["callables"], _state["error"] = tools, callables, None
            _state["ready"].set()          # 先让等待方拿到结果
            await _state["stop"].wait()    # 挂起，保持连接存活
    except Exception as e:
        _state["tools"], _state["callables"] = [], {}
        _state["error"] = str(e)
        print(f"[MCP] 连接失败，本次忽略 MCP 工具：{e}")
    finally:
        _state["ready"].set()              # 失败路径也要放行等待方


async def _ensure_started() -> None:
    """惰性启动长驻连接任务（首次调用时）。"""
    if _state["ready"] is None:
        _state["ready"] = asyncio.Event()
        _state["stop"] = asyncio.Event()
    if _state["task"] is None or _state["task"].done():
        _state["task"] = asyncio.create_task(_serve())


async def get_mcp_tools() -> tuple[list[dict], dict]:
    """返回 (OpenAI 工具 schema 列表, 工具名→async 函数)。

    - MCP 不可用时返回 ([], {})，不影响内置工具；原因见 get_mcp_status()
    - 首次调用会建立连接，之后进程内复用
    """
    if _state["tools"] is None:
        await _ensure_started()
        try:
            await asyncio.wait_for(_state["ready"].wait(), timeout=_CONNECT_TIMEOUT)
        except asyncio.TimeoutError:
            _state["tools"], _state["callables"] = [], {}
            _state["error"] = f"连接 MCP server 超时（>{_CONNECT_TIMEOUT}s）"
            print(f"[MCP] {_state['error']}，本次忽略 MCP 工具")
    return _state["tools"], _state["callables"]


def get_mcp_status() -> dict:
    """MCP 连接状态，供接口/日志观测（available 为 False 时 reason 说明原因）。"""
    tools = _state["tools"]
    connected = bool(tools)
    return {
        "connected": connected,
        "tool_count": len(tools or []),
        "tools": [t["function"]["name"] for t in (tools or [])],
        "reason": None if connected else (_state["error"] or "尚未连接"),
    }


async def close_mcp() -> None:
    """关闭 MCP 连接（由应用 lifespan 在 shutdown 时调用）。幂等。"""
    if _state["stop"] is not None:
        _state["stop"].set()
    task = _state["task"]
    if task is not None and not task.done():
        try:
            await asyncio.wait_for(task, timeout=5.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            task.cancel()
    _state.update(tools=None, callables=None, ready=None, stop=None, task=None)
