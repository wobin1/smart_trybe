from uuid import UUID

import asyncpg


async def insert_user(
    conn: asyncpg.Connection,
    email: str,
    password_hash: str,
    full_name: str | None,
    *,
    is_admin: bool = False,
) -> UUID:
    row = await conn.fetchrow(
        """
        INSERT INTO users (email, password_hash, full_name, is_admin)
        VALUES (LOWER(TRIM($1)), $2, $3, $4)
        RETURNING id
        """,
        email,
        password_hash,
        full_name,
        is_admin,
    )
    assert row is not None
    return row["id"]


async def fetch_user_by_email(conn: asyncpg.Connection, email: str) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT id, email, password_hash, full_name, is_active, is_admin, created_at
        FROM users
        WHERE LOWER(TRIM(email)) = LOWER(TRIM($1))
        """,
        email,
    )


async def fetch_user_by_id(conn: asyncpg.Connection, user_id: UUID) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT id, email, full_name, is_active, is_admin, created_at
        FROM users
        WHERE id = $1
        """,
        user_id,
    )
