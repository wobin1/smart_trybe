from collections.abc import AsyncGenerator
from dataclasses import dataclass
from uuid import UUID

import asyncpg
from fastapi import Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.database import get_pool
from app.domain.enums import UserRole
from app.modules.access.company import resolve_user_role
from app.modules.auth.service import AuthService

security = HTTPBearer()


async def db_pool() -> AsyncGenerator[asyncpg.Pool, None]:
    yield get_pool()


@dataclass(frozen=True)
class CurrentUser:
    id: UUID
    record: asyncpg.Record

    @property
    def role(self) -> UserRole:
        return resolve_user_role(self.record)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    pool: asyncpg.Pool = Depends(db_pool),
) -> CurrentUser:
    svc = AuthService(pool)
    row = await svc.get_user_by_token(credentials.credentials)
    return CurrentUser(id=row["id"], record=row)


async def get_admin_user(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


async def get_agent_user(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if user.role not in (UserRole.AGENT, UserRole.ADMIN):
        raise HTTPException(status_code=403, detail="Agent access required")
    return user


async def get_agent_or_admin_user(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if user.role not in (UserRole.AGENT, UserRole.ADMIN):
        raise HTTPException(status_code=403, detail="Agent or admin access required")
    return user


async def get_current_user_from_header_or_query(
    credentials: HTTPAuthorizationCredentials | None = Depends(
        HTTPBearer(auto_error=False)
    ),
    access_token: str | None = Query(default=None),
    pool: asyncpg.Pool = Depends(db_pool),
) -> CurrentUser:
    """Accept Bearer header or ?access_token= for browser file viewing."""
    token: str | None = None
    if credentials is not None:
        token = credentials.credentials
    elif access_token is not None:
        token = access_token
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    svc = AuthService(pool)
    row = await svc.get_user_by_token(token)
    return CurrentUser(id=row["id"], record=row)
