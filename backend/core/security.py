"""
认证与授权：pbkdf2 密码哈希 + JWT。

- 密码用 hashlib.pbkdf2_hmac（10 万次迭代）哈希，存 "salt$hash"
- 登录签发 JWT（sub=username, role, exp），无状态、可水平扩展
"""
import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone

import jwt

from backend.core.config import get_settings


def hash_password(password: str) -> str:
    """pbkdf2 哈希密码，返回 "salt$hash"。"""
    salt = os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), 100000
    ).hex()
    return f"{salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    """校验密码是否与存储的哈希匹配。"""
    try:
        salt, digest = stored.split("$", 1)
    except ValueError:
        return False
    calc = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), 100000
    ).hex()
    return secrets.compare_digest(calc, digest)


def create_access_token(username: str, role: str) -> str:
    """签发 JWT（sub=username, role, exp）。"""
    settings = get_settings()
    payload = {
        "sub": username,
        "role": role,
        "exp": datetime.now(timezone.utc)
        + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict | None:
    """校验并解析 JWT，失败返回 None。"""
    settings = get_settings()
    try:
        return jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except jwt.PyJWTError:
        return None
