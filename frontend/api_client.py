"""
后端 API 客户端

用 httpx 封装后端接口，供 app.py 调用。每个函数对应一个后端接口。
V0.4 起：除 get_status 外，其余接口需要登录 token（Authorization: Bearer）。
"""

import httpx
from config import BACKEND_URL

TIMEOUT = httpx.Timeout(300.0, connect=10.0)


def _headers(token=None):
    """构造请求头：有 token 则带 Authorization。"""
    return {"Authorization": f"Bearer {token}"} if token else {}


def get_status():
    """查询知识库状态，返回 {"indexed": bool, "total_chunks": int}。"""
    try:
        return httpx.get(BACKEND_URL + "/status", timeout=TIMEOUT).json()
    except Exception:
        return {"indexed": False, "total_chunks": 0, "error": "后端未启动"}


def login(username, password):
    """登录，成功返回 {"token": str, "username": str, "role": str}，失败返回 {"error": str}。"""
    resp = httpx.post(
        BACKEND_URL + "/auth/login",
        json={"username": username, "password": password},
        timeout=TIMEOUT,
    )
    if resp.status_code != 200:
        try:
            error = resp.json().get("detail") or f"登录失败(HTTP {resp.status_code})"
        except Exception:
            error = f"登录失败(HTTP {resp.status_code})"
        return {"error": error}
    return resp.json()


def register(username, password):
    """注册新用户（默认 user 角色），成功返回 token（注册即登录），失败返回 {"error": str}。"""
    resp = httpx.post(
        BACKEND_URL + "/auth/register",
        json={"username": username, "password": password},
        timeout=TIMEOUT,
    )
    if resp.status_code != 200:
        try:
            error = resp.json().get("detail") or f"注册失败(HTTP {resp.status_code})"
        except Exception:
            error = f"注册失败(HTTP {resp.status_code})"
        return {"error": error}
    return resp.json()


def upload_file(file, token=None):
    """上传文档（需 admin），返回 {"filename": str, "message": str}。"""
    files = {"file": (file.name, file.getvalue())}
    resp = httpx.post(BACKEND_URL + "/upload", files=files, headers=_headers(token), timeout=TIMEOUT)
    if resp.status_code != 200:
        try:
            data = resp.json()
            error = data.get("detail") or data.get("message") or data.get("error") or f"上传失败(HTTP {resp.status_code})"
        except Exception:
            error = f"上传失败(HTTP {resp.status_code})"
        return {"error": error}
    return resp.json()


def chat(query, token=None):
    """普通 RAG 问答（需登录），返回 {"answer": str, "sources": list}。"""
    resp = httpx.post(BACKEND_URL + "/chat", json={"query": query}, headers=_headers(token), timeout=TIMEOUT)
    if resp.status_code != 200:
        try:
            return {"error": resp.json().get("detail") or f"请求失败(HTTP {resp.status_code})"}
        except Exception:
            return {"error": f"请求失败(HTTP {resp.status_code})"}
    return resp.json()


def agent_chat(query, token=None):
    """Agent 问答（需登录），返回 {"answer": str, "tool_calls": list, "iterations": int}。"""
    resp = httpx.post(BACKEND_URL + "/chat/agent", json={"query": query}, headers=_headers(token), timeout=TIMEOUT)
    if resp.status_code != 200:
        try:
            return {"error": resp.json().get("detail") or f"请求失败(HTTP {resp.status_code})"}
        except Exception:
            return {"error": f"请求失败(HTTP {resp.status_code})"}
    return resp.json()


def reset(since, token=None):
    """重置知识库（需 admin），since 可选 "all" / "2h" / "12h" / "24h"。"""
    resp = httpx.post(BACKEND_URL + "/admin/reset", json={"since": since}, headers=_headers(token), timeout=TIMEOUT)
    if resp.status_code != 200:
        try:
            return {"error": resp.json().get("detail") or f"重置失败(HTTP {resp.status_code})"}
        except Exception:
            return {"error": f"重置失败(HTTP {resp.status_code})"}
    return resp.json()
