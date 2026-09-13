# examples —— 实验性扩展能力

本目录不是项目主线。主线只有两件事：**RAG 混合检索** + **自研 Agent 执行循环**
（分别在 `backend/services/rag.py` 和 `backend/agent/executor.py`）。

这三个子包用来证明主线架构的**可扩展性**，都是可选的，不启动不影响后端正常运行。

| 子包 | 作用 | 依赖 | 设计要点 |
|------|------|------|----------|
| `mcp/` | 通过 MCP 协议**动态发现**外部工具，而非硬编码在 `tools.py` | `mcp>=2.0` | 工具来源可插拔；降级不影响主线 |
| `multi_agent/` | Planner → Executor → Reflector 编排层，复杂任务拆解 | 无（复用主线） | 说明何时**不应**引入多智能体 |
| `langgraph_agent/` | 用 LangGraph 状态机复刻同一套 Agent 循环 | `langgraph`、`langchain-openai` | 对照说明框架在底层做了什么 |

## 降级设计（重点）

MCP 是**可选能力**，两条失败路径都不影响主线问答：

```
MCP 不可用
    ├── 没装 mcp 包      → backend/agent/tools.py 捕获 ImportError，只用 4 个内置工具
    └── server 连不上    → mcp_client 记录错误并返回空工具集（不抛异常）
                              ↓
                    build_system_prompt() 按「本次真实可用的工具」生成
                              ↓
                    工具清单里没有 get_current_time / get_system_info
                    强制调用规则 1.5 也不会出现
                              ↓
                    模型不会去调用一个不存在的工具
```

这条链路的关键在于：**工具可用性会反过来影响 Agent policy**，而不是写死在 prompt 里。

## 连接生命周期

MCP 的 stdio 连接内部用 anyio task group，**enter / exit 必须在同一个 asyncio task**，
否则报 `Attempted to exit cancel scope in a different task than it was entered in`。

而 `get_mcp_tools()` 是被各个请求协程调用的，随请求结束而销毁，不能由它持有连接。
因此 `mcp_client.py` 用一个长驻后台任务（`_serve`）独占连接：自己 enter、自己 exit，
应用关闭时由 `close_mcp()` 通知退出（已接进 `backend/main.py` 的 lifespan）。

## 运行

```bash
# 必须在项目根目录 agent/ 下执行

# 1) MCP：无需手动启动 server，client 会以子进程拉起
python -c "import asyncio;from examples.mcp import mcp_client as m;print(asyncio.run(m.get_mcp_tools())[0])"

# 2) LangGraph 对照实现
python -m examples.langgraph_agent.langgraph_demo "3加4再乘2等于几"

# 3) 多智能体：通过后端接口体验
#    POST /chat/agent/multi/stream
```
