"""
FastAPI 依赖：当前用户 / 管理员。

用 Depends 做依赖注入，替代原模块级 config = Config() 全局变量。
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.core.security import decode_token

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    """解析 Bearer token，返回 {"username", "role"}。"""
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录或缺少认证信息")
    payload = decode_token(credentials.credentials)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="token 无效或已过期")
    return {"username": payload.get("sub"), "role": payload.get("role", "user")}


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """要求 admin 角色。"""
    if user["role"] != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return user
