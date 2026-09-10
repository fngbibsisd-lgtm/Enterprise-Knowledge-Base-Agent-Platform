"""上传文件表数据访问。"""
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import UploadedFile


class FileRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def exists_by_md5(self, md5_hash: str) -> bool:
        stmt = select(UploadedFile.id).where(UploadedFile.md5_hash == md5_hash)
        return (await self.session.execute(stmt)).first() is not None

    async def create(self, filename: str, md5_hash: str, chunk_count: int) -> UploadedFile:
        f = UploadedFile(filename=filename, md5_hash=md5_hash, chunk_count=chunk_count)
        self.session.add(f)
        await self.session.flush()
        return f

    async def list_recent_filenames(self, since: datetime) -> set[str]:
        """返回 created_at > since 的文件名集合。"""
        stmt = select(UploadedFile.filename).where(UploadedFile.created_at > since)
        return set((await self.session.execute(stmt)).scalars().all())

    async def delete_recent(self, since: datetime) -> int:
        result = await self.session.execute(
            delete(UploadedFile).where(UploadedFile.created_at > since)
        )
        return result.rowcount

    async def delete_all(self) -> int:
        result = await self.session.execute(delete(UploadedFile))
        return result.rowcount

    async def count(self) -> int:
        stmt = select(func.count()).select_from(UploadedFile)
        return (await self.session.execute(stmt)).scalar_one()
