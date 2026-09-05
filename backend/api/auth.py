"""
认证接口 — POST /auth/login：校验用户名密码，返回 token。
"""
from fastapi import APIRouter, HTTPException

from backend.config import Config
from backend.database.connection import get_connection
from backend.models.schemas import LoginRequest, LoginResponse, RegisterRequest
from backend.security.auth import create_token, verify_password, hash_password

config = Config()
router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/login", response_model=LoginResponse)
def login(request: LoginRequest):
    username = request.username.strip()
    password = request.password
    if not username or not password:
        raise HTTPException(status_code=400, detail="用户名和密码不能为空")

    with get_connection(config) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT username, password_hash, role FROM users WHERE username=%s",
            (username,),
        )
        row = cursor.fetchone()

    if not row or not verify_password(password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    token = create_token(row["username"], row["role"], config.token_ttl_hours)
    return LoginResponse(token=token, username=row["username"], role=row["role"])


@router.post("/register", response_model=LoginResponse)
def register(request: RegisterRequest):
    """注册新用户（默认 user 角色），注册成功后直接返回 token 自动登录。"""
    username = request.username.strip()
    password = request.password
    if not username or not password:
        raise HTTPException(status_code=400, detail="用户名和密码不能为空")
    if len(username) < 3 or len(password) < 6:
        raise HTTPException(status_code=400, detail="用户名至少3位，密码至少6位")

    with get_connection(config) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) AS cnt FROM users WHERE username=%s", (username,))
        if cursor.fetchone()["cnt"] > 0:
            raise HTTPException(status_code=409, detail="用户名已存在")
        cursor.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s)",
            (username, hash_password(password), "user"),
        )

    token = create_token(username, "user", config.token_ttl_hours)
    return LoginResponse(token=token, username=username, role="user")
