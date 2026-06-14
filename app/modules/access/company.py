from uuid import UUID

import asyncpg
from fastapi import HTTPException

from app.domain.enums import UserRole
from app.modules.cac.repository import (
    fetch_company_by_id,
    fetch_company_for_user,
)


def resolve_user_role(record: asyncpg.Record) -> UserRole:
    raw = record.get("role")
    if raw is not None:
        return UserRole(str(raw))
    if record.get("is_admin"):
        return UserRole.ADMIN
    return UserRole.CLIENT


async def fetch_company_for_agent(
    conn: asyncpg.Connection, company_id: UUID, agent_user_id: UUID
) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT c.id, c.name, c.rc_number, c.tin, c.address, c.user_id, c.created_at,
               u.email AS owner_email, u.full_name AS owner_name
        FROM companies c
        JOIN users u ON u.id = c.user_id
        JOIN company_agent_assignments a
          ON a.company_id = c.id AND a.agent_user_id = $2
        WHERE c.id = $1
        """,
        company_id,
        agent_user_id,
    )


async def is_agent_assigned(
    conn: asyncpg.Connection, company_id: UUID, agent_user_id: UUID
) -> bool:
    row = await conn.fetchrow(
        """
        SELECT 1
        FROM company_agent_assignments
        WHERE company_id = $1 AND agent_user_id = $2
        """,
        company_id,
        agent_user_id,
    )
    return row is not None


async def require_company_read(
    conn: asyncpg.Connection,
    company_id: UUID,
    user_id: UUID,
    role: UserRole,
) -> asyncpg.Record:
    if role == UserRole.ADMIN:
        row = await fetch_company_by_id(conn, company_id)
    elif role == UserRole.CLIENT:
        row = await fetch_company_for_user(conn, company_id, user_id)
    elif role == UserRole.AGENT:
        row = await fetch_company_for_agent(conn, company_id, user_id)
    else:
        row = None
    if row is None:
        raise HTTPException(status_code=404, detail="Company not found")
    return row


async def require_company_client(
    conn: asyncpg.Connection,
    company_id: UUID,
    user_id: UUID,
    role: UserRole,
) -> asyncpg.Record:
    if role != UserRole.CLIENT:
        raise HTTPException(status_code=403, detail="Client access required")
    row = await fetch_company_for_user(conn, company_id, user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Company not found")
    return row


async def require_company_agent(
    conn: asyncpg.Connection,
    company_id: UUID,
    user_id: UUID,
    role: UserRole,
) -> asyncpg.Record:
    if role == UserRole.ADMIN:
        return await require_company_read(conn, company_id, user_id, role)
    if role != UserRole.AGENT:
        raise HTTPException(status_code=403, detail="Agent access required")
    row = await fetch_company_for_agent(conn, company_id, user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Company not found or not assigned to you")
    return row
