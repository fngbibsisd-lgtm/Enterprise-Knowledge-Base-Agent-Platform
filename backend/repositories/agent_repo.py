"""Agent 会话 / 消息数据访问（Repository 模式）。"""
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import AgentMessage, AgentSession


class SessionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, username: str, title: str) -> AgentSession:
        s = AgentSession(username=username, title=title)
        self.session.add(s)
        await self.session.flush()
        return s

    async def list_by_user(self, username: str) -> list[AgentSession]:
        stmt = (
            select(AgentSession)
            .where(AgentSession.username == username)
            .order_by(AgentSession.updated_at.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get(self, session_id: int) -> AgentSession | None:
        return await self.session.get(AgentSession, session_id)

    async def delete(self, session_id: int) -> None:
        # 先删消息再删会话,不依赖外键级联,兼容不同数据库
        await self.session.execute(delete(AgentMessage).where(AgentMessage.session_id == session_id))
        await self.session.execute(delete(AgentSession).where(AgentSession.id == session_id))


class MessageRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def append(
        self,
        session_id: int,
        role: str,
        content: str,
        tool_calls: str | None = None,
        sources: str | None = None,
    ) -> AgentMessage:
        m = AgentMessage(
            session_id=session_id,
            role=role,
            content=content,
            tool_calls=tool_calls,
            sources=sources,
        )
        self.session.add(m)
        await self.session.flush()
        return m

    async def list_by_session(self, session_id: int) -> list[AgentMessage]:
        stmt = (
            select(AgentMessage)
            .where(AgentMessage.session_id == session_id)
            .order_by(AgentMessage.id.asc())
        )
        return list((await self.session.execute(stmt)).scalars().all())
