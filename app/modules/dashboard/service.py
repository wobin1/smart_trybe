from datetime import date, timedelta
from uuid import UUID

import asyncpg
from fastapi import HTTPException

from app.domain.enums import ComplianceStatus, UserRole
from app.modules.access.company import require_company_read


class DashboardService:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def client_dashboard(self, *, user_id: UUID) -> dict:
        async with self._pool.acquire() as conn:
            companies = await conn.fetch(
                """
                SELECT id, name, rc_number, tin, registration_type::text AS registration_type, created_at
                FROM companies
                WHERE user_id = $1
                ORDER BY created_at DESC
                """,
                user_id,
            )
            company_ids = [c["id"] for c in companies]

            if not company_ids:
                return {
                    "summary": {
                        "company_count": 0,
                        "active_workflows": 0,
                        "in_review": 0,
                        "completed": 0,
                        "upcoming_renewals": 0,
                    },
                    "currently_working_on": [],
                    "companies": [],
                }

            stats = await conn.fetchrow(
                """
                SELECT
                    COUNT(*) FILTER (
                        WHERE status IN ('PENDING'::compliance_status, 'IN_REVIEW'::compliance_status)
                    ) AS active_workflows,
                    COUNT(*) FILTER (WHERE status = 'IN_REVIEW'::compliance_status) AS in_review,
                    COUNT(*) FILTER (WHERE status = 'COMPLETED'::compliance_status) AS completed
                FROM compliance_workflows
                WHERE company_id = ANY($1::uuid[])
                """,
                company_ids,
            )

            renewal_count = await conn.fetchval(
                """
                SELECT COUNT(*)
                FROM compliance_registry
                WHERE company_id = ANY($1::uuid[])
                  AND expiry_date IS NOT NULL
                  AND expiry_date <= CURRENT_DATE + INTERVAL '90 days'
                  AND status = 'COMPLETED'::compliance_status
                """,
                company_ids,
            )

            active_items = await conn.fetch(
                """
                SELECT
                    w.company_id,
                    c.name AS company_name,
                    w.compliance_type::text AS compliance_type,
                    w.mode::text AS mode,
                    w.status::text AS status,
                    w.current_step,
                    w.total_steps,
                    w.last_updated,
                    cc.display_name,
                    cc.icon_key
                FROM compliance_workflows w
                JOIN companies c ON c.id = w.company_id
                LEFT JOIN compliance_catalog cc
                  ON cc.compliance_type = w.compliance_type AND cc.mode = w.mode
                WHERE w.company_id = ANY($1::uuid[])
                  AND w.status IN ('PENDING'::compliance_status, 'IN_REVIEW'::compliance_status)
                ORDER BY w.last_updated DESC
                LIMIT 10
                """,
                company_ids,
            )

            return {
                "summary": {
                    "company_count": len(companies),
                    "active_workflows": int(stats["active_workflows"] or 0),
                    "in_review": int(stats["in_review"] or 0),
                    "completed": int(stats["completed"] or 0),
                    "upcoming_renewals": int(renewal_count or 0),
                },
                "currently_working_on": [
                    {
                        "company_id": str(row["company_id"]),
                        "company_name": row["company_name"],
                        "compliance_type": row["compliance_type"],
                        "mode": row["mode"],
                        "display_name": row["display_name"]
                        or f"{row['compliance_type']} ({row['mode']})",
                        "icon_key": row["icon_key"],
                        "status": row["status"],
                        "current_step": row["current_step"],
                        "total_steps": row["total_steps"],
                        "progress_percent": round(
                            (row["current_step"] / row["total_steps"]) * 100
                        )
                        if row["total_steps"]
                        else 0,
                        "last_updated": row["last_updated"].isoformat(),
                    }
                    for row in active_items
                ],
                "companies": [
                    {
                        "id": str(c["id"]),
                        "name": c["name"],
                        "rc_number": c["rc_number"],
                        "registration_type": c["registration_type"],
                    }
                    for c in companies
                ],
            }

    async def company_dashboard(
        self, *, company_id: UUID, user_id: UUID, role: UserRole
    ) -> dict:
        async with self._pool.acquire() as conn:
            company = await require_company_read(conn, company_id, user_id, role)

            stats = await conn.fetchrow(
                """
                SELECT
                    COUNT(*) FILTER (
                        WHERE status IN ('PENDING'::compliance_status, 'IN_REVIEW'::compliance_status)
                    ) AS active_workflows,
                    COUNT(*) FILTER (WHERE status = 'IN_REVIEW'::compliance_status) AS in_review,
                    COUNT(*) FILTER (WHERE status = 'COMPLETED'::compliance_status) AS completed,
                    COUNT(*) FILTER (WHERE status = 'NOT_STARTED'::compliance_status) AS not_started
                FROM compliance_workflows
                WHERE company_id = $1
                """,
                company_id,
            )

            active_items = await conn.fetch(
                """
                SELECT
                    w.compliance_type::text AS compliance_type,
                    w.mode::text AS mode,
                    w.status::text AS status,
                    w.current_step,
                    w.total_steps,
                    w.last_updated,
                    cc.display_name,
                    cc.icon_key
                FROM compliance_workflows w
                LEFT JOIN compliance_catalog cc
                  ON cc.compliance_type = w.compliance_type AND cc.mode = w.mode
                WHERE w.company_id = $1
                  AND w.status IN ('PENDING'::compliance_status, 'IN_REVIEW'::compliance_status)
                ORDER BY w.last_updated DESC
                """,
                company_id,
            )

            return {
                "company": {
                    "id": str(company["id"]),
                    "name": company["name"],
                    "rc_number": company["rc_number"],
                    "tin": company["tin"],
                },
                "summary": {
                    "active_workflows": int(stats["active_workflows"] or 0),
                    "in_review": int(stats["in_review"] or 0),
                    "completed": int(stats["completed"] or 0),
                    "not_started": int(stats["not_started"] or 0),
                },
                "currently_working_on": [
                    {
                        "compliance_type": row["compliance_type"],
                        "mode": row["mode"],
                        "display_name": row["display_name"]
                        or f"{row['compliance_type']} ({row['mode']})",
                        "icon_key": row["icon_key"],
                        "status": row["status"],
                        "current_step": row["current_step"],
                        "total_steps": row["total_steps"],
                        "progress_percent": round(
                            (row["current_step"] / row["total_steps"]) * 100
                        )
                        if row["total_steps"]
                        else 0,
                        "last_updated": row["last_updated"].isoformat(),
                    }
                    for row in active_items
                ],
            }

    async def upcoming_renewals(
        self,
        *,
        user_id: UUID,
        role: UserRole,
        days: int = 90,
        company_id: UUID | None = None,
    ) -> dict:
        if days < 1 or days > 365:
            raise HTTPException(status_code=400, detail="days must be between 1 and 365")

        cutoff = date.today() + timedelta(days=days)

        async with self._pool.acquire() as conn:
            if company_id is not None:
                await require_company_read(conn, company_id, user_id, role)
                rows = await conn.fetch(
                    """
                    SELECT
                        r.company_id,
                        c.name AS company_name,
                        r.compliance_type::text AS compliance_type,
                        r.status::text AS status,
                        r.expiry_date,
                        cc.display_name,
                        cc.mode::text AS mode,
                        cc.icon_key
                    FROM compliance_registry r
                    JOIN companies c ON c.id = r.company_id
                    LEFT JOIN compliance_catalog cc ON cc.compliance_type = r.compliance_type
                    WHERE r.company_id = $1
                      AND r.expiry_date IS NOT NULL
                      AND r.expiry_date <= $2
                      AND r.status IN ('COMPLETED'::compliance_status, 'EXPIRED'::compliance_status)
                    ORDER BY r.expiry_date ASC
                    """,
                    company_id,
                    cutoff,
                )
            elif role == UserRole.CLIENT:
                rows = await conn.fetch(
                    """
                    SELECT
                        r.company_id,
                        c.name AS company_name,
                        r.compliance_type::text AS compliance_type,
                        r.status::text AS status,
                        r.expiry_date,
                        cc.display_name,
                        cc.mode::text AS mode,
                        cc.icon_key
                    FROM compliance_registry r
                    JOIN companies c ON c.id = r.company_id
                    LEFT JOIN compliance_catalog cc ON cc.compliance_type = r.compliance_type
                    WHERE c.user_id = $1
                      AND r.expiry_date IS NOT NULL
                      AND r.expiry_date <= $2
                      AND r.status IN ('COMPLETED'::compliance_status, 'EXPIRED'::compliance_status)
                    ORDER BY r.expiry_date ASC
                    """,
                    user_id,
                    cutoff,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT
                        r.company_id,
                        c.name AS company_name,
                        r.compliance_type::text AS compliance_type,
                        r.status::text AS status,
                        r.expiry_date,
                        cc.display_name,
                        cc.mode::text AS mode,
                        cc.icon_key
                    FROM compliance_registry r
                    JOIN companies c ON c.id = r.company_id
                    LEFT JOIN compliance_catalog cc ON cc.compliance_type = r.compliance_type
                    WHERE r.expiry_date IS NOT NULL
                      AND r.expiry_date <= $1
                      AND r.status IN ('COMPLETED'::compliance_status, 'EXPIRED'::compliance_status)
                    ORDER BY r.expiry_date ASC
                    """,
                    cutoff,
                )

            today = date.today()
            renewals = []
            for row in rows:
                expiry = row["expiry_date"]
                days_until = (expiry - today).days if expiry else None
                renewals.append(
                    {
                        "company_id": str(row["company_id"]),
                        "company_name": row["company_name"],
                        "compliance_type": row["compliance_type"],
                        "mode": row["mode"],
                        "display_name": row["display_name"] or row["compliance_type"],
                        "icon_key": row["icon_key"],
                        "status": row["status"],
                        "expiry_date": expiry.isoformat() if expiry else None,
                        "days_until_expiry": days_until,
                        "is_expired": days_until is not None and days_until < 0,
                        "is_due_soon": days_until is not None and 0 <= days_until <= 30,
                    }
                )

            return {
                "days_ahead": days,
                "count": len(renewals),
                "renewals": renewals,
            }

    async def agent_dashboard(self, *, user_id: UUID) -> dict:
        async with self._pool.acquire() as conn:
            companies = await conn.fetch(
                """
                SELECT c.id, c.name, c.rc_number, caa.assigned_at
                FROM company_agent_assignments caa
                JOIN companies c ON c.id = caa.company_id
                WHERE caa.agent_user_id = $1
                ORDER BY caa.assigned_at DESC
                """,
                user_id,
            )
            company_ids = [c["id"] for c in companies]

            if not company_ids:
                return {
                    "role": UserRole.AGENT.value,
                    "summary": {
                        "assigned_companies": 0,
                        "in_review": 0,
                        "active_workflows": 0,
                        "completed": 0,
                    },
                    "in_review_queue": [],
                    "assigned_companies": [],
                }

            stats = await conn.fetchrow(
                """
                SELECT
                    COUNT(*) FILTER (WHERE status = 'IN_REVIEW'::compliance_status) AS in_review,
                    COUNT(*) FILTER (
                        WHERE status IN ('PENDING'::compliance_status, 'IN_REVIEW'::compliance_status)
                    ) AS active_workflows,
                    COUNT(*) FILTER (WHERE status = 'COMPLETED'::compliance_status) AS completed
                FROM compliance_workflows
                WHERE company_id = ANY($1::uuid[])
                """,
                company_ids,
            )

            in_review = await conn.fetch(
                """
                SELECT
                    w.company_id,
                    c.name AS company_name,
                    w.compliance_type::text AS compliance_type,
                    w.mode::text AS mode,
                    w.status::text AS status,
                    w.last_updated,
                    cc.display_name,
                    u.email AS owner_email
                FROM compliance_workflows w
                JOIN companies c ON c.id = w.company_id
                JOIN users u ON u.id = c.user_id
                LEFT JOIN compliance_catalog cc
                  ON cc.compliance_type = w.compliance_type AND cc.mode = w.mode
                WHERE w.company_id = ANY($1::uuid[])
                  AND w.status = 'IN_REVIEW'::compliance_status
                ORDER BY w.last_updated ASC
                LIMIT 20
                """,
                company_ids,
            )

            return {
                "role": UserRole.AGENT.value,
                "summary": {
                    "assigned_companies": len(companies),
                    "in_review": int(stats["in_review"] or 0),
                    "active_workflows": int(stats["active_workflows"] or 0),
                    "completed": int(stats["completed"] or 0),
                },
                "in_review_queue": [
                    {
                        "company_id": str(row["company_id"]),
                        "company_name": row["company_name"],
                        "owner_email": row["owner_email"],
                        "compliance_type": row["compliance_type"],
                        "mode": row["mode"],
                        "display_name": row["display_name"]
                        or f"{row['compliance_type']} ({row['mode']})",
                        "status": row["status"],
                        "last_updated": row["last_updated"].isoformat(),
                    }
                    for row in in_review
                ],
                "assigned_companies": [
                    {
                        "id": str(c["id"]),
                        "name": c["name"],
                        "rc_number": c["rc_number"],
                        "assigned_at": c["assigned_at"].isoformat(),
                    }
                    for c in companies
                ],
            }

    async def admin_dashboard(self, *, user_id: UUID) -> dict:
        async with self._pool.acquire() as conn:
            user_stats = await conn.fetchrow(
                """
                SELECT
                    COUNT(*) FILTER (WHERE role = 'CLIENT'::user_role) AS clients,
                    COUNT(*) FILTER (WHERE role = 'AGENT'::user_role) AS agents,
                    COUNT(*) FILTER (WHERE role = 'ADMIN'::user_role) AS admins
                FROM users
                WHERE is_active = TRUE
                """
            )
            company_count = await conn.fetchval("SELECT COUNT(*) FROM companies")
            wf_stats = await conn.fetchrow(
                """
                SELECT
                    COUNT(*) FILTER (WHERE status = 'IN_REVIEW'::compliance_status) AS in_review,
                    COUNT(*) FILTER (WHERE status = 'PENDING'::compliance_status) AS pending,
                    COUNT(*) FILTER (WHERE status = 'COMPLETED'::compliance_status) AS completed
                FROM compliance_workflows
                """
            )
            unassigned = await conn.fetchval(
                """
                SELECT COUNT(*)
                FROM companies c
                WHERE NOT EXISTS (
                    SELECT 1 FROM company_agent_assignments caa WHERE caa.company_id = c.id
                )
                """
            )
            catalog_count = await conn.fetchval(
                "SELECT COUNT(*) FROM compliance_catalog WHERE is_active = TRUE"
            )
            in_review = await conn.fetch(
                """
                SELECT
                    w.company_id,
                    c.name AS company_name,
                    w.compliance_type::text AS compliance_type,
                    w.mode::text AS mode,
                    w.last_updated,
                    u.email AS owner_email
                FROM compliance_workflows w
                JOIN companies c ON c.id = w.company_id
                JOIN users u ON u.id = c.user_id
                WHERE w.status = 'IN_REVIEW'::compliance_status
                ORDER BY w.last_updated ASC
                LIMIT 15
                """
            )

            return {
                "role": UserRole.ADMIN.value,
                "summary": {
                    "companies": int(company_count or 0),
                    "active_clients": int(user_stats["clients"] or 0),
                    "active_agents": int(user_stats["agents"] or 0),
                    "active_admins": int(user_stats["admins"] or 0),
                    "catalog_items": int(catalog_count or 0),
                    "workflows_in_review": int(wf_stats["in_review"] or 0),
                    "workflows_pending": int(wf_stats["pending"] or 0),
                    "workflows_completed": int(wf_stats["completed"] or 0),
                    "unassigned_companies": int(unassigned or 0),
                },
                "in_review_queue": [
                    {
                        "company_id": str(row["company_id"]),
                        "company_name": row["company_name"],
                        "owner_email": row["owner_email"],
                        "compliance_type": row["compliance_type"],
                        "mode": row["mode"],
                        "last_updated": row["last_updated"].isoformat(),
                    }
                    for row in in_review
                ],
            }
