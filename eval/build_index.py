"""
批量入库脚本 —— 把 eval/data/*.txt 全部建索引到 FAISS。

用法（必须在 agent/ 根目录，否则 from backend.xxx 导入报错）：
    python eval/build_index.py

流程：
    1. 收集 eval/data/*.txt
    2. 逐个调 backend.services.rag.build_index_for_file（切片 → embedding → 追加索引）
    3. 统计总 chunk 数、索引状态
"""
import glob
import os
import sys

# 把项目根目录加入 sys.path，保证 from backend.xxx 可导入
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.config import Config
from backend.services import rag

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


def main() -> int:
    config = Config()
    files = sorted(glob.glob(os.path.join(DATA_DIR, "*.txt")))
    if not files:
        print("eval/data/ 下没有 .txt 文件，请先运行 eval/download_docs.py")
        return 1

    print(f"待入库文件: {len(files)} 份")
    print(f"索引路径: {config.index_path}")
    print("=" * 60)

    total_chunks = 0
    for i, f in enumerate(files, 1):
        name = os.path.basename(f)
        try:
            n = rag.build_index_for_file(f, config)
            total_chunks += n
            print(f"  [{i:>2}/{len(files)}] {n:>4} chunks  {name[:42]}")
        except Exception as e:
            print(f"  [{i:>2}/{len(files)}] 失败  {name[:42]}: {e}")

    status = rag.get_index_status(config)
    print("=" * 60)
    print(f"  本次新增 chunks: {total_chunks}")
    print(f"  索引状态: indexed={status['indexed']}  total_chunks={status['total_chunks']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
