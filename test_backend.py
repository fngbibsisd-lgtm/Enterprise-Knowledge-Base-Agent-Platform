"""
backend 冒烟测试脚本

用法：
    1. 先启动服务（在 agent/ 根目录）：
       python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
    2. 另开一个终端运行：
       python test_backend.py

覆盖：根路由 / 状态 / RAG 问答 / Agent 查库 / Agent 查文档，共 5 项。
依赖 httpx（openai 库已附带安装）。
"""

import sys
import httpx

BASE = "http://127.0.0.1:8000"


def check(name: str, ok: bool, detail: str = "") -> bool:
    status = "PASS" if ok else "FAIL"
    line = f"[{status}] {name}"
    if detail:
        line += f"  -> {detail}"
    print(line)
    return ok


def main() -> int:
    results = []

    # 1. 根路由
    r = httpx.get(f"{BASE}/")
    ok = r.status_code == 200 and r.json().get("status") == "running"
    results.append(check("GET /", ok))

    # 2. 知识库状态
    r = httpx.get(f"{BASE}/status")
    ok = r.status_code == 200 and "total_chunks" in r.json()
    results.append(check("GET /status", ok, f"chunks={r.json().get('total_chunks')}"))

    # 3. RAG 问答（文档检索 + LLM）
    r = httpx.post(f"{BASE}/chat", json={"query": "2024年国民经济和社会发展情况如何？"}, timeout=120)
    d = r.json() if r.status_code == 200 else {}
    ok = r.status_code == 200 and bool(d.get("answer")) and bool(d.get("sources"))
    results.append(check("POST /chat (RAG)", ok, f"status={r.status_code}, sources={len(d.get('sources', []))}"))

    # 4. Agent 数据类（应自动调 sql_query）
    r = httpx.post(f"{BASE}/chat/agent", json={"query": "最近上传了几个文件？"}, timeout=120)
    d = r.json() if r.status_code == 200 else {}
    ok = r.status_code == 200 and any(t.get("tool_name") == "sql_query" for t in d.get("tool_calls", []))
    results.append(check("POST /chat/agent (sql_query)", ok,
                         f"status={r.status_code}, iterations={d.get('iterations')}"))

    # 5. Agent 文档类（应自动调 knowledge_search）
    r = httpx.post(f"{BASE}/chat/agent", json={"query": "2024年GDP增长情况如何？"}, timeout=120)
    d = r.json() if r.status_code == 200 else {}
    ok = r.status_code == 200 and any(t.get("tool_name") == "knowledge_search" for t in d.get("tool_calls", []))
    results.append(check("POST /chat/agent (knowledge_search)", ok, f"status={r.status_code}"))

    print()
    passed = sum(results)
    print(f"结果: {passed}/{len(results)} 通过")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
