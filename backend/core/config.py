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
    llm_timeout_sec: float = 120.0  # OpenAI SDK 默认 600s,太长,卡住会干等 10 分钟

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
    # 指定 source 精查时放大候选池并跳过去重（见 rag.search 的 scoped）。
    # 关掉即完全回到旧行为——线上异常时的软回滚阀门，比改代码回滚快。
    rag_source_scoped_search: bool = True

    # ===== Agent =====
    agent_max_iterations: int = 6          # 工具调用最大轮数
    agent_max_history: int = 12            # 多轮对话保留的最近消息条数（滑动窗口）
    # 工具结果字符预算：按工具分档，见 core/tool_output.py。均可在 .env 里覆盖，
    # 出问题时不改代码就能调回旧值（如全设 4000 即回到改动前行为）
    agent_search_result_max_chars: int = 6000    # knowledge_search 整条结果预算（含 5-8 个片段）
    agent_document_result_max_chars: int = 10000  # get_document 整条结果预算（单篇文档，支持分页）
    agent_tool_result_max_chars: int = 4000      # 兜底预算：sql_query/list_tables/MCP 动态工具
    agent_sql_max_rows: int = 50           # sql_query 最大返回行数（自动补 LIMIT）
    agent_sql_timeout_sec: float = 5.0     # sql_query 执行超时（秒）
    agent_top_k: int = 8                   # knowledge_search 默认返回条数（上限见 tool_output.MAX_TOP_K）

    # ===== 存储路径 =====
    data_dir: str = "./data"
    upload_dir: str = "./data/uploads"

    # ===== Milvus 向量库 =====
    milvus_db_uri: str = "./milvus.db"       # Milvus Lite 本地文件；standalone 用 http://localhost:19530
    milvus_collection: str = "knowledge_chunks"
    milvus_collection_eval: str = "knowledge_chunks_eval"  # 评测语料独立 collection，避免污染生产索引
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
