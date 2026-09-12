"""
检索策略消融实验 —— 在同一份评测集上对比 4 种检索配置，量化每个组件的贡献。

用法（必须在 agent/ 根目录，且已运行 eval/build_index.py 建好索引）：
    python eval/evaluate_retrieval_ablation.py

对比的 4 种配置（都跑 backend/services/rag.py 的同一条代码路径，只是 mode 不同）：

    bm25        仅 BM25 关键词检索（不调 embedding）
    vector      仅 Milvus 向量检索
    hybrid      BM25 + 向量 → RRF 融合（不含年份策略）
    hybrid_year 上面基础上 + 年份候选集放大 + 年份软排序  ← 生产默认

指标：
    Recall@5 / Recall@8  金标准文档是否进入 top-5 / top-8
    MRR@8                首个命中结果的排名倒数均值（反映"排得够不够前"）
    年份Top-1命中率       带 expected_year 的题，top-1 文件名是否含该年份
    平均延迟             每次检索耗时（bm25 模式省掉 embedding 调用，天然更快）

无答案题（gold_keywords 为空）不计入 Recall/MRR——检索层没有"拒答"语义，
误召回率需要相似度阈值才能定义，这类题由 agent 层的拒答率单独评测。

结果同时写入 eval/retrieval_ablation_result.json，供 README 引用。
"""
import asyncio
import json
import os
import statistics
import sys
import time

# 项目根目录：加入 sys.path 并 chdir 过去，保证 ./milvus.db 相对路径解析正确
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

from backend.core.config import get_settings
from backend.services import rag

QA_FILE = os.path.join(os.path.dirname(__file__), "qa_pairs.json")
RESULT_FILE = os.path.join(os.path.dirname(__file__), "retrieval_ablation_result.json")

MODES = ["bm25", "vector", "hybrid", "hybrid_year"]
MODE_LABEL = {
    "bm25": "BM25 仅关键词",
    "vector": "Milvus 仅向量",
    "hybrid": "+ RRF 融合",
    "hybrid_year": "+ 年份策略(生产)",
}


def _hit(sources: list[dict], golds: list[str]) -> bool:
    return any(k in s["source"] for k in golds for s in sources)


def _first_rank(sources: list[dict], golds: list[str]) -> int:
    """首个命中结果的 1-based 排名；未命中返回 0。"""
    for i, s in enumerate(sources, 1):
        if any(k in s["source"] for k in golds):
            return i
    return 0


async def _run_mode(mode: str, pairs: list[dict], settings) -> dict:
    """在给定检索模式下跑完整评测集，返回各项指标。"""
    answerable = [p for p in pairs if p.get("gold_keywords")]
    unanswerable = [p for p in pairs if not p.get("gold_keywords")]

    recall5 = recall8 = 0
    rr_sum = 0.0
    year_total = year_correct = 0
    latencies: list[float] = []
    by_type: dict[str, dict] = {}

    for p in answerable:
        golds = p["gold_keywords"]
        t0 = time.perf_counter()
        sources = await rag.search(p["query"], settings, mode=mode, verbose=False)
        latencies.append((time.perf_counter() - t0) * 1000)

        top5, top8 = sources[:5], sources[:8]
        h5, h8 = _hit(top5, golds), _hit(top8, golds)
        recall5 += int(h5)
        recall8 += int(h8)
        rr_sum += 1.0 / _first_rank(top8, golds) if h8 else 0.0

        exp_year = p.get("expected_year")
        if exp_year is not None:
            year_total += 1
            if sources and exp_year in sources[0]["source"]:
                year_correct += 1

        st = by_type.setdefault(p.get("type", "其他"), {"hit8": 0, "total": 0})
        st["total"] += 1
        st["hit8"] += int(h8)

    n = len(answerable)
    return {
        "mode": mode,
        "label": MODE_LABEL[mode],
        "answerable_n": n,
        "unanswerable_n": len(unanswerable),
        "recall@5": round(recall5 / n, 4) if n else 0.0,
        "recall@8": round(recall8 / n, 4) if n else 0.0,
        "mrr@8": round(rr_sum / n, 4) if n else 0.0,
        "year_top1": round(year_correct / year_total, 4) if year_total else None,
        "year_n": year_total,
        "avg_latency_ms": round(statistics.mean(latencies), 1) if latencies else 0.0,
        "by_type": {
            t: round(v["hit8"] / v["total"], 4) for t, v in sorted(by_type.items())
        },
    }


def _pct(v) -> str:
    return "  -  " if v is None else f"{v * 100:5.1f}%"


async def amain() -> int:
    _settings = get_settings()
    # 检索评测读独立 collection，与生产上传文件索引隔离
    settings = _settings.model_copy(update={"milvus_collection": _settings.milvus_collection_eval})

    with open(QA_FILE, encoding="utf-8") as f:
        pairs = json.load(f)

    status = await rag.get_index_status(settings)
    answerable_n = sum(1 for p in pairs if p.get("gold_keywords"))
    print(f"评测集: {len(pairs)} 题（可答 {answerable_n} / 无答案 {len(pairs) - answerable_n}）")
    print(f"索引: collection={settings.milvus_collection} chunks={status['total_chunks']}")
    if not status["indexed"]:
        print("[警告] 向量索引为空，请先运行 python eval/build_index.py\n")

    results = []
    for mode in MODES:
        print(f"  running {mode} ...", flush=True)
        results.append(await _run_mode(mode, pairs, settings))

    # ---- 汇总表 ----
    print("\n" + "=" * 78)
    print(f"{'检索配置':<22}{'Recall@5':>10}{'Recall@8':>10}{'MRR@8':>9}{'年份Top-1':>11}{'延迟ms':>10}")
    print("-" * 78)
    for r in results:
        print(f"{r['label']:<22}{_pct(r['recall@5']):>10}{_pct(r['recall@8']):>10}"
              f"{r['mrr@8']:>9.3f}{_pct(r['year_top1']):>11}{r['avg_latency_ms']:>10.0f}")
    print("=" * 78)

    base = results[0]
    best = results[-1]
    print("\n各组件相对「仅 BM25」的 Recall@8 提升：")
    for r in results[1:]:
        print(f"  {r['label']:<22} {base['recall@8'] * 100:5.1f}% → {r['recall@8'] * 100:5.1f}%"
              f"  (+{(r['recall@8'] - base['recall@8']) * 100:.1f}pp)")

    print("\n分题型 Recall@8：")
    types = sorted({t for r in results for t in r["by_type"]})
    print(f"  {'题型':<16}" + "".join(f"{r['mode']:>14}" for r in results))
    for t in types:
        row = "".join(f"{_pct(r['by_type'].get(t)):>14}" for r in results)
        print(f"  {t:<16}{row}")

    with open(RESULT_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {"qa_file": os.path.basename(QA_FILE), "total_questions": len(pairs),
             "answerable": answerable_n, "results": results},
            f, ensure_ascii=False, indent=2,
        )
    print(f"\n结果已写入 {os.path.relpath(RESULT_FILE, PROJECT_ROOT)}")
    return 0


def _explain(e: Exception) -> str:
    """把 Milvus Lite 的独占锁错误翻译成可操作的提示。

    Milvus Lite 是单进程独占的：后端 uvicorn 一开着，评测脚本就打不开 ./milvus.db，
    报出来是一大段 pymilvus 堆栈，很容易被误当成代码 bug。
    """
    msg = str(e)
    if "milvus" in msg.lower() or "ConnectionConfig" in type(e).__name__:
        return (
            "无法打开 Milvus 本地库。\n"
            "        Milvus Lite 是独占锁——通常是后端还在运行（uvicorn 占着 ./milvus.db）。\n"
            "        请先停掉后端（Ctrl+C 或 kill 掉 uvicorn 进程），再重跑本脚本。"
        )
    return f"评测中断：{e}"


def main() -> int:
    try:
        return asyncio.run(amain())
    except Exception as e:
        print(f"\n[评测中断] {_explain(e)}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
