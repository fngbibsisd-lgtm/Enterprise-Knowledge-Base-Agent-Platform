"""
FastAPI 后端入口

注册 upload / chat / admin / agent_chat 路由；启动时初始化数据库并打印索引状态。

启动方式（必须在项目根目录 agent/ 下，否则 `from backend.xxx` 导入会报错）：
    uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
    然后访问 http://localhost:8000/docs 查看 Swagger 自动文档
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from backend.database.connection import init_db
from backend.config import Config
from backend.api.upload import router as upload_router
from backend.api.chat import router as chat_router
from backend.api.admin import router as admin_router
from backend.api.agent_chat import router as agent_chat_router
from backend.services.rag import get_index_status
@asynccontextmanager
async def lifespan(app: FastAPI):
    config=Config()
    init_db(config)
    status = get_index_status(config)
    print(f"\n{'='*50}")
    print(f"  索引状态: {'已加载' if status['indexed'] else '空索引，请上传PDF'}")
    print(f"  知识库 chunks: {status['total_chunks']} 条")
    print(f"{'='*50}\n")
    yield

app = FastAPI(
        title="RAG_API",
        description="RAG后端接口服务",
        version="0.3.0",
        lifespan=lifespan,
)

app.include_router(upload_router)
app.include_router(chat_router)
app.include_router(admin_router)
app.include_router(agent_chat_router)
@app.get("/status")
async def status():
    """
    查看知识库状态：已索引多少文档
    """
    s = get_index_status(Config())
    return s

@app.get("/")
async def root():
    """
    根路由,返回欢迎信息和文档链接
    """
    return {
        "message":"Welcome to RAG_API",
        "status":"running",
        "docs":"http://localhost:8000/docs",
        "redoc":"http://localhost:8000/redoc",
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
