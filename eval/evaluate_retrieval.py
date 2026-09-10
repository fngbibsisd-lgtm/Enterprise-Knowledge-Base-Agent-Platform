"""
检索质量评测脚本 —— 对 eval/qa_pairs.json 逐题跑 rag.search()，统计检索指标。

用法（必须在 agent/ 根目录）：
    python eval/evaluate_retrieval.py

指标：
    - Recall@5 / Recall@8 ：标准答案文档是否进入 top-5 / top-8
    - 年份 Top-1 命中率   ：带 expected_year 的题，top-1 是否含正确年份
    - 平均检索延迟        ：每次 rag.search() 耗时（含 query 向量化）

前置：已运行 eval/build_index.py 建好索引。
"""
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.core.config import get_settings
from backend.services import rag

QA_FILE = os.path.join(os.path.dirname(__file__), "qa_pairs.json")


def hit(source: str, keywords: list[str]) -> bool:
    """判断检索返回的 source 是否命中任一 gold 关键词。"""
    return any(k in source for k in keywords)


async def amain() -> int:
    settings = get_settings()
    with open(QA_FILE, encoding="utf-8") as f:
        pairs = json.load(f)

    total = len(pairs)
    recall5 = recall8 = 0
    year_total = year_correct = 0
    latencies: list[float] = []
    by_type: dict[str, dict] = {}

    print(f"评测题库: {total} 题，索引 top_k={settings.top_k}\n")
    print(f"{'题型':<12} {'状态':<6} {'Recall@5':<9} {'Recall@8':<9} {'年份':<6} {'延迟ms':<8}  题目")

    for p in pairs:
        typ = p.get("type", "其他")
        golds = p["gold_keywords"]
        exp_year = p.get("expected_year")

        t0 = time.time()
        sources = await rag.search(p["query"], settings)
        lat = (time.time() - t0) * 1000
        latencies.append(lat)

        top5 = sources[:5]
        top8 = sources[:8]
        hit5 = any(hit(s["source"], golds) for s in top5)
        hit8 = any(hit(s["source"], golds) for s in top8)

        year_ok = None
        if exp_year is not None:
            year_total += 1
            if sources:
                year_ok = exp_year in sources[0]["source"]
                if year_ok:
                    year_correct += 1
            else:
                year_ok = False

        if hit5:
            recall5 += 1
        if hit8:
            recall8 += 1

        st = by_type.setdefault(typ, {"hit5": 0, "hit8": 0, "total": 0})
        st["total"] += 1
        st["hit5"] += int(hit5)
        st["hit8"] += int(hit8)

        yt = "-" if year_ok is None else ("Y" if year_ok else "N")
        print(f"{typ:<12} {'Y' if hit8 else 'N':<6} {'Y' if hit5 else 'N':<9} "
              f"{'Y' if hit8 else 'N':<9} {yt:<6} {lat:>6.0f}   {p['query'][:38]}")

    avg_lat = sum(latencies) / len(latencies) if latencies else 0
    print("\n" + "=" * 60)
    print(f"  Recall@5         : {recall5}/{total} = {recall5 / total * 100:.1f}%")
    print(f"  Recall@8         : {recall8}/{total} = {recall8 / total * 100:.1f}%")
    print(f"  年份Top-1命中率   : {year_correct}/{year_total} = "
          f"{(year_correct / year_total * 100 if year_total else 100):.1f}%")
    print(f"  平均检索延迟      : {avg_lat:.0f} ms")
    print("=" * 60)

    print("\n分题型 Recall@8：")
    for typ, st in sorted(by_type.items()):
        r = st["hit8"] / st["total"] * 100
        print(f"  {typ:<12} {st['hit8']}/{st['total']} = {r:.1f}%")

    return 0


def main() -> int:
    return asyncio.run(amain())


if __name__ == "__main__":
    raise SystemExit(main())
