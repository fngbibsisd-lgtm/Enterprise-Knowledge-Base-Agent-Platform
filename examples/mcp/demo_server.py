"""
MCP 演示 server —— 通过 stdio 暴露几个「知识库之外」的外部工具，演示 agent 用 MCP 动态接入外部能力。

使用 mcp 2.x 的 MCPServer（原 FastMCP，2.x 已改名）。

由 mcp_client 以子进程拉起：
    python -m examples.mcp.demo_server
"""
import datetime
import os
import platform

from mcp.server import MCPServer

server = MCPServer(name="demo-tools", version="1.0.0")


@server.tool(description="获取当前系统时间。当用户询问'现在几点/当前时间/今天日期'等问题时,必须调用本工具获取,不要自己猜测。")
def get_current_time() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@server.tool(description="获取当前运行环境信息(操作系统平台、工作目录)。当用户询问'运行在什么系统/环境/平台/哪台机器/服务器配置'等问题时,必须调用本工具获取,不要凭记忆猜测。")
def get_system_info() -> str:
    return f"platform={platform.platform()}, cwd={os.getcwd()}"


if __name__ == "__main__":
    server.run(transport="stdio")
