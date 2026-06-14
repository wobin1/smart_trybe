from uuid import UUID

import asyncpg
from fastapi import HTTPException

from app.core.security import hash_password
from app.domain.enums import UserRole
from app.modules.cac.repository import fetch_company_by_id
from app.modules.users import repository as users_repo


def _format_user(row: asyncpg.Record) -> dict:
    return {
        "id": str(row["id"]),
        "email": row["email"],
        "full_name": row["full_name"],
        "role": row["role"],
        "is_active": row["is_active"],
        "created_at": row["created_at"].isoformat(),
    }


class UserManagementService:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def list_users(self, *, role: UserRole | None = None) -> dict:
        async with self._pool.acquire() as conn:
            rows = await users_repo.list_users(conn, role=role.value if role else None)
            return {"users": [_format_user(r) for r in rows]}

    async def create_user(
        self,
        *,
        email: str,
        password: str,
        full_name: str | None,
        role: UserRole,
    ) -> dict:
        if role == UserRole.CLIENT:
            raise HTTPException(status_code=400, detail="Clients must self-register via /auth/register")
        async with self._pool.acquire() as conn:
            from app.modules.auth.repository import fetch_user_by_email

            if await fetch_user_by_email(conn, email) is not None:
                raise HTTPException(status_code=409, detail="Email already registered")
            user_id = await users_repo.insert_user_with_role(
                conn,
                email,
                hash_password(password),
                full_name,
                role.value,
            )
            row = await users_repo.fetch_user_by_id(conn, user_id)
            assert row is not None
            return _format_user(row)

    async def update_user(
        self,
        user_id: UUID,
        *,
        full_name: str | None = None,
        is_active: bool | None = None,
        role: UserRole | None = None,
    ) -> dict:
        async with self._pool.acquire() as conn:
            row = await users_repo.update_user(
                conn,
                user_id,
                full_name=full_name,
                is_active=is_active,
                role=role.value if role else None,
            )
            if row is None:
                raise HTTPException(status_code=404, detail="User not found")
            return _format_user(row)

    async def assign_agent(
        self,
        *,
        company_id: UUID,
        agent_user_id: UUID,
        assigned_by: UUID,
    ) -> dict:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                if await fetch_company_by_id(conn, company_id) is None:
                    raise HTTPException(status_code=404, detail="Company not found")
                agent = await users_repo.fetch_user_by_id(conn, agent_user_id)
                if agent is None:
                    raise HTTPException(status_code=404, detail="Agent user not found")
                if agent["role"] != UserRole.AGENT.value:
                    raise HTTPException(status_code=400, detail="User is not an agent")
                row = await users_repo.assign_agent_to_company(
                    conn,
                    company_id=company_id,
                    agent_user_id=agent_user_id,
                    assigned_by=assigned_by,
                )
                return {
                    "company_id": str(row["company_id"]),
                    "agent_user_id": str(row["agent_user_id"]),
                    "assigned_by": str(row["assigned_by"]) if row["assigned_by"] else None,
                    "assigned_at": row["assigned_at"].isoformat(),
                }

    async def unassign_agent(self, *, company_id: UUID, agent_user_id: UUID) -> dict:
        async with self._pool.acquire() as conn:
            removed = await users_repo.unassign_agent_from_company(
                conn, company_id=company_id, agent_user_id=agent_user_id
            )
            if not removed:
                raise HTTPException(status_code=404, detail="Assignment not found")
            return {"company_id": str(company_id), "agent_user_id": str(agent_user_id), "removed": True}

    async def list_company_assignments(self, company_id: UUID) -> dict:
        async with self._pool.acquire() as conn:
            if await fetch_company_by_id(conn, company_id) is None:
                raise HTTPException(status_code=404, detail="Company not found")
            rows = await users_repo.list_assignments_for_company(conn, company_id)
            return {
                "company_id": str(company_id),
                "assignments": [
                    {
                        "agent_user_id": str(r["agent_user_id"]),
                        "agent_email": r["agent_email"],
                        "agent_name": r["agent_name"],
                        "assigned_by": str(r["assigned_by"]) if r["assigned_by"] else None,
                        "assigned_at": r["assigned_at"].isoformat(),
                    }
                    for r in rows
                ],
            }
