"""
认证与授权：密码哈希（pbkdf2）+ 内存 token + FastAPI 依赖。

设计（简单权限）：
- 密码用 hashlib.pbkdf2_hmac 哈希，存 "salt$hash" 字符串
- 登录后发一个随机 token，存内存 dict（后端重启失效，需重新登录）
- require_user / require_admin 作为路由依赖，从 Authorization: Bearer <token> 解析
"""
import hashlib
import os
import secrets
import time
from typing import Optional

from fastapi import Header, HTTPException

from backend.config import Config
from backend.database.connection import get_connection

# token -> {"username": str, "role": str, "expires": float(时间戳)}
_tokens: dict = {}


def hash_password(password: str) -> str:
    """pbkdf2 哈希密码，返回 "salt$hash"。"""
    salt = os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 100000).hex()
    return f"{salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    """校验密码是否与存储的哈希匹配。"""
    try:
        salt, digest = stored.split("$", 1)
    except ValueError:
        return False
    calc = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 100000).hex()
    return secrets.compare_digest(calc, digest)


def create_token(username: str, role: str, ttl_hours: int = 24) -> str:
    """生成随机 token 并存入内存，返回 token 字符串。"""
    token = secrets.token_hex(32)
    _tokens[token] = {
        "username": username,
        "role": role,
        "expires": time.time() + ttl_hours * 3600,
    }
    return token


def get_user_by_token(token: str) -> Optional[dict]:
    """根据 token 查用户，校验过期。"""
    data = _tokens.get(token)
    if not data:
        return None
    if data["expires"] < time.time():
        _tokens.pop(token, None)
        return None
    return data


def _authenticate(authorization: Optional[str] = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录或缺少认证信息")
    token = authorization[7:].strip()
    user = get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="token 无效或已过期")
    return user


def require_user(authorization: Optional[str] = Header(None)) -> dict:
    """依赖：要求已登录（任意角色）。"""
    return _authenticate(authorization)


def require_admin(authorization: Optional[str] = Header(None)) -> dict:
    """依赖：要求 admin 角色。"""
    user = _authenticate(authorization)
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def ensure_default_admin(config: Config) -> None:
    """启动时若无 admin 账号则预置一个（用户名/密码读 config）。"""
    with get_connection(config) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) AS cnt FROM users WHERE username=%s", (config.admin_username,))
        if cursor.fetchone()["cnt"] > 0:
            return
        cursor.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s)",
            (config.admin_username, hash_password(config.admin_password), "admin"),
        )
