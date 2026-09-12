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


# 检索模式。hybrid_year 是生产默认（混合检索 + 年份策略）；
# 其余三个用于消融实验，跑的是同一条检索路径，保证实验结论与线上行为一致。
RETRIEVAL_MODES = ("bm25", "vector", "hybrid", "hybrid_year")
DEFAULT_RETRIEVAL_MODE = "hybrid_year"

# ---- BM25 索引缓存 ----
# BM25Index 构建要对全部 chunk 重新分词，实测 835 个 chunk（43 万字）约 256ms；
# 而它原本每次 rag.search 都会重建，是查询路径上一笔固定开销。
# 这里按 (chunk 数, 最大 id) 做版本指纹缓存：
#   Milvus 的主键自增 → 任何新增都会改变 max_id，任何删除都会改变 count，
#   因此指纹能准确反映语料是否变更，无需额外版本号。
# 进程内缓存，多 worker 部署时每个 worker 各存一份（可接受：只影响首次命中）。
_bm25_cache: dict[str, tuple[tuple[int, int], BM25Index]] = {}


def _bm25_index(collection: str, all_chunks: list[dict]) -> BM25Index:
    """取该 collection 的 BM25 索引；语料未变则直接复用缓存。

    返回的索引其 doc_idx 与传入 all_chunks 的顺序一一对应，
    因此调用方仍用同一份 all_chunks 派生的 id 列表做映射。
    """
    ids = [c["id"] for c in all_chunks]
    fingerprint = (len(ids), max(ids) if ids else 0)
    cached = _bm25_cache.get(collection)
    if cached is not None and cached[0] == fingerprint:
        return cached[1]
    index = BM25Index([c["text"] for c in all_chunks])
    _bm25_cache[collection] = (fingerprint, index)
    return index


def invalidate_bm25_cache(collection: str | None = None) -> None:
    """显式失效缓存。正常情况靠指纹自动失效，这里用于 clear() 这类
    「删表重建、id 可能从头开始」的场景做兜底。"""
    if collection is None:
        _bm25_cache.clear()
    else:
        _bm25_cache.pop(collection, None)


async def search(
    query: str,
    settings: Settings,
    top_k: int | None = None,
    source: str | None = None,
    mode: str = DEFAULT_RETRIEVAL_MODE,
    verbose: bool = True,
) -> list[dict]:
    """混合检索，返回 [{id, source, text, preview, score}]。

    - top_k: 返回条数（默认 settings.top_k）
    - source: 非空时仅返回该来源（文件名）的 chunk
    - mode:   检索策略，见 RETRIEVAL_MODES。默认 hybrid_year = 生产行为
    - verbose: 是否打印检索明细（评测/消融实验批量跑时关掉）

    返回的 score 是向量余弦相似度：bm25 模式未做向量检索，该字段恒为 0.0，
    因此跨模式的对比应基于排名（Recall / MRR），不要横向比较 score。
    """
    if mode not in RETRIEVAL_MODES:
        raise ValueError(f"未知检索模式: {mode}，可选 {RETRIEVAL_MODES}")
    if top_k is None:
        top_k = settings.top_k
    await vector_store.ensure_collection(settings)
    all_chunks = await vector_store.get_all_chunks(settings)
    if not all_chunks:
        return []

    chunk_by_id = {c["id"]: c for c in all_chunks}
    ids = [c["id"] for c in all_chunks]

    years = re.findall(r"20\d{2}", query)
    # 年份策略：查询含年份时把候选集放大到全量，因为各年份公报正文雷同，
    # 正确年份的文档常常排不进默认 top_k。仅 hybrid_year 模式启用。
    use_year_strategy = mode == "hybrid_year" and bool(years)
    search_k = len(all_chunks) if use_year_strategy else settings.top_k

    # ---- 向量检索 ----（bm25 模式不需要向量，省掉一次 embedding 调用）
    vector_ranked: list[tuple[int, float]] = []
    vector_scores: dict[int, float] = {}
    if mode != "bm25":
        query_vec = await embed_query(query, settings)
        vector_ranked = await vector_store.search_by_vector(query_vec, search_k, settings)
        vector_scores = {vid: score for vid, score in vector_ranked}

    # ---- BM25 关键词检索 ----（索引走缓存，语料未变时不再重复分词）
    bm25_ranked: list[int] = []
    if mode != "vector":
        bm25 = _bm25_index(settings.milvus_collection, all_chunks)
        bm25_ranked = [ids[idx] for idx, _ in bm25.search(query, k=search_k)]

    # ---- 融合 ----
    if mode == "vector":
        fused_ids = [vid for vid, _ in vector_ranked]
    elif mode == "bm25":
        fused_ids = bm25_ranked
    else:
        fused_ids = rrf_fuse([vid for vid, _ in vector_ranked], bm25_ranked)

    # ---- 按融合顺序构建结果（按文档去重，避免大文件多 chunk 霸榜） ----
    results = []
    seen_sources = set()
    for cid in fused_ids:
        chunk = chunk_by_id.get(cid)
        if chunk is None:
            continue
        text = (chunk.get("text") or "").strip()
        chunk_source = chunk.get("source") or ""
        if source and chunk_source != source:
            continue
        if not text or chunk_source in seen_sources:
            continue
        seen_sources.add(chunk_source)
        results.append({
            "source": chunk_source,
            "text": text,
            "preview": text[:100],
            "score": vector_scores.get(cid, 0.0),
        })

    results = results[: top_k]
    # 年份软排序：query 含年份时，把文件名含该年份的文档排前面（不硬过滤，
    # 避免把「目标年份」误当文档年份而误伤「十五五」类规划文档）
    if use_year_strategy:
        results.sort(key=lambda r: 0 if any(y in r.get("source", "") for y in years) else 1)

    # 稳定引文 id（1..n，对应最终展示顺序）
    for i, r in enumerate(results, 1):
        r["id"] = i

    if verbose:
        print(f"\n[检索] mode={mode} query=\"{query[:50]}...\" 共 {len(results)} 条:")
        for i, r in enumerate(results, 1):
            print(f"  [{i}] score={r['score']:.4f}  {r['source']}")
        print()
    return results


async def get_document_by_source(source: str, settings: Settings) -> dict:
    """按文件名取出该文档全部 chunk 拼接成全文，返回 {source, text}。"""
    await vector_store.ensure_collection(settings)
    chunks = await vector_store.get_chunks_by_source(source, settings)
    if not chunks:
        return {"source": source, "text": ""}
    text = "\n".join((c.get("text") or "").strip() for c in chunks if (c.get("text") or "").strip())
    return {"source": source, "text": text}


async def delete_by_sources(sources: set[str], settings: Settings) -> int:
    """删除指定来源（文件名）对应的 chunk。"""
    return await vector_store.delete_by_sources(sources, settings)


async def clear(settings: Settings) -> int:
    """清空知识库，返回删除的 chunk 数。"""
    n = await vector_store.clear(settings)
    # 删表重建后 Milvus 主键可能从头开始，指纹会失效于「删了又建同样多」的场景，
    # 这里显式清一次缓存兜底
    invalidate_bm25_cache(settings.milvus_collection)
    return n


async def get_index_status(settings: Settings) -> dict:
    total = await vector_store.count(settings)
    return {"indexed": total > 0, "total_chunks": total}
