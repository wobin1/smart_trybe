from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr, Field

from app.api.deps import CurrentUser, db_pool, get_current_user
from app.modules.auth.service import AuthService


router = APIRouter(prefix="/auth", tags=["Authentication"])


class RegisterBody(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    full_name: str | None = None


class LoginBody(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserMe(BaseModel):
    id: UUID
    email: str
    full_name: str | None
    is_admin: bool
    created_at: str


def get_auth_service(pool: asyncpg.Pool = Depends(db_pool)) -> AuthService:
    return AuthService(pool)


@router.post("/register", status_code=201)
async def register(body: RegisterBody, svc: AuthService = Depends(get_auth_service)):
    await svc.register(email=str(body.email), password=body.password, full_name=body.full_name)
    token = await svc.login(email=str(body.email), password=body.password)
    return TokenResponse(access_token=token)


@router.post("/login")
async def login(body: LoginBody, svc: AuthService = Depends(get_auth_service)):
    token = await svc.login(email=str(body.email), password=body.password)
    return TokenResponse(access_token=token)


@router.get("/me")
async def me(user: CurrentUser = Depends(get_current_user)):
    r = user.record
    return UserMe(
        id=r["id"],
        email=r["email"],
        full_name=r["full_name"],
        is_admin=bool(r.get("is_admin")),
        created_at=r["created_at"].isoformat(),
    )
