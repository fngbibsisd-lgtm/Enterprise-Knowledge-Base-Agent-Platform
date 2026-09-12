"""
Agent 聊天接口。

- POST /chat/agent/stream : SSE 流式,边生成边返回(工具调用/检索过程/回答增量实时可见)
- POST /chat/agent         : 非流式,返回完整 answer + tool_calls(历史感知,复用同一执行器)
- GET  /chat/agent/sessions           : 当前用户会话列表
- GET  /chat/agent/sessions/{id}/messages : 加载会话历史消息
- DELETE /chat/agent/sessions/{id}    : 删除会话
"""
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from backend.agent.executor import run_agent, run_agent_stream
from examples.multi_agent.multi_agent import run_multi_agent_stream
from backend.core.config import Settings, get_settings
from backend.core.deps import get_current_user
from backend.db.session import AsyncSessionLocal
from backend.repositories import MessageRepository, SessionRepository
from backend.schemas import (
    AgentChatResponse,
    AgentStreamRequest,
    MessageOut,
    SessionOut,
)

router = APIRouter(prefix="/chat", tags=["Agent 聊天"])


def _sse_frame(event: dict) -> str:
    """把事件 dict 序列化成 SSE 数据帧(data: {json}\n\n)。"""
    return f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"


async def _prepare_session(username: str, query: str, session_id: int | None) -> tuple[int, list[dict], bool]:
    """创建/校验会话并追加当前 user 消息,返回 (session_id, 历史, 是否新建)。"""
    async with AsyncSessionLocal() as session:
        srepo = SessionRepository(session)
        mrepo = MessageRepository(session)
        is_new = False
        if session_id:
            s = await srepo.get(session_id)
            if s is None or s.username != username:
                raise HTTPException(status_code=404, detail="会话不存在")
        else:
            s = await srepo.create(username, title=query[:50])
            is_new = True
        await mrepo.append(s.id, "user", query)
        msgs = await mrepo.list_by_session(s.id)
        await session.commit()
    history = [{"role": m.role, "content": m.content} for m in msgs[:-1]]
    return s.id, history, is_new


async def _persist_assistant(session_id: int, answer: str, trace: list[dict], sources: list[dict]) -> None:
    """把最终回答(及工具调用轨迹/引文)落库为 assistant 消息。"""
    if not answer:
        return
    async with AsyncSessionLocal() as session:
        await MessageRepository(session).append(
            session_id,
            "assistant",
            answer,
            tool_calls=json.dumps(trace, ensure_ascii=False, default=str) if trace else None,
            sources=json.dumps(sources, ensure_ascii=False, default=str) if sources else None,
        )
        await session.commit()


@router.post("/agent/stream")
async def agent_chat_stream(
    request: AgentStreamRequest,
    settings: Settings = Depends(get_settings),
    user: dict = Depends(get_current_user),
):
    query = request.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="问题不能为空")

    session_id, history, _ = await _prepare_session(user["username"], query, request.session_id)

    async def gen():
        answer = ""
        trace: list[dict] = []
        sources: list[dict] = []
        try:
            async for event in run_agent_stream(query, history, settings):
                if event["type"] == "done":
                    event["session_id"] = session_id
                    answer = event["answer"]
                    trace = event.get("trace", [])
                    sources = event.get("sources", [])
                elif event["type"] == "error" and not answer:
                    answer = event["message"]
                yield _sse_frame(event)
        except Exception as e:
            yield _sse_frame({"type": "error", "message": f"处理失败:{e}"})
        finally:
            await _persist_assistant(session_id, answer, trace, sources)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/agent/multi/stream")
async def agent_chat_multi_stream(
    request: AgentStreamRequest,
    settings: Settings = Depends(get_settings),
    user: dict = Depends(get_current_user),
):
    query = request.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="问题不能为空")

    session_id, history, _ = await _prepare_session(user["username"], query, request.session_id)

    async def gen():
        answer = ""
        try:
            async for event in run_multi_agent_stream(query, settings, history):
                if event["type"] == "done":
                    event["session_id"] = session_id
                    answer = event["answer"]
                elif event["type"] == "error" and not answer:
                    answer = event["message"]
                yield _sse_frame(event)
        except Exception as e:
            yield _sse_frame({"type": "error", "message": f"处理失败:{e}"})
        finally:
            await _persist_assistant(session_id, answer, [], [])

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/agent", response_model=AgentChatResponse)
async def agent_chat(
    request: AgentStreamRequest,
    settings: Settings = Depends(get_settings),
    user: dict = Depends(get_current_user),
):
    query = request.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="问题不能为空")

    session_id, history, _ = await _prepare_session(user["username"], query, request.session_id)

    try:
        result = await run_agent(query, settings, history)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"agent处理失败:{e}")

    await _persist_assistant(session_id, result["answer"], result["tool_calls"], result["sources"])
    return AgentChatResponse(
        answer=result["answer"],
        tool_calls=result["tool_calls"],
        iterations=result["iterations"],
        sources=result["sources"],
    )


@router.get("/agent/sessions", response_model=list[SessionOut])
async def list_sessions(user: dict = Depends(get_current_user)):
    async with AsyncSessionLocal() as session:
        sessions = await SessionRepository(session).list_by_user(user["username"])
    return sessions


@router.get("/agent/sessions/{session_id}/messages", response_model=list[MessageOut])
async def get_session_messages(session_id: int, user: dict = Depends(get_current_user)):
    async with AsyncSessionLocal() as session:
        s = await SessionRepository(session).get(session_id)
        if s is None or s.username != user["username"]:
            raise HTTPException(status_code=404, detail="会话不存在")
        msgs = await MessageRepository(session).list_by_session(session_id)

    result = []
    for m in msgs:
        result.append(
            MessageOut(
                id=m.id,
                role=m.role,
                content=m.content,
                tool_calls=json.loads(m.tool_calls) if m.tool_calls else None,
                sources=json.loads(m.sources) if m.sources else None,
                created_at=m.created_at,
            )
        )
    return result


@router.delete("/agent/sessions/{session_id}")
async def delete_session(session_id: int, user: dict = Depends(get_current_user)):
    async with AsyncSessionLocal() as session:
        s = await SessionRepository(session).get(session_id)
        if s is None or s.username != user["username"]:
            raise HTTPException(status_code=404, detail="会话不存在")
        await SessionRepository(session).delete(session_id)
        await session.commit()
    return {"ok": True}
