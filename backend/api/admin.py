"""
知识库管理接口 — POST /admin/reset

清空/重置知识库（支持按时间范围删除）
"""

from fastapi import APIRouter, HTTPException
from backend.config import Config
from backend.models.schemas import ResetRequest
from backend.services.rag import reset_index
from backend.database.connection import get_connection
config = Config()
router = APIRouter(prefix="/admin", tags=["管理"])


TIME_MAP = {"2h":2,"12h":12,"24h":24,"all":None}


@router.post("/reset")
def reset_knowledge_base(request: ResetRequest):
    """
    重置知识库

    - `since="all"`: 删除所有索引和上传记录
    - `since="2h"`:  仅删除最近 2 小时内上传的文件
    - `since="12h"`: 仅删除最近 12 小时内上传的文件
    - `since="24h"`: 仅删除最近 24 小时内上传的文件
    """

    if request.since not in TIME_MAP:
        raise HTTPException(400,detail="不可用时间范围")
    hours=TIME_MAP[request.since]
    deleted_count=reset_index(config,hours)

    if hours is None:
        with get_connection(config) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM uploaded_files")
            deleted_files = cursor.rowcount
            cursor.execute("SELECT COUNT(*) AS cnt FROM uploaded_files")
            remaining = cursor.fetchone()["cnt"]
    else:
        with get_connection(config) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                DELETE FROM uploaded_files WHERE created_at > DATE_SUB(NOW(), INTERVAL %s HOUR)
                """,
                (hours,),
            )
            deleted_files = cursor.rowcount
            cursor.execute("SELECT COUNT(*) AS cnt FROM uploaded_files")
            remaining = cursor.fetchone()["cnt"]

    return {
        "deleted_files":deleted_files,
        "remaining_files":remaining,
        "deleted_chunks":deleted_count,
    }
