"""
BM25 索引缓存基准 —— 量化「把建索引从查询路径剥离」的收益。

用法（必须在 agent/ 根目录，不需要 Milvus）：
    python eval/bench_bm25_cache.py

背景：
    BM25Index 构建要对全部 chunk 重新分词。原实现里 rag.search() 每次都重建一次，
    成为查询路径上的固定开销。改成按 (chunk 数, 最大 id) 指纹缓存后，
    只有语料变更时才会重建。

口径说明：
    这里只测 BM25 那一段的开销。完整一次 rag.search 还包含 Milvus 向量检索
    和一次 embedding API 调用，端到端耗时不是本脚本的数字——
    本脚本回答的是「BM25 这一段从多少降到多少」。
"""
import os
import statistics
import sys
import time

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

from backend.services import rag
from backend.services.bm25 import BM25Index
from backend.services.document import chunk_documents, load_documents

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
REPEAT = 50


def main() -> int:
    docs = load_documents(DATA_DIR)
    chunks = chunk_documents(docs, 512, 50)
    all_chunks = [
        {"id": i + 1, "text": f"【来源：{c.metadata['source']}】{c.text}"}
        for i, c in enumerate(chunks)
    ]
    total_chars = sum(len(c["text"]) for c in all_chunks)
    print(f"语料: {len(docs)} 份文档 → {len(all_chunks)} 个 chunk（{total_chars:,} 字）\n")

    # ---- Before：每次检索都重建索引 ----
    timings = []
    for _ in range(4):
        t0 = time.perf_counter()
        BM25Index([c["text"] for c in all_chunks])
        timings.append(time.perf_counter() - t0)
    before_ms = statistics.mean(timings) * 1000

    # ---- After：冷启动一次 + 命中缓存 ----
    rag.invalidate_bm25_cache("bench")
    t0 = time.perf_counter()
    rag._bm25_index("bench", all_chunks)
    cold_ms = (time.perf_counter() - t0) * 1000

    timings = []
    for _ in range(REPEAT):
        t0 = time.perf_counter()
        rag._bm25_index("bench", all_chunks)
        timings.append(time.perf_counter() - t0)
    warm_ms = statistics.mean(timings) * 1000

    print(f"{'每次检索重建（原实现）':<26}{before_ms:>10.1f} ms")
    print(f"{'首次构建（冷，等价原开销）':<24}{cold_ms:>10.1f} ms")
    print(f"{'命中缓存（改后常态）':<26}{warm_ms:>10.3f} ms")
    print("-" * 36)
    print(f"BM25 段降幅: {before_ms / warm_ms:.0f}x")
    print(f"100 次检索累计省下: {(before_ms - warm_ms) * 100 / 1000:.1f} s")
    print("\n注意: 缓存按 (chunk 数, 最大 id) 指纹自动失效——")
    print("      新增文档改变 max_id、删除文档改变 count，都会触发重建，无需手动清理。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
