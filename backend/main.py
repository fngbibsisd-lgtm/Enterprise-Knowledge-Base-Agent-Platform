"""
FastAPI 后端入口（V2 架构）

- app 工厂 + lifespan：建表 + 预置 admin + 确保 Milvus collection
- CORS：放行前端开发源
- 注册 auth / upload / chat / agent_chat / admin 路由

启动（必须在项目根目录 agent/ 下，否则 `from backend.xxx` 导入会报错）：
    uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend import models  # noqa: F401  确保 ORM 模型注册到 metadata
from backend.api import admin, agent_chat, auth, chat, upload
from backend.core.config import get_settings
from backend.db.base import Base
from backend.db.session import AsyncSessionLocal, engine
from backend.repositories import UserRepository
from backend.services import rag, vector_store


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    # 建表（幂等；正式版本迁移用 alembic upgrade head）
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # 预置默认 admin 账号
    async with AsyncSessionLocal() as session:
        await UserRepository(session).ensure_admin(settings.admin_username, settings.admin_password)
        await session.commit()
    # 确保 Milvus collection 就绪
    await vector_store.ensure_collection(settings)
    yield
    # 释放 MCP 长驻连接（子进程 + anyio task group 必须成对退出，见 examples/mcp/mcp_client.py）
    from examples.mcp.mcp_client import close_mcp

    await close_mcp()


app = FastAPI(
    title="RAG_API",
    description="企业智能知识库 Agent 平台后端",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(upload.router)
app.include_router(chat.router)
app.include_router(agent_chat.router)
app.include_router(admin.router)


@app.get("/status")
async def status():
    return await rag.get_index_status(get_settings())


@app.get("/")
async def root():
    return {
        "message": "Welcome to RAG_API",
        "status": "running",
        "docs": "http://localhost:8000/docs",
        "redoc": "http://localhost:8000/redoc",
    }
