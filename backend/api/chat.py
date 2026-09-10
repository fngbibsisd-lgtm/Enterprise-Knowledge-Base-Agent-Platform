"""
聊天接口 —— POST /chat：RAG 检索 → LLM 生成 → 保存记录 → 返回 answer + sources。
"""
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import Settings, get_settings
from backend.core.deps import get_current_user
from backend.db.session import get_db
from backend.repositories import ChatRepository
from backend.schemas import ChatRequest, ChatResponse
from backend.services import llm, rag

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    _user: dict = Depends(get_current_user),
):
    query = request.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="问题不可为空")

    sources = await rag.search(query, settings)
    try:
        answer = await llm.generate_answer(query, sources, settings)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM生成回答失败:{e}")

    # 保存聊天记录，失败不影响接口返回
    try:
        await ChatRepository(session).save(query, answer, json.dumps(sources, ensure_ascii=False))
    except Exception:
        pass

    return ChatResponse(answer=answer, sources=sources)
