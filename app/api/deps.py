from collections.abc import AsyncGenerator
from dataclasses import dataclass
from uuid import UUID

import asyncpg
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.database import get_pool
from app.modules.auth.service import AuthService

security = HTTPBearer()


async def db_pool() -> AsyncGenerator[asyncpg.Pool, None]:
    yield get_pool()


@dataclass(frozen=True)
class CurrentUser:
    id: UUID
    record: asyncpg.Record


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    pool: asyncpg.Pool = Depends(db_pool),
) -> CurrentUser:
    svc = AuthService(pool)
    row = await svc.get_user_by_token(credentials.credentials)
    return CurrentUser(id=row["id"], record=row)
