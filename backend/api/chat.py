"""
聊天接口 — POST /chat：RAG 检索 → LLM 生成 → 保存记录 → 返回 answer + sources。
"""
from fastapi import APIRouter, HTTPException
from backend.config import Config
from backend.models.schemas import ChatResponse,ChatRequest
from backend.services import rag,llm
from backend.database import crud

config = Config()
router = APIRouter()

@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    聊天窗口

    流程:
        1.获取用户query
        2.RAG检索相关chunk
        3.调用LLM生成回答
        4.保存聊天记录,失败不影响接口返回
        5.返回answer+sources
    """
    query=request.query.strip()
    if not query:
        raise HTTPException(status_code=400,detail=f"问题不可为空")
    #搜索资料
    sources=rag.search(query,config)
    #生成回答
    try:
        answer=llm.generate_answer(query,sources,config)
    except Exception as e:
        raise HTTPException(status_code=500,detail=f"LLM生成回答失败:{e}")
    #保存聊天记录
    try:
        crud.save_chat(
            config=config,
            query=query,
            answer=answer,
            sources=sources
        )
    except Exception:
        pass
    return ChatResponse(answer=answer,sources=sources)