from pathlib import Path

import asyncpg


async def run_schema(conn: asyncpg.Connection) -> None:
    schema_path = Path(__file__).resolve().parent / "schema.sql"
    sql = schema_path.read_text(encoding="utf-8")
    await conn.execute(sql)


async def bootstrap_database(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await run_schema(conn)
