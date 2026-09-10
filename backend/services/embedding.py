"""Embedding 调用（异步，AsyncOpenAI）。"""
from openai import AsyncOpenAI

from backend.core.config import Settings

_BATCH_SIZE = 20


def _client(settings: Settings) -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=settings.embedding_key,
        base_url=settings.embedding_base_url,
    )


async def embed_texts(texts: list[str], settings: Settings) -> list[list[float]]:
    """批量把文本转成向量（分批调 API）。"""
    if not texts:
        return []
    client = _client(settings)
    vectors: list[list[float]] = []
    for i in range(0, len(texts), _BATCH_SIZE):
        batch = texts[i : i + _BATCH_SIZE]
        resp = await client.embeddings.create(model=settings.embedding_model, input=batch)
        vectors.extend([d.embedding for d in resp.data])
    return vectors


async def embed_query(query: str, settings: Settings) -> list[float]:
    """把单条 query 转成向量。"""
    vecs = await embed_texts([query], settings)
    return vecs[0]
