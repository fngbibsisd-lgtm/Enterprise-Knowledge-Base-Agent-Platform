"""
RAG 核心服务（异步）—— 切片 → 向量化 → Milvus + BM25 混合检索。

混合检索流程：
    向量检索(Milvus) + BM25 关键词检索 → RRF 融合 → 文档级去重 → 年份软排序

其中「文档级去重」在指定 source 精查某一份文档时跳过（见 search 里的 scoped）：
那时用户的意图是"读这一份"，去重会把同文档里真正答到问题的 chunk 丢掉。
"""
import os
import re
import time
from dataclasses import dataclass

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
    n = await vector_store.add_chunks(chunks, settings)
    invalidate_corpus_cache(settings.milvus_collection)
    return n


# 检索模式。hybrid_year 是生产默认（混合检索 + 年份策略）；
# 其余三个用于消融实验，跑的是同一条检索路径，保证实验结论与线上行为一致。
RETRIEVAL_MODES = ("bm25", "vector", "hybrid", "hybrid_year")
DEFAULT_RETRIEVAL_MODE = "hybrid_year"

# ---- 语料缓存（全量 chunk + BM25 索引）----
# 这两样东西失效条件完全相同（都只依赖 collection 的内容），合并成一个缓存条目，
# 避免两套指纹各说各话。
#
# 为什么需要：
#   原先每次 rag.search 都调 get_all_chunks()，把全量 chunk 正文从 Milvus 拉回来。
#   实测 835 个 chunk（43.5 万字）约 811ms，是单次检索里最大的一项开销——
#   对比之下 Milvus 真正干活的向量检索只要 59ms。BM25 索引构建（238ms）
#   同样在查询路径上，一并缓存。
#
# 指纹为什么用 count()：
#   它走 get_collection_stats，不需要 load collection，实测约 37ms，
#   比全量拉取便宜 20 倍以上，适合放在每次检索的必经路径上。
#
# 已知盲区：count 单独用识别不了「删 N 条再加 N 条」——数量没变但内容变了。
#   因此所有写路径（build_index_for_file / delete_by_sources / clear）都显式失效。
#   单进程下这是严密的；多 worker 部署时别的进程写入本进程不会感知，
#   故再叠一个 TTL 兜底，把最坏情况的陈旧窗口限制在 _CORPUS_TTL_SEC 内。
_CORPUS_TTL_SEC = 60.0


@dataclass
class _CorpusEntry:
    count: int              # 建缓存时的 chunk 数，与 vector_store.count() 比对
    expires_at: float
    chunks: list[dict]
    bm25: BM25Index


_corpus_cache: dict[str, _CorpusEntry] = {}


async def _load_corpus(settings: Settings) -> tuple[list[dict], BM25Index]:
    """取该 collection 的全量 chunk 与 BM25 索引。

    语料未变时直接复用缓存，不向 Milvus 取正文。
    返回的 chunks 其顺序与 BM25 索引的 doc_idx 一一对应，
    因此调用方仍用同一份 chunks 派生的 id 列表做映射。
    """
    key = settings.milvus_collection
    entry = _corpus_cache.get(key)
    if entry is not None and entry.expires_at > time.monotonic():
        if await vector_store.count(settings) == entry.count:
            return entry.chunks, entry.bm25

    chunks = await vector_store.get_all_chunks(settings)
    entry = _CorpusEntry(
        count=len(chunks),
        expires_at=time.monotonic() + _CORPUS_TTL_SEC,
        chunks=chunks,
        bm25=BM25Index([c["text"] for c in chunks]),
    )
    _corpus_cache[key] = entry
    return entry.chunks, entry.bm25


def invalidate_corpus_cache(collection: str | None = None) -> None:
    """显式失效。所有写路径都要调——这是 count 指纹之外的第二道保险
    （也是多 worker 场景下的唯一保险，见上方已知盲区）。"""
    if collection is None:
        _corpus_cache.clear()
    else:
        _corpus_cache.pop(collection, None)


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
    - source: 非空时仅返回该来源（文件名）的 chunk。此时候选池会放大到全量、
      且跳过我文档级去重（见下方 scoped），使「精查某份文档」真的能查到它自己的内容
    - mode:   检索策略，见 RETRIEVAL_MODES。默认 hybrid_year = 生产行为
    - verbose: 是否打印检索明细（评测/消融实验批量跑时关掉）

    返回的 score 是向量余弦相似度：bm25 模式未做向量检索，该字段恒为 0.0，
    因此跨模式的对比应基于排名（Recall / MRR），不要横向比较 score。
    """
    if mode not in RETRIEVAL_MODES:
        raise ValueError(f"未知检索模式: {mode}，可选 {RETRIEVAL_MODES}")
    if top_k is None:
        top_k = settings.top_k
    source = (source or "").strip() or None  # 模型常带首尾空格，一空格之差就查不到
    await vector_store.ensure_collection(settings)
    # 全量语料与 BM25 索引一起走缓存（语料未变时不向 Milvus 取正文）
    all_chunks, bm25 = await _load_corpus(settings)
    if not all_chunks:
        return []

    chunk_by_id = {c["id"]: c for c in all_chunks}
    ids = [c["id"] for c in all_chunks]

    years = re.findall(r"20\d{2}", query)
    # 年份策略：查询含年份时把候选集放大到全量，因为各年份公报正文雷同，
    # 正确年份的文档常常排不进默认 top_k。仅 hybrid_year 模式启用。
    use_year_strategy = mode == "hybrid_year" and bool(years)
    # 指定来源精查时同样要放大候选集：候选池若按 top_k 截断，是在「按来源过滤之前」就截的，
    # 该文档的片段会被别的文档挤掉——问了具体某份文档却检索不到它自己的内容，就是这个原因。
    scoped = settings.rag_source_scoped_search and bool(source)
    search_k = len(all_chunks) if (use_year_strategy or scoped) else settings.top_k

    # ---- 向量检索 ----（bm25 模式不需要向量，省掉一次 embedding 调用）
    vector_ranked: list[tuple[int, float]] = []
    vector_scores: dict[int, float] = {}
    if mode != "bm25":
        query_vec = await embed_query(query, settings)
        vector_ranked = await vector_store.search_by_vector(
            query_vec, search_k, settings, source=source if scoped else None
        )
        vector_scores = {vid: score for vid, score in vector_ranked}

    # ---- BM25 关键词检索 ----（索引与语料同源，已在 _load_corpus 里取好）
    bm25_ranked: list[int] = []
    if mode != "vector":
        bm25_ranked = [ids[idx] for idx, _ in bm25.search(query, k=search_k)]

    # ---- 融合 ----
    if mode == "vector":
        fused_ids = [vid for vid, _ in vector_ranked]
    elif mode == "bm25":
        fused_ids = bm25_ranked
    else:
        fused_ids = rrf_fuse([vid for vid, _ in vector_ranked], bm25_ranked)

    # ---- 按融合顺序构建结果（按文档去重，避免大文件多 chunk 霸榜） ----
    # 按来源精查时**不**去重：只留每篇一条会把同文档里真正答到问题的那条丢掉
    # （实测：目标 chunk 的 BM25 排名是第 0，同文档另有一条排名更高，去重后目标被丢）
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
        if not text or (not scoped and chunk_source in seen_sources):
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

    # 引文 id（1..n，对应**本次检索内**的展示顺序）。
    # 它不是 chunk 身份：Agent 一次回答会调多次工具，每次都从 1 开始，跨调用必然重复。
    # 进 messages 之前由 executor 统一重编号为「整轮唯一」，引用 [n] 才指得准。
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
    n = await vector_store.delete_by_sources(sources, settings)
    if n:
        # 一条都没删掉说明语料没变，不必让缓存白白重建
        invalidate_corpus_cache(settings.milvus_collection)
    return n


async def clear(settings: Settings) -> int:
    """清空知识库，返回删除的 chunk 数。"""
    n = await vector_store.clear(settings)
    # 删表重建后 count 可能恰好回到同一个值，显式清一次缓存兜底
    invalidate_corpus_cache(settings.milvus_collection)
    return n


async def get_index_status(settings: Settings) -> dict:
    total = await vector_store.count(settings)
    return {"indexed": total > 0, "total_chunks": total}
