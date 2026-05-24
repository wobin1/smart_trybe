from uuid import UUID

import asyncpg

from app.domain.enums import ComplianceType
from app.modules.compliance import repository as reg_repo


async def fetch_bpp_federal(conn: asyncpg.Connection, company_id: UUID) -> asyncpg.Record | None:
    return await reg_repo.fetch_registry_row(conn, company_id, ComplianceType.BPP_FEDERAL.value)


async def upsert_bpp_federal(
    conn: asyncpg.Connection,
    company_id: UUID,
    status: str,
    expiry_date,
) -> None:
    await reg_repo.upsert_registry_status(
        conn,
        company_id,
        ComplianceType.BPP_FEDERAL.value,
        status,
        expiry_date,
    )
