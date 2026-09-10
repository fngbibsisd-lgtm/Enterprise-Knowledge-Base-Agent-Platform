"""
Agent 聊天接口 —— POST /chat/agent：调用 run_agent，由 LLM 自主决定是否检索、查库。
"""
from fastapi import APIRouter, Depends, HTTPException

from backend.agent.executor import run_agent
from backend.core.config import Settings, get_settings
from backend.core.deps import get_current_user
from backend.schemas import AgentChatRequest, AgentChatResponse

router = APIRouter(prefix="/chat", tags=["Agent 聊天"])


@router.post("/agent", response_model=AgentChatResponse)
async def agent_chat(
    request: AgentChatRequest,
    settings: Settings = Depends(get_settings),
    _user: dict = Depends(get_current_user),
):
    query = request.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="问题不能为空")

    try:
        result = await run_agent(query, settings)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"agent处理失败:{e}")

    return AgentChatResponse(
        answer=result["answer"],
        tool_calls=result["tool_calls"],
        iterations=result["iterations"],
    )
