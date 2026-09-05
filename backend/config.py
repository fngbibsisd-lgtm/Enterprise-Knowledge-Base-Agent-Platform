"""
配置中心：LLM / Embedding / 切片 / 检索 / 存储路径等所有配置项。
"""

import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv
    from pathlib import Path
    env_path = Path(__file__).parent / ".env"
    load_dotenv(env_path)
except ImportError:
    pass


@dataclass
class Config:
    # ========== LLM ==========
    llm_model: str = os.getenv("LLM_MODEL", "deepseek-chat")
    llm_api_key: str = os.getenv("LLM_API_KEY", "sk-xxx")
    llm_base_url: str = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
    max_tokens: int = 1024  # 新增：LLM 最大生成 token 数
    # ========== Embedding ==========
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "Qwen/Qwen3-VL-Embedding-8B")
    embedding_api_key: str = os.getenv("EMBEDDING_API_KEY", "")
    embedding_base_url: str = os.getenv("EMBEDDING_BASE_URL", "https://api.siliconflow.cn/v1")

    def embedding_key(self) -> str:
        return self.embedding_api_key or self.llm_api_key

    # ========== 文本切片 ==========
    chunk_size: int = 512
    chunk_overlap: int = 50

    # ========== 检索 ==========
    top_k: int = 8

    # ========== 存储路径 ==========
    data_dir: str = "./data"
    upload_dir: str = "./data/uploads"   # 上传文件存放
    index_path: str = "./faiss_data/faiss_index"
    chunks_path: str = "./faiss_data/faiss_chunks"

    # ========== MySQL 数据库（V0.4 替换 SQLite）==========
    mysql_host: str = os.getenv("MYSQL_HOST", "127.0.0.1")
    mysql_port: int = int(os.getenv("MYSQL_PORT", "3306"))
    mysql_user: str = os.getenv("MYSQL_USER", "root")
    mysql_password: str = os.getenv("MYSQL_PASSWORD", "")
    mysql_database: str = os.getenv("MYSQL_DATABASE", "rag_agent")
    db_path: str = "./chat.db"           # 遗留：SQLite 路径，切换 MySQL 后可删除