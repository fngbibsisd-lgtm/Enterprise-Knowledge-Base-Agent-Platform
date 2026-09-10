"""
批量入库脚本 —— 把 eval/data/*.txt 全部建索引到 Milvus。

用法（必须在 agent/ 根目录）：
    python eval/build_index.py
"""
import asyncio
import glob
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.core.config import get_settings
from backend.services import rag

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


async def amain() -> int:
    settings = get_settings()
    files = sorted(glob.glob(os.path.join(DATA_DIR, "*.txt")))
    if not files:
        print("eval/data/ 下没有 .txt 文件，请先运行 eval/download_docs.py")
        return 1

    print(f"待入库文件: {len(files)} 份")
    print("=" * 60)

    total_chunks = 0
    for i, f in enumerate(files, 1):
        name = os.path.basename(f)
        try:
            n = await rag.build_index_for_file(f, settings)
            total_chunks += n
            print(f"  [{i:>2}/{len(files)}] {n:>4} chunks  {name[:42]}")
        except Exception as e:
            print(f"  [{i:>2}/{len(files)}] 失败  {name[:42]}: {e}")

    status = await rag.get_index_status(settings)
    print("=" * 60)
    print(f"  本次新增 chunks: {total_chunks}")
    print(f"  索引状态: indexed={status['indexed']}  total_chunks={status['total_chunks']}")
    return 0


def main() -> int:
    return asyncio.run(amain())


if __name__ == "__main__":
    raise SystemExit(main())
