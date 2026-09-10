"""
Milvus 向量存储 —— 封装 pymilvus MilvusClient。

- 开发用 Milvus Lite（本地文件 milvus.db），生产用 standalone（http://localhost:19530）
- collection 字段：id(int64 主键自增) / text(varchar) / source(varchar) / embedding(float vector)
- 同步 pymilvus 调用统一丢线程池（asyncio.to_thread），避免阻塞事件循环
"""
import asyncio
from functools import lru_cache

from pymilvus import DataType, MilvusClient

from backend.core.config import Settings
from backend.services.embedding import embed_texts

_TEXT_MAX_LEN = 2048
_SOURCE_MAX_LEN = 512


@lru_cache
def _client(uri: str) -> MilvusClient:
    return MilvusClient(uri)


def _ensure_collection_sync(client: MilvusClient, settings: Settings) -> None:
    name = settings.milvus_collection
    if not client.has_collection(name):
        schema = client.create_schema(auto_id=True)
        schema.add_field("id", DataType.INT64, is_primary=True)
        schema.add_field("text", DataType.VARCHAR, max_length=_TEXT_MAX_LEN)
        schema.add_field("source", DataType.VARCHAR, max_length=_SOURCE_MAX_LEN)
        schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=settings.embedding_dim)
        index_params = client.prepare_index_params()
        index_params.add_index(field_name="embedding", index_type="FLAT", metric_type="COSINE")
        client.create_collection(name, schema=schema, index_params=index_params)
    # Milvus 需显式 load 后才能 search/query（幂等，重复调用安全）
    client.load_collection(name)


async def ensure_collection(settings: Settings) -> None:
    client = _client(settings.milvus_db_uri)
    await asyncio.to_thread(_ensure_collection_sync, client, settings)


async def add_chunks(chunks: list[dict], settings: Settings) -> int:
    """chunks: [{text(含【来源】前缀), source}]，先向量化再入库，返回新增数。"""
    if not chunks:
        return 0
    client = _client(settings.milvus_db_uri)
    await asyncio.to_thread(_ensure_collection_sync, client, settings)
    texts = [c["text"] for c in chunks]
    vectors = await embed_texts(texts, settings)
    data = [
        {"text": c["text"], "source": c["source"], "embedding": v}
        for c, v in zip(chunks, vectors)
    ]

    def _insert() -> int:
        return client.insert(settings.milvus_collection, data)["insert_count"]

    return await asyncio.to_thread(_insert)


async def search_by_vector(query_vec: list[float], top_k: int, settings: Settings) -> list[tuple[int, float]]:
    """向量检索，返回 [(id, score)]，按 score 降序（COSINE 越高越相似）。"""
    client = _client(settings.milvus_db_uri)

    def _search() -> list[tuple[int, float]]:
        res = client.search(
            settings.milvus_collection,
            data=[query_vec],
            limit=top_k,
        )
        return [(h["id"], float(h["distance"])) for h in res[0]]

    return await asyncio.to_thread(_search)


async def get_all_chunks(settings: Settings) -> list[dict]:
    """返回所有 [{id, text, source}]（分页取全量，供 BM25 与去重使用）。"""
    client = _client(settings.milvus_db_uri)

    def _fetch() -> list[dict]:
        result: list[dict] = []
        offset = 0
        page = 1000
        while True:
            rows = client.query(
                settings.milvus_collection,
                filter="id >= 0",
                output_fields=["id", "text", "source"],
                offset=offset,
                limit=page,
            )
            result.extend(rows)
            if len(rows) < page:
                break
            offset += page
        return result

    return await asyncio.to_thread(_fetch)


def _in_expr(field: str, values: set[str]) -> str:
    quoted = ", ".join('"' + v.replace('"', '\\"') + '"' for v in values)
    return f"{field} in [{quoted}]"


async def delete_by_sources(sources: set[str], settings: Settings) -> int:
    """删除 source 属于指定集合的行，返回删除数。"""
    if not sources:
        return 0
    client = _client(settings.milvus_db_uri)
    if not client.has_collection(settings.milvus_collection):
        return 0

    def _delete() -> int:
        res = client.delete(
            settings.milvus_collection, filter=_in_expr("source", sources)
        )
        # pymilvus 3.0 返回 list（如 [count]），2.x 返回 dict（{"delete_count": n}）
        if isinstance(res, dict):
            return res.get("delete_count", 0)
        if isinstance(res, (list, tuple)) and res:
            return int(res[0])
        return 0

    return await asyncio.to_thread(_delete)


async def clear(settings: Settings) -> int:
    """清空 collection，返回清空前行数。"""
    client = _client(settings.milvus_db_uri)
    n = await count(settings)
    await asyncio.to_thread(client.drop_collection, settings.milvus_collection)
    return n


async def count(settings: Settings) -> int:
    client = _client(settings.milvus_db_uri)

    def _count() -> int:
        if not client.has_collection(settings.milvus_collection):
            return 0
        return client.get_collection_stats(settings.milvus_collection)["row_count"]

    return await asyncio.to_thread(_count)
