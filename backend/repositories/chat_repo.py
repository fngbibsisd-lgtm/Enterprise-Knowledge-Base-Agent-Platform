"""聊天记录表数据访问。"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import ChatHistory


class ChatRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def save(self, query: str, answer: str, sources_json: str) -> ChatHistory:
        chat = ChatHistory(query=query, answer=answer, sources=sources_json)
        self.session.add(chat)
        await self.session.flush()
        return chat

    async def list_recent(self, limit: int = 20) -> list[ChatHistory]:
        stmt = select(ChatHistory).order_by(ChatHistory.created_at.desc()).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())
