"""
配置中心 —— 所有可调参数集中在这里，不用在代码里翻找。

设计原则：
    - 环境变量优先（安全，不把 key 写死在代码里）
    - dataclass 给默认值（本地开发方便）
"""

import os
from dataclasses import dataclass, field

# python-dotenv 是可选的：装了就从 .env 读配置，没装就用系统环境变量
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

    # ========== Embedding ==========
    # 如果 EMBEDDING_API_KEY 没单独设，就复用 LLM 的 key
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "Qwen/Qwen3-VL-Embedding-8B")
    embedding_api_key: str = os.getenv("EMBEDDING_API_KEY", "")
    embedding_base_url: str = os.getenv("EMBEDDING_BASE_URL", "https://api.siliconflow.cn/v1")

    def embedding_key(self) -> str:
        """获取实际使用的 embedding key：优先专用 key，否则用 LLM key"""
        return self.embedding_api_key or self.llm_api_key

    # ========== 文本切片 ==========
    chunk_size: int = 512       # 每个 chunk 大约多少字符
    chunk_overlap: int = 50     # 相邻 chunk 重叠多少字符（防止关键信息被切断）

    # ========== 检索 ==========
    top_k: int = 3              # 每次检索返回最相关的几个 chunk

    # ========== 存储路径 ==========
    data_dir: str = "./data"              # PDF 放这里
    index_path: str = "./faiss_index"     # FAISS 索引文件存这里
    chunks_path: str = "./chunks.pkl"     # chunk 元数据存这里
