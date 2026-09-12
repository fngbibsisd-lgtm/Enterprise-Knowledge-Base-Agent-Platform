"""
检索延迟构成 + 语料缓存效果 —— 量化「把与查询无关的开销从查询路径剥离」的收益。

用法（必须在 agent/ 根目录；需已运行 eval/build_index.py，且先停掉后端）：
    python eval/bench_search_latency.py

背景：
    rag.search() 原先每次都要做两件与查询本身无关的事——
        get_all_chunks()   把全量 chunk 正文从 Milvus 拉回来
        BM25Index(...)     对全部 chunk 重新分词建索引
    而这两样都只依赖语料内容，语料在一次评测/一段服务期里通常不变。
    现已合并成一个「语料缓存」条目，指纹用廉价的 count()
    （走 get_collection_stats，不需要 load collection）。

本脚本回答三件事：
    1. 单次 rag.search 的耗时到底花在哪（各段多少 ms、占比多少）
    2. 语料缓存的冷/热对比，以及**命中缓存前后检索结果是否完全一致**
    3. BM25 索引构建本身的成本（说明它为什么也值得进缓存）

口径说明：
    embed_query 是外部 API 调用（硅基流动），受网络波动影响，是本机不可优化的部分；
    这里把它单列出来，就是为了不把它的耗时混进「我们自己代码的开销」里。
"""
import asyncio
import os
import re
import statistics
import sys
import time

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

from backend.core.config import get_settings
from backend.services import rag, vector_store
from backend.services.bm25 import BM25Index
from backend.services.embedding import embed_query

# 分段拆解用的 query（取含年份的慢路径，即最坏情况）；冷热对比则两条都跑
QUERY = "2024年国内生产总值是多少？"
QUERIES = [
    ("含年份（触发全量扫描）", QUERY),
    ("不含年份（走默认 top_k）", "政府信息公开工作年度报告包括哪些内容？"),
]


def _ms(t0: float) -> float:
    return (time.perf_counter() - t0) * 1000


async def _timed_async(fn, n: int = 5):
    """跑 n 次取均值，返回 (平均毫秒, 最后一次的返回值)。"""
    ts, out = [], None
    for _ in range(n):
        t0 = time.perf_counter()
        out = await fn()
        ts.append(_ms(t0))
    return statistics.mean(ts), out


def _timed_sync(fn, n: int = 3):
    ts = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        ts.append(_ms(t0))
    return statistics.mean(ts)


async def amain() -> int:
    settings = get_settings()
    # 与其它评测脚本一致：读独立的评测 collection，不碰生产索引
    settings = settings.model_copy(
        update={"milvus_collection": settings.milvus_collection_eval}
    )

    chunks_n = await vector_store.count(settings)
    if not chunks_n:
        print(f"[警告] collection={settings.milvus_collection} 为空，请先运行 python eval/build_index.py")
        return 1
    await vector_store.ensure_collection(settings)
    print(f"collection={settings.milvus_collection}  chunks={chunks_n}")
    print(f"query=\"{QUERY}\"   各段取多次均值\n")

    # ---- 1. 单次检索的各段耗时 ----
    m_ensure, _ = await _timed_async(lambda: vector_store.ensure_collection(settings))
    m_count, _ = await _timed_async(lambda: vector_store.count(settings))
    m_all, chunks = await _timed_async(lambda: vector_store.get_all_chunks(settings), n=3)
    m_bm25 = _timed_sync(lambda: BM25Index([c["text"] for c in chunks]))
    m_embed, vec = await _timed_async(lambda: embed_query(QUERY, settings), n=3)
    # 分段口径必须与 rag.search 对齐：query 含年份时生产路径会把候选集放大到全量
    # （各年份公报正文雷同，正确年份常排不进默认 top_k），这里照做，否则测出来的
    # 向量检索耗时会被严重低估，跟热态总时长对不上。
    years = re.findall(r"20\d{2}", QUERY)
    search_k = chunks_n if years else settings.top_k
    m_vec, _ = await _timed_async(
        lambda: vector_store.search_by_vector(vec, search_k, settings)
    )

    segments = [
        ("ensure_collection (含 load_collection)", m_ensure),
        ("count()            (缓存指纹，很廉价)", m_count),
        ("get_all_chunks()   (全量拉正文，走缓存)", m_all),
        ("BM25Index 构建     (走缓存)", m_bm25),
        ("embed_query        (外部 API，不可优化)", m_embed),
        (f"search_by_vector   (Milvus，search_k={search_k})", m_vec),
    ]
    total = sum(v for _, v in segments)
    for name, v in segments:
        print(f"  {name:<40}{v:>9.1f} ms   {v / total * 100:>5.1f}%")
    print(f"  {'-' * 58}")
    print(f"  {'分段合计（首次）':<40}{total:>9.1f} ms")

    # ---- 2. 语料缓存冷/热对比 + 结果一致性 ----
    # 分两条 query：含年份的会触发全量扫描（search_k=835），是慢路径；
    # 不含年份的走默认 top_k，是绝大多数请求的实际路径。两者的缓存收益不同。
    print("\n语料缓存冷/热对比：")
    print(f"  {'查询':<34}{'冷':>11}{'热':>11}{'降幅':>9}")
    for label, q in QUERIES:
        rag.invalidate_corpus_cache(settings.milvus_collection)

        t0 = time.perf_counter()
        cold = await rag.search(q, settings, verbose=False)
        cold_ms = _ms(t0)

        warm_ms, _ = await _timed_async(
            lambda: rag.search(q, settings, verbose=False), n=5
        )
        # 缓存绝不能改变检索结果——这是本次改动唯一的正确性要求
        warm = await rag.search(q, settings, verbose=False)

        if [r["source"] for r in cold] != [r["source"] for r in warm]:
            print(f"\n[FAIL] 「{label}」命中缓存前后结果不一致，缓存实现有 bug：")
            print(f"       冷: {[r['source'] for r in cold]}")
            print(f"       热: {[r['source'] for r in warm]}")
            return 1

        print(f"  {label:<34}{cold_ms:>9.0f}ms{warm_ms:>9.0f}ms"
              f"{cold_ms / warm_ms:>8.1f}x")
    print("\n[OK] 两条 query 的冷/热检索结果均完全一致（逐条来源对齐）")

    print("\n注意：缓存靠两道保险失效——")
    print("      ① count() 指纹变化（新增/删除 chunk 都会改变它）")
    print("      ② 写路径显式失效（add_chunks / delete_by_sources / clear）")
    print("      另叠 60s TTL，兜住多 worker 场景下别的进程写入的盲区。")
    return 0


def _explain(e: Exception) -> str:
    """把 Milvus Lite 的独占锁错误翻译成可操作的提示。"""
    msg = str(e)
    if "milvus" in msg.lower() or "ConnectionConfig" in type(e).__name__:
        return (
            "无法打开 Milvus 本地库。\n"
            "        Milvus Lite 是独占锁——通常是后端还在运行（uvicorn 占着 ./milvus.db）。\n"
            "        请先停掉后端（Ctrl+C 或 kill 掉 uvicorn 进程），再重跑本脚本。"
        )
    return f"基准中断：{e}"


def main() -> int:
    try:
        return asyncio.run(amain())
    except Exception as e:
        print(f"\n[基准中断] {_explain(e)}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
