"""
文件上传接口 — POST /upload：校验文件类型 → 保存 → 建索引 → 返回结果。
"""
import os
import hashlib
from fastapi import APIRouter, UploadFile, File, HTTPException
from backend.config import Config
from backend.models.schemas import UploadResponse
from backend.services import rag
from backend.database.connection import get_connection
router = APIRouter()

ALLOWED_EXTENSIONS = {'.pdf', '.txt'}
config=Config()
@router.post("/upload",response_model=UploadResponse)
async def upload_file(file: UploadFile = File(...)):
    """
    文件上传接口

    1.接收上传文件
    2.校验文件类型,只允许pdf和txt
    3.保存到upload_dir,复制到data_dir
    4,调用build_index_for_file()建立索引
    5.返回uploadresponse
    """
    if not file.filename:
        raise HTTPException(status_code=400,detail="文件名不可为空")
    filename = os.path.basename(file.filename)#防止路径穿越
    #j校验文件类型
    ext=os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="文件类型不支持,只允许pdf,txt"
        )
    #确保目录存在
    os.makedirs(config.upload_dir, exist_ok=True)
    os.makedirs(config.data_dir,exist_ok=True)
    #读取
    content=await file.read()

    if not content:
        raise HTTPException(status_code=400,detail="上传文件内容为空")

    file_md5 = hashlib.md5(content).hexdigest()

    with get_connection(config) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT 1 FROM uploaded_files WHERE md5_hash=%s
            """,
            (file_md5,)
        )
        exists = cursor.fetchone()
        if exists:
            raise HTTPException(status_code=409,detail="存在相同文档")


    #保存到upload_dir
    upload_path=os.path.join(config.upload_dir,filename)
    with open(upload_path,'wb') as f:
        f.write(content)
    #保存到data_dir
    data_path=os.path.join(config.data_dir,filename)
    with open(data_path,'wb') as f:
       f.write(content)
    #建立索引
    try:
        added_chunks=rag.build_index_for_file(data_path,config)
    except Exception as e:
        raise HTTPException(status_code=400,detail=f"文件上传成功,但索引构建失败:{e}")

    with get_connection(config) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO uploaded_files(filename, md5_hash, chunk_count) VALUES (%s,%s,%s)
            """,
            (filename, file_md5, added_chunks)
        )
    #返回结果
    return UploadResponse(
        filename=filename,
        message=f"文件上传成功,并新增{added_chunks}个文本块索引"
    )