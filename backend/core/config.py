"""
配置中心（Pydantic Settings）—— 取代原 dataclass Config。

- 自动从 backend/.env 加载，字段带类型校验
- 通过 core.deps.get_settings 依赖注入使用，不再用模块级全局单例
"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ 目录（.env 所在位置）
BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    # ===== LLM =====
    llm_model: str = "deepseek-chat"
    llm_api_key: str = "sk-xxx"
    llm_base_url: str = "https://api.deepseek.com/v1"
    max_tokens: int = 1024

    # ===== Embedding =====
    embedding_model: str = "Qwen/Qwen3-VL-Embedding-8B"
    embedding_api_key: str = ""
    embedding_base_url: str = "https://api.siliconflow.cn/v1"

    @property
    def embedding_key(self) -> str:
        return self.embedding_api_key or self.llm_api_key

    # ===== 文本切片 =====
    chunk_size: int = 512
    chunk_overlap: int = 50

    # ===== 检索 =====
    top_k: int = 8

    # ===== 存储路径 =====
    data_dir: str = "./data"
    upload_dir: str = "./data/uploads"

    # ===== Milvus 向量库 =====
    milvus_db_uri: str = "./milvus.db"       # Milvus Lite 本地文件；standalone 用 http://localhost:19530
    milvus_collection: str = "knowledge_chunks"
    embedding_dim: int = 4096

    # ===== MySQL（异步驱动 asyncmy）=====
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = ""
    mysql_database: str = "rag_agent"

    @property
    def database_url(self) -> str:
        return (
            f"mysql+asyncmy://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
            f"?charset=utf8mb4"
        )

    # ===== 权限 / JWT =====
    admin_username: str = "admin"
    admin_password: str = "admin123"
    jwt_secret: str = "dev-secret-change-me-0123456789abcdef"  # 生产务必用 JWT_SECRET 覆盖
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """返回全局唯一的 Settings 实例（依赖注入入口）。"""
    return Settings()
