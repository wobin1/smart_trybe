from uuid import UUID

import asyncpg
from fastapi import HTTPException
from jose import JWTError

from app.core.security import create_access_token, decode_token, hash_password, parse_user_id_from_payload, verify_password
from app.domain.enums import OAuthProvider
from app.modules.auth import repository as auth_repo
from app.modules.auth.oauth import OAuthUserInfo, verify_oauth_token


class AuthService:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def register(self, *, email: str, password: str, full_name: str | None) -> UUID:
        async with self._pool.acquire() as conn:
            existing = await auth_repo.fetch_user_by_email(conn, email)
            if existing is not None:
                raise HTTPException(status_code=409, detail="Email already registered")
            pw_hash = hash_password(password)
            return await auth_repo.insert_user(conn, email, pw_hash, full_name, role="CLIENT")

    async def login(self, *, email: str, password: str) -> str:
        async with self._pool.acquire() as conn:
            row = await auth_repo.fetch_user_by_email(conn, email)
            if row is None or not row["is_active"]:
                raise HTTPException(status_code=401, detail="Invalid email or password")
            if row["password_hash"] is None:
                raise HTTPException(status_code=401, detail="Invalid email or password")
            if not verify_password(password, row["password_hash"]):
                raise HTTPException(status_code=401, detail="Invalid email or password")
            return create_access_token(subject=str(row["id"]), extra_claims={"email": row["email"]})

    async def oauth_login(
        self,
        *,
        provider: OAuthProvider,
        id_token: str,
        full_name: str | None = None,
    ) -> str:
        info = verify_oauth_token(provider, id_token)
        if not info.email_verified:
            raise HTTPException(status_code=401, detail="Email address is not verified with provider")

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                user_id = await self._resolve_oauth_user(
                    conn,
                    provider=provider,
                    info=info,
                    full_name=full_name,
                )
                row = await auth_repo.fetch_user_by_id(conn, user_id)
                if row is None or not row["is_active"]:
                    raise HTTPException(status_code=401, detail="User not found or inactive")
                return create_access_token(subject=str(row["id"]), extra_claims={"email": row["email"]})

    async def _resolve_oauth_user(
        self,
        conn: asyncpg.Connection,
        *,
        provider: OAuthProvider,
        info: OAuthUserInfo,
        full_name: str | None,
    ) -> UUID:
        oauth_account = await auth_repo.fetch_oauth_account(
            conn,
            provider=provider.value,
            provider_user_id=info.provider_user_id,
        )
        if oauth_account is not None:
            return oauth_account["user_id"]

        existing = await auth_repo.fetch_user_by_email(conn, info.email)
        if existing is not None:
            if existing["role"] != "CLIENT":
                raise HTTPException(
                    status_code=403,
                    detail="Social login is only available for client accounts",
                )
            await auth_repo.insert_oauth_account(
                conn,
                user_id=existing["id"],
                provider=provider.value,
                provider_user_id=info.provider_user_id,
            )
            return existing["id"]

        display_name = full_name or info.full_name
        user_id = await auth_repo.insert_user(
            conn,
            info.email,
            None,
            display_name,
            role="CLIENT",
        )
        await auth_repo.insert_oauth_account(
            conn,
            user_id=user_id,
            provider=provider.value,
            provider_user_id=info.provider_user_id,
        )
        return user_id

    async def get_user_by_token(self, token: str) -> asyncpg.Record:
        try:
            payload = decode_token(token)
            user_id = parse_user_id_from_payload(payload)
        except (JWTError, ValueError):
            raise HTTPException(status_code=401, detail="Invalid or expired token") from None

        async with self._pool.acquire() as conn:
            row = await auth_repo.fetch_user_by_id(conn, user_id)
            if row is None or not row["is_active"]:
                raise HTTPException(status_code=401, detail="User not found or inactive")
            return row
