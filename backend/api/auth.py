"""
认证接口 —— POST /auth/login、/auth/register。
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import get_settings
from backend.core.deps import get_current_user
from backend.core.security import create_access_token, hash_password, verify_password
from backend.db.session import get_db
from backend.repositories import UserRepository
from backend.schemas import LoginRequest, LoginResponse, RegisterRequest

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest, session: AsyncSession = Depends(get_db)):
    username = request.username.strip()
    password = request.password
    if not username or not password:
        raise HTTPException(status_code=400, detail="用户名和密码不能为空")

    user = await UserRepository(session).get_by_username(username)
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    token = create_access_token(user.username, user.role)
    return LoginResponse(token=token, username=user.username, role=user.role)


@router.post("/register", response_model=LoginResponse)
async def register(request: RegisterRequest, session: AsyncSession = Depends(get_db)):
    username = request.username.strip()
    password = request.password
    if not username or not password:
        raise HTTPException(status_code=400, detail="用户名和密码不能为空")
    if len(username) < 3 or len(password) < 6:
        raise HTTPException(status_code=400, detail="用户名至少3位，密码至少6位")

    repo = UserRepository(session)
    if await repo.exists(username):
        raise HTTPException(status_code=409, detail="用户名已存在")
    await repo.create(username, hash_password(password), "user")

    token = create_access_token(username, "user")
    return LoginResponse(token=token, username=username, role="user")
