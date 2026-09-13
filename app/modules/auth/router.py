from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, EmailStr, Field

from app.api.deps import CurrentUser, db_pool, get_current_user
from app.domain.enums import OAuthProvider, UserRole
from app.modules.access.company import resolve_user_role
from app.modules.auth.service import AuthService


router = APIRouter(prefix="/auth", tags=["Authentication"])

# Bump when Terms of Service / Privacy Policy copy changes materially, so
# consent records stay attributable to the version the user actually saw.
CONSENT_VERSION = "tos-privacy-2026-09-11"


class RegisterBody(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    full_name: str | None = None
    # Optional today so existing clients aren't broken by this rollout; the
    # frontend should send this once it ships a required consent checkbox
    # (compliance audit finding DP-1), after which the backend can enforce it.
    consent_accepted: bool = False


class LoginBody(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


class OAuthLoginBody(BaseModel):
    id_token: str = Field(..., min_length=1)
    full_name: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserMe(BaseModel):
    id: UUID
    email: str
    full_name: str | None
    role: UserRole
    is_admin: bool
    created_at: str


def get_auth_service(pool: asyncpg.Pool = Depends(db_pool)) -> AuthService:
    return AuthService(pool)


@router.post("/register", status_code=201)
async def register(
    body: RegisterBody, request: Request, svc: AuthService = Depends(get_auth_service)
):
    await svc.register(
        email=str(body.email),
        password=body.password,
        full_name=body.full_name,
        consent_accepted=body.consent_accepted,
        consent_version=CONSENT_VERSION,
        consent_ip=request.client.host if request.client else None,
        consent_user_agent=request.headers.get("user-agent"),
    )
    token = await svc.login(email=str(body.email), password=body.password)
    return TokenResponse(access_token=token)


@router.post("/login")
async def login(body: LoginBody, svc: AuthService = Depends(get_auth_service)):
    token = await svc.login(email=str(body.email), password=body.password)
    return TokenResponse(access_token=token)


@router.post("/oauth/{provider}")
async def oauth_login(
    provider: OAuthProvider,
    body: OAuthLoginBody,
    svc: AuthService = Depends(get_auth_service),
):
    token = await svc.oauth_login(
        provider=provider,
        id_token=body.id_token,
        full_name=body.full_name,
    )
    return TokenResponse(access_token=token)


@router.get("/me")
async def me(user: CurrentUser = Depends(get_current_user)):
    r = user.record
    role = resolve_user_role(r)
    return UserMe(
        id=r["id"],
        email=r["email"],
        full_name=r["full_name"],
        role=role,
        is_admin=role == UserRole.ADMIN,
        created_at=r["created_at"].isoformat(),
    )
