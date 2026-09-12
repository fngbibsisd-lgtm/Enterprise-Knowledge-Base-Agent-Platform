"""
批量入库脚本 —— 把 eval/data/*.txt 全部建索引到 Milvus。

用法（必须在 agent/ 根目录）：
    python eval/build_index.py
"""
import asyncio
import glob
import os
import sys

# 项目根目录：加入 sys.path 并 chdir 过去，保证 ./milvus.db / ./data 相对路径解析正确（无论从哪里运行）
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

from backend.core.config import get_settings
from backend.services import rag

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


async def amain() -> int:
    _settings = get_settings()
    # 评测语料写入独立 collection，避免和生产上传文件混在同一个索引里
    settings = _settings.model_copy(update={"milvus_collection": _settings.milvus_collection_eval})
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
    print(f"  评测索引状态(collection={settings.milvus_collection}): indexed={status['indexed']}  total_chunks={status['total_chunks']}")
    return 0


def main() -> int:
    return asyncio.run(amain())


if __name__ == "__main__":
    raise SystemExit(main())
