"""用户表数据访问。"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.security import hash_password
from backend.models import User


class UserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_username(self, username: str) -> User | None:
        stmt = select(User).where(User.username == username)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def exists(self, username: str) -> bool:
        stmt = select(User.id).where(User.username == username)
        return (await self.session.execute(stmt)).first() is not None

    async def create(self, username: str, password_hash: str, role: str = "user") -> User:
        user = User(username=username, password_hash=password_hash, role=role)
        self.session.add(user)
        await self.session.flush()
        return user

    async def ensure_admin(self, admin_username: str, admin_password: str) -> None:
        """无 admin 账号则预置一个（用户名/密码读配置）。"""
        if await self.exists(admin_username):
            return
        await self.create(admin_username, hash_password(admin_password), "admin")
