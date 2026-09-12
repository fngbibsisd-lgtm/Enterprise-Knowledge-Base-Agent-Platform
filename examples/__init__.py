"""实验性扩展能力（非项目主线）。

主线只有两件事：RAG 混合检索 + 手写 Function Calling Agent 循环。
本包里的三个能力都是「可选增强」，目的是证明主线架构的可扩展性：

    mcp/             通过 MCP 协议动态接入外部工具（工具来源可插拔）
    multi_agent/     Planner → Executor → Reflector 编排层（复杂任务拆解）
    langgraph_agent/ 用 LangGraph 复刻同一套 Agent 循环（框架对照）

三个子包都可以独立运行，不启动它们不影响后端主流程。
"""
