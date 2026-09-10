"""
RAG 核心服务（异步）—— 切片 → 向量化 → Milvus + BM25 混合检索。

混合检索流程：
    向量检索(Milvus) + BM25 关键词检索 → RRF 融合 → 文档级去重 → 年份软排序
"""
import os
import re

from backend.core.config import Settings
from backend.services import vector_store
from backend.services.bm25 import BM25Index, rrf_fuse
from backend.services.document import chunk_documents, load_documents
from backend.services.embedding import embed_query


async def build_index_for_file(filepath: str, settings: Settings) -> int:
    """读取文件 → 切片 → 向量化 → 入库 Milvus，返回新增 chunk 数。"""
    docs = load_documents(filepath)
    if not docs:
        return 0
    raw_chunks = chunk_documents(docs, settings.chunk_size, settings.chunk_overlap)
    if not raw_chunks:
        return 0

    chunks = []
    for chunk in raw_chunks:
        # 统一 Document / dict 两种 chunk 格式
        if isinstance(chunk, dict):
            text = chunk.get("text") or chunk.get("content") or ""
            source = chunk.get("source") or os.path.basename(filepath)
        elif hasattr(chunk, "text"):
            text = chunk.text
            source = os.path.basename(filepath)
        else:
            text = str(chunk)
            source = os.path.basename(filepath)
        text = text.strip()
        if text:
            # 把文件名注入 chunk 文本，让 embedding 能编码年份/来源信息
            chunks.append({"text": f"【来源：{source}】{text}", "source": source})
    if not chunks:
        return 0
    return await vector_store.add_chunks(chunks, settings)


async def search(query: str, settings: Settings) -> list[dict]:
    """混合检索，返回 [{source, text, preview, score}]。"""
    await vector_store.ensure_collection(settings)
    all_chunks = await vector_store.get_all_chunks(settings)
    if not all_chunks:
        return []

    chunk_by_id = {c["id"]: c for c in all_chunks}
    ids = [c["id"] for c in all_chunks]
    corpus = [c["text"] for c in all_chunks]

    # 年份过滤需在更大候选集上做：各年份公报正文雷同，正确年份常排不进 top_k
    years = re.findall(r"20\d{2}", query)
    search_k = len(all_chunks) if years else settings.top_k

    # ---- 向量检索 ----
    query_vec = await embed_query(query, settings)
    vector_ranked = await vector_store.search_by_vector(query_vec, search_k, settings)
    vector_scores = {vid: score for vid, score in vector_ranked}

    # ---- BM25 关键词检索 ----
    bm25 = BM25Index(corpus)
    bm25_ranked = [ids[idx] for idx, _ in bm25.search(query, k=search_k)]

    # ---- RRF 融合 ----
    fused_ids = rrf_fuse([vid for vid, _ in vector_ranked], bm25_ranked)

    # ---- 按融合顺序构建结果（按文档去重，避免大文件多 chunk 霸榜） ----
    results = []
    seen_sources = set()
    for cid in fused_ids:
        chunk = chunk_by_id.get(cid)
        if chunk is None:
            continue
        text = (chunk.get("text") or "").strip()
        source = chunk.get("source") or ""
        if not text or source in seen_sources:
            continue
        seen_sources.add(source)
        results.append({
            "source": source,
            "text": text,
            "preview": text[:100],
            "score": vector_scores.get(cid, 0.0),
        })

    results = results[: settings.top_k]
    # 年份软排序：query 含年份时，把文件名含该年份的文档排前面（不硬过滤，
    # 避免把「目标年份」误当文档年份而误伤「十五五」类规划文档）
    if years:
        results.sort(key=lambda r: 0 if any(y in r.get("source", "") for y in years) else 1)

    print(f"\n[检索] query=\"{query[:50]}...\" 共 {len(results)} 条:")
    for i, r in enumerate(results, 1):
        print(f"  [{i}] score={r['score']:.4f}  {r['source']}")
    print()
    return results


async def delete_by_sources(sources: set[str], settings: Settings) -> int:
    """删除指定来源（文件名）对应的 chunk。"""
    return await vector_store.delete_by_sources(sources, settings)


async def clear(settings: Settings) -> int:
    """清空知识库，返回删除的 chunk 数。"""
    return await vector_store.clear(settings)


async def get_index_status(settings: Settings) -> dict:
    total = await vector_store.count(settings)
    return {"indexed": total > 0, "total_chunks": total}
