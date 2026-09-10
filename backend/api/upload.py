"""
文件上传接口 —— POST /upload：校验类型 → 保存 → 建索引 → 入库。
"""
import hashlib
import os

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import Settings, get_settings
from backend.core.deps import require_admin
from backend.db.session import get_db
from backend.repositories import FileRepository
from backend.schemas import UploadResponse
from backend.services import rag

router = APIRouter()
ALLOWED_EXTENSIONS = {".pdf", ".txt"}


@router.post("/upload", response_model=UploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    _admin: dict = Depends(require_admin),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不可为空")
    filename = os.path.basename(file.filename)  # 防路径穿越
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="文件类型不支持,只允许pdf,txt")

    os.makedirs(settings.upload_dir, exist_ok=True)
    os.makedirs(settings.data_dir, exist_ok=True)

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="上传文件内容为空")

    file_md5 = hashlib.md5(content).hexdigest()
    repo = FileRepository(session)
    if await repo.exists_by_md5(file_md5):
        raise HTTPException(status_code=409, detail="存在相同文档")

    # 保存到 upload_dir 和 data_dir
    for path in (
        os.path.join(settings.upload_dir, filename),
        os.path.join(settings.data_dir, filename),
    ):
        with open(path, "wb") as f:
            f.write(content)

    try:
        added_chunks = await rag.build_index_for_file(os.path.join(settings.data_dir, filename), settings)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"文件上传成功,但索引构建失败:{e}")

    await repo.create(filename, file_md5, added_chunks)
    return UploadResponse(filename=filename, message=f"文件上传成功,并新增{added_chunks}个文本块索引")
