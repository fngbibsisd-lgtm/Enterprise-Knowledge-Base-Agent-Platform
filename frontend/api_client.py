"""
后端 API 客户端

用 httpx 封装后端接口，供 app.py 调用。每个函数对应一个后端接口。

你需要实现 5 个函数：
    - get_status()      -> dict   查询知识库状态
    - upload_file(file) -> dict   上传文档
    - chat(query)       -> dict   普通 RAG 问答
    - agent_chat(query) -> dict   Agent 问答
    - reset(since)      -> dict   重置知识库

提示（后端接口都在 backend/api/ 下，返回 JSON）：
    httpx.get(BACKEND_URL + "/status").json()
    httpx.post(BACKEND_URL + "/upload", files={"file": (文件名, 文件内容)})
    httpx.post(BACKEND_URL + "/chat", json={"query": query})
    httpx.post(BACKEND_URL + "/chat/agent", json={"query": query})
    httpx.post(BACKEND_URL + "/admin/reset", json={"since": since})
"""

import httpx
from config import BACKEND_URL
TIMEOUT = httpx.Timeout(300.0, connect=10.0)

def get_status():
    """查询知识库状态，返回 {"indexed": bool, "total_chunks": int}。TODO：实现"""
    # TODO: GET {BACKEND_URL}/status，返回 JSON
    try:
        return httpx.get(BACKEND_URL + "/status",timeout=TIMEOUT).json()
    except:
        return {"indexed": False, "total_chunks": 0,"error":"后端未启动"}


def upload_file(file):
    """
    上传文档。file 是 Streamlit 的 UploadedFile 对象（有 .name 和 .getvalue()）。
    返回 {"filename": str, "message": str}。TODO：实现
    """
    # TODO: POST {BACKEND_URL}/upload
    # 提示：files={"file": (file.name, file.getvalue())}
    files={"file":(file.name,file.getvalue())}
    resp=httpx.post(BACKEND_URL + "/upload", files=files,timeout=TIMEOUT)
    if resp.status_code != 200:
        try:
            data = resp.json()
            error = data.get("detail") or data.get("message") or data.get(
                "error") or f"上传失败(HTTP {resp.status_code})"
        except Exception:
            error = f"上传失败(HTTP {resp.status_code})"
        return {"error": error}
    return resp.json()


def chat(query):
    """普通 RAG 问答，返回 {"answer": str, "sources": list}。TODO：实现"""
    # TODO: POST {BACKEND_URL}/chat，body={"query": query}
    response=httpx.post(BACKEND_URL + "/chat", json={"query": query},timeout=TIMEOUT).json()
    return response



def agent_chat(query):
    """Agent 问答，返回 {"answer": str, "tool_calls": list, "iterations": int}。TODO：实现"""
    # TODO: POST {BACKEND_URL}/chat/agent，body={"query": query}
    agent_response=httpx.post(BACKEND_URL + "/chat/agent", json={"query": query},timeout=TIMEOUT).json()
    return agent_response


def reset(since):
    """重置知识库，since 可选 "all" / "2h" / "12h" / "24h"。TODO：实现"""
    # TODO: POST {BACKEND_URL}/admin/reset，body={"since": since}
    reset_one=httpx.post(BACKEND_URL + "/admin/reset", json={"since": since},timeout=TIMEOUT).json()
    return reset_one