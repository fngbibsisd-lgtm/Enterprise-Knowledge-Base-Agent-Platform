"""
把评测结果 JSON 渲染成 Markdown 表格，供 README 直接粘贴。

用法（必须在 agent/ 根目录）：
    python eval/render_results.py

读入：
    eval/retrieval_ablation_result.json   ← 由 evaluate_retrieval_ablation.py 生成
    eval/agent_eval_result.json           ← 由 evaluate_agent.py 生成

两个文件都不存在时，会提示先跑对应脚本（不会凭空编数字）。
"""
import json
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RETRIEVAL_FILE = os.path.join(os.path.dirname(__file__), "retrieval_ablation_result.json")
AGENT_FILE = os.path.join(os.path.dirname(__file__), "agent_eval_result.json")


def _pct(v) -> str:
    return "—" if v is None else f"{v * 100:.1f}%"


def render_retrieval() -> None:
    if not os.path.exists(RETRIEVAL_FILE):
        print("## 检索消融\n\n> 尚未运行 evaluate_retrieval_ablation.py，暂无数据。\n")
        return
    with open(RETRIEVAL_FILE, encoding="utf-8") as f:
        d = json.load(f)

    print(f"## 检索消融（{d['total_questions']} 题，其中可答 {d['answerable']} 题）\n")
    print("| 检索配置 | Recall@5 | Recall@8 | MRR@8 | 年份 Top-1 | 平均延迟 |")
    print("|---|---:|---:|---:|---:|---:|")
    for r in d["results"]:
        year = "—" if r["year_top1"] is None else _pct(r["year_top1"])
        print(f"| {r['label']} | {_pct(r['recall@5'])} | {_pct(r['recall@8'])} | "
              f"{r['mrr@8']:.3f} | {year} | {r['avg_latency_ms']:.0f} ms |")

    base, best = d["results"][0], d["results"][-1]
    print(f"\n相比「仅 BM25」，生产配置 Recall@8 变化："
          f"{_pct(base['recall@8'])} → {_pct(best['recall@8'])}"
          f"（{(best['recall@8'] - base['recall@8']) * 100:+.1f}pp）\n")

    print("\n### 分题型 Recall@8\n")
    types = sorted({t for r in d["results"] for t in r["by_type"]})
    print("| 题型 | " + " | ".join(r["mode"] for r in d["results"]) + " |")
    print("|---|" + "---:|" * len(d["results"]))
    for t in types:
        cells = " | ".join(_pct(r["by_type"].get(t)) for r in d["results"])
        print(f"| {t} | {cells} |")
    print()


def render_agent() -> None:
    if not os.path.exists(AGENT_FILE):
        print("## Agent 评测\n\n> 尚未运行 evaluate_agent.py，暂无数据。\n")
        return
    with open(AGENT_FILE, encoding="utf-8") as f:
        d = json.load(f)

    print(f"## Agent 评测（{d['total']} 题）\n")
    print("| 指标 | 结果 | 样本数 |")
    print("|---|---:|---:|")
    rows = [
        ("任务完成率", d["completion_rate"], d["total"]),
        ("工具选择正确率", d["tool_selection_rate"], d["tool_selection_n"]),
        ("引用命中率", d["citation_hit_rate"], d["citation_hit_n"]),
        ("拒答正确率", d["refusal_accuracy"], d["refusal_n"]),
        ("正确率（LLM 裁判）", d["judge_correct"], d["judge_n"]),
        ("忠实性/无幻觉（LLM 裁判）", d["judge_grounded"], d["judge_n"]),
    ]
    for name, val, n in rows:
        print(f"| {name} | {_pct(val)} | {n} |")
    print(f"| 平均延迟 | {d['avg_latency_sec']:.1f} s/题 | {d['total']} |")
    print(f"| 平均迭代轮数 | {d['avg_iterations']:.1f} | {d['total']} |")

    if d.get("mcp_required"):
        print(f"\n其中依赖 MCP 的 {d['mcp_required']} 题通过 {d['mcp_passed']} 题。")

    print("\n### 分题型\n")
    print("| 题型 | 题数 | 完成率 | 工具选择 |")
    print("|---|---:|---:|---:|")
    for t, st in d["by_type"].items():
        tool = "—" if st["tool_selection"] is None else _pct(st["tool_selection"])
        print(f"| {t} | {st['n']} | {_pct(st['completion'])} | {tool} |")
    print()


def main() -> int:
    render_retrieval()
    render_agent()
    print("---")
    print("以上表格直接粘进 README 的 Evaluation 章节。数字均来自本地真实运行结果。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
