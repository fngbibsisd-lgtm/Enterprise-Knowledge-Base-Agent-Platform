"""
一次性清理脚本 —— 从生产 collection 里删除评测语料（eval/data/*.txt），只保留上传文件。

用法（必须在 agent/ 根目录）：
    python eval/cleanup_prod.py            # 只预览（dry-run），不真正删除
    python eval/cleanup_prod.py --apply    # 真正删除评测语料

背景：早期 eval/build_index.py 把评测语料（eval/data/ 下的政府公文 .txt）误写进了
      生产 collection，导致「索引了 963 个 chunk，实际只有 2 份上传文件」。
      本脚本按 source 精确匹配评测文件名并删除，保留上传文件（PDF 等）。
"""
import asyncio
import glob
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

from backend.core.config import get_settings
from backend.services import rag, vector_store

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


async def _source_counts(settings) -> dict[str, int]:
    """统计生产 collection 各 source 的 chunk 数。"""
    chunks = await vector_store.get_all_chunks(settings)
    counts: dict[str, int] = {}
    for c in chunks:
        src = c.get("source") or "(空)"
        counts[src] = counts.get(src, 0) + 1
    return counts


def _print_counts(title: str, counts: dict[str, int], eval_sources: set[str]) -> None:
    print(title)
    for src, n in sorted(counts.items(), key=lambda x: -x[1]):
        mark = "  <-- 评测语料" if src in eval_sources else ""
        print(f"  {n:>5}  {src}{mark}")
    print(f"  合计: {sum(counts.values())} chunks\n")


async def amain() -> int:
    apply = "--apply" in sys.argv
    settings = get_settings()
    eval_sources = {os.path.basename(f) for f in glob.glob(os.path.join(DATA_DIR, "*.txt"))}

    before = await _source_counts(settings)
    to_delete = set(before) & eval_sources

    _print_counts("当前生产 collection 各来源 chunk 数：", before, eval_sources)

    if not to_delete:
        print("没有匹配到评测语料，无需清理。")
        return 0

    print(f"将删除评测语料 source 共 {len(to_delete)} 个，"
          f"涉及 {sum(before[s] for s in to_delete)} chunks：")
    for s in sorted(to_delete):
        print(f"  - {s} ({before[s]} chunks)")

    if not apply:
        print("\n[预览模式] 未真正删除。确认无误后加 --apply 执行。")
        return 0

    deleted = await rag.delete_by_sources(to_delete, settings)
    print(f"\n已删除 {deleted} chunks。")

    after = await _source_counts(settings)
    _print_counts("清理后生产 collection 各来源 chunk 数：", after, eval_sources)
    return 0


def main() -> int:
    return asyncio.run(amain())


if __name__ == "__main__":
    raise SystemExit(main())
