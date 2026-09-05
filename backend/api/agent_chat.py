"""
Agent 聊天接口 — POST /chat/agent：调用 run_agent，由 LLM 自主决定是否检索、查库。
"""

from fastapi import APIRouter, HTTPException
from backend.config import Config
from backend.models.schemas import AgentChatRequest, AgentChatResponse
from backend.agent.executor import run_agent

config = Config()
router = APIRouter(prefix="/chat", tags=["Agent 聊天"])


@router.post("/agent", response_model=AgentChatResponse)
async def agent_chat(request: AgentChatRequest):
    """
    Agent 智能聊天

    和 /chat 不同，Agent 会自主决策：
    - 需要查文档时，自动调用 knowledge_search
    - 需要查数据时，自动调用 sql_query
    - 可能多次调用不同工具来回答一个复杂问题
    """
    query=request.query.strip()
    if not query:
        raise HTTPException(status_code=400,detail="问题不能为空")

    try:
        result = run_agent(query,config)
    except Exception as e:
        raise HTTPException(status_code=500,detail=f"agent处理失败:{e}")

    return AgentChatResponse(
        answer=result["answer"],
        tool_calls=result["tool_calls"],
        iterations=result["iterations"]
    )

