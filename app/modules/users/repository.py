from uuid import UUID

import asyncpg


async def list_users(
    conn: asyncpg.Connection,
    *,
    role: str | None = None,
) -> list[asyncpg.Record]:
    if role is None:
        return await conn.fetch(
            """
            SELECT id, email, full_name, is_active, is_admin, role::text AS role, created_at
            FROM users
            ORDER BY created_at DESC
            """
        )
    return await conn.fetch(
        """
        SELECT id, email, full_name, is_active, is_admin, role::text AS role, created_at
        FROM users
        WHERE role = $1::user_role
        ORDER BY created_at DESC
        """,
        role,
    )


async def insert_user_with_role(
    conn: asyncpg.Connection,
    email: str,
    password_hash: str,
    full_name: str | None,
    role: str,
) -> UUID:
    is_admin = role == "ADMIN"
    row = await conn.fetchrow(
        """
        INSERT INTO users (email, password_hash, full_name, role, is_admin)
        VALUES (LOWER(TRIM($1)), $2, $3, $4::user_role, $5)
        RETURNING id
        """,
        email,
        password_hash,
        full_name,
        role,
        is_admin,
    )
    assert row is not None
    return row["id"]


async def update_user(
    conn: asyncpg.Connection,
    user_id: UUID,
    *,
    full_name: str | None = None,
    is_active: bool | None = None,
    role: str | None = None,
) -> asyncpg.Record | None:
    sets: list[str] = []
    args: list[object] = [user_id]
    idx = 2
    if full_name is not None:
        sets.append(f"full_name = ${idx}")
        args.append(full_name)
        idx += 1
    if is_active is not None:
        sets.append(f"is_active = ${idx}")
        args.append(is_active)
        idx += 1
    if role is not None:
        sets.append(f"role = ${idx}::user_role")
        args.append(role)
        idx += 1
        sets.append(f"is_admin = ${idx}")
        args.append(role == "ADMIN")
        idx += 1
    if not sets:
        return await fetch_user_by_id(conn, user_id)
    sql = f"""
        UPDATE users
        SET {", ".join(sets)}
        WHERE id = $1
        RETURNING id, email, full_name, is_active, is_admin, role::text AS role, created_at
    """
    return await conn.fetchrow(sql, *args)


async def fetch_user_by_id(conn: asyncpg.Connection, user_id: UUID) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT id, email, full_name, is_active, is_admin, role::text AS role, created_at
        FROM users
        WHERE id = $1
        """,
        user_id,
    )


async def assign_agent_to_company(
    conn: asyncpg.Connection,
    *,
    company_id: UUID,
    agent_user_id: UUID,
    assigned_by: UUID,
) -> asyncpg.Record:
    return await conn.fetchrow(
        """
        INSERT INTO company_agent_assignments (company_id, agent_user_id, assigned_by)
        VALUES ($1, $2, $3)
        ON CONFLICT (company_id, agent_user_id) DO UPDATE
        SET assigned_by = EXCLUDED.assigned_by, assigned_at = NOW()
        RETURNING company_id, agent_user_id, assigned_by, assigned_at
        """,
        company_id,
        agent_user_id,
        assigned_by,
    )


async def unassign_agent_from_company(
    conn: asyncpg.Connection,
    *,
    company_id: UUID,
    agent_user_id: UUID,
) -> bool:
    result = await conn.execute(
        """
        DELETE FROM company_agent_assignments
        WHERE company_id = $1 AND agent_user_id = $2
        """,
        company_id,
        agent_user_id,
    )
    return result.endswith("1")


async def list_assignments_for_company(
    conn: asyncpg.Connection, company_id: UUID
) -> list[asyncpg.Record]:
    return await conn.fetch(
        """
        SELECT a.company_id, a.agent_user_id, a.assigned_by, a.assigned_at,
               u.email AS agent_email, u.full_name AS agent_name
        FROM company_agent_assignments a
        JOIN users u ON u.id = a.agent_user_id
        WHERE a.company_id = $1
        ORDER BY a.assigned_at DESC
        """,
        company_id,
    )


async def list_companies_for_agent(
    conn: asyncpg.Connection, agent_user_id: UUID
) -> list[asyncpg.Record]:
    return await conn.fetch(
        """
        SELECT c.id, c.name, c.rc_number, c.tin, c.address, c.user_id, c.created_at,
               u.email AS owner_email, u.full_name AS owner_name,
               a.assigned_at
        FROM company_agent_assignments a
        JOIN companies c ON c.id = a.company_id
        JOIN users u ON u.id = c.user_id
        WHERE a.agent_user_id = $1
        ORDER BY a.assigned_at DESC
        """,
        agent_user_id,
    )
