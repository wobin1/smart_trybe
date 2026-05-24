from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import asyncpg

from app.core.config import settings

_pool: asyncpg.Pool | None = None


async def create_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            dsn=settings.database_url,
            min_size=1,
            max_size=10,
            command_timeout=60,
        )
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Database pool is not initialized; call create_pool during startup.")
    return _pool


@asynccontextmanager
async def acquire_connection() -> AsyncGenerator[asyncpg.Connection, None]:
    pool = get_pool()
    async with pool.acquire() as conn:
        yield conn
