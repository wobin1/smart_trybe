from uuid import UUID

import asyncpg
from fastapi import HTTPException
from jose import JWTError

from app.core.config import settings
from app.core.security import create_access_token, decode_token, hash_password, parse_user_id_from_payload, verify_password
from app.modules.auth import repository as auth_repo


class AuthService:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def register(self, *, email: str, password: str, full_name: str | None) -> UUID:
        async with self._pool.acquire() as conn:
            existing = await auth_repo.fetch_user_by_email(conn, email)
            if existing is not None:
                raise HTTPException(status_code=409, detail="Email already registered")
            pw_hash = hash_password(password)
            is_admin = email.strip().lower() in settings.admin_email_set()
            return await auth_repo.insert_user(conn, email, pw_hash, full_name, is_admin=is_admin)

    async def login(self, *, email: str, password: str) -> str:
        async with self._pool.acquire() as conn:
            row = await auth_repo.fetch_user_by_email(conn, email)
            if row is None or not row["is_active"]:
                raise HTTPException(status_code=401, detail="Invalid email or password")
            if not verify_password(password, row["password_hash"]):
                raise HTTPException(status_code=401, detail="Invalid email or password")
            return create_access_token(subject=str(row["id"]), extra_claims={"email": row["email"]})

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
