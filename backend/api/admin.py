"""
知识库管理接口 —— POST /admin/reset：清空/重置知识库（支持按时间范围删除）。
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import Settings, get_settings
from backend.core.deps import require_admin
from backend.db.session import get_db
from backend.repositories import FileRepository
from backend.schemas import ResetRequest
from backend.services import rag

router = APIRouter(prefix="/admin", tags=["管理"])

TIME_MAP = {"2h": 2, "12h": 12, "24h": 24, "all": None}


@router.post("/reset")
async def reset_knowledge_base(
    request: ResetRequest,
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    _admin: dict = Depends(require_admin),
):
    if request.since not in TIME_MAP:
        raise HTTPException(status_code=400, detail="不可用时间范围")

    hours = TIME_MAP[request.since]
    file_repo = FileRepository(session)

    if hours is None:
        deleted_chunks = await rag.clear(settings)
        deleted_files = await file_repo.delete_all()
        remaining = await file_repo.count()
    else:
        since = datetime.now() - timedelta(hours=hours)
        recent = await file_repo.list_recent_filenames(since)
        deleted_chunks = await rag.delete_by_sources(recent, settings)
        deleted_files = await file_repo.delete_recent(since)
        remaining = await file_repo.count()

    return {
        "deleted_files": deleted_files,
        "remaining_files": remaining,
        "deleted_chunks": deleted_chunks,
    }
