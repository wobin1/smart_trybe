from uuid import UUID

import asyncpg


async def insert_company(
    conn: asyncpg.Connection,
    name: str,
    rc_number: str | None,
    tin: str | None,
    address: str | None,
    user_id: UUID,
) -> UUID:
    row = await conn.fetchrow(
        """
        INSERT INTO companies (name, rc_number, tin, address, user_id)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id
        """,
        name,
        rc_number,
        tin,
        address,
        user_id,
    )
    assert row is not None
    return row["id"]


async def fetch_company(conn: asyncpg.Connection, company_id: UUID) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT id, name, rc_number, tin, address, user_id, created_at
        FROM companies
        WHERE id = $1
        """,
        company_id,
    )


async def fetch_company_for_user(
    conn: asyncpg.Connection, company_id: UUID, user_id: UUID
) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT id, name, rc_number, tin, address, user_id, created_at
        FROM companies
        WHERE id = $1 AND user_id = $2
        """,
        company_id,
        user_id,
    )


async def update_company_for_user(
    conn: asyncpg.Connection,
    company_id: UUID,
    user_id: UUID,
    updates: dict[str, str | None],
) -> asyncpg.Record | None:
    allowed = {"name", "rc_number", "tin", "address"}
    set_parts: list[str] = []
    values: list[object] = [company_id, user_id]
    idx = 3
    for field, value in updates.items():
        if field not in allowed:
            continue
        set_parts.append(f"{field} = ${idx}")
        values.append(value)
        idx += 1
    if not set_parts:
        return await fetch_company_for_user(conn, company_id, user_id)

    sql = f"""
        UPDATE companies
        SET {", ".join(set_parts)}
        WHERE id = $1 AND user_id = $2
        RETURNING id, name, rc_number, tin, address, user_id, created_at
    """
    return await conn.fetchrow(sql, *values)


async def list_companies_for_user(conn: asyncpg.Connection, user_id: UUID) -> list[asyncpg.Record]:
    return await conn.fetch(
        """
        SELECT id, name, rc_number, tin, address, user_id, created_at
        FROM companies
        WHERE user_id = $1
        ORDER BY created_at DESC
        """,
        user_id,
    )
