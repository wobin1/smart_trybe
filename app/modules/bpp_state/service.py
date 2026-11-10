from datetime import date
from uuid import UUID

import asyncpg
from fastapi import HTTPException, UploadFile

from app.core.uploads import store_upload
from app.domain.enums import ComplianceStatus, ComplianceType, UserRole
from app.modules.access.company import require_company_agent, require_company_client, require_company_read
from app.modules.bpp_state import repository as bpp_repo
from app.modules.compliance import repository as reg_repo
from app.modules.compliance.engine import ComplianceEngine


def _raise_prerequisites(missing: list[str]) -> None:
    if not missing:
        return
    raise HTTPException(
        status_code=403,
        detail={
            "message": "Compliance prerequisites not satisfied",
            "missing_compliance": missing,
        },
    )


class BPPStateService:
    """State BPP — prefer unified workflow routes; legacy registry helpers remain for compatibility."""

    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def get_registry(
        self, company_id: UUID, user_id: UUID, role: UserRole
    ) -> asyncpg.Record | None:
        async with self._pool.acquire() as conn:
            if await require_company_read(conn, company_id, user_id, role) is None:
                raise HTTPException(status_code=404, detail="Company not found")
            return await bpp_repo.fetch_bpp_state(conn, company_id)

    async def upsert_registry(
        self,
        company_id: UUID,
        user_id: UUID,
        role: UserRole,
        *,
        status: ComplianceStatus,
        expiry_date: date | None,
    ) -> None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                if await require_company_agent(conn, company_id, user_id, role) is None:
                    raise HTTPException(status_code=404, detail="Company not found")

                engine = ComplianceEngine(conn)
                missing = await engine.missing_for_bpp(company_id)
                if status == ComplianceStatus.COMPLETED:
                    _raise_prerequisites(missing)

                await bpp_repo.upsert_bpp_state(conn, company_id, status.value, expiry_date)

    async def upload_document(
        self,
        company_id: UUID,
        user_id: UUID,
        role: UserRole,
        *,
        doc_type: str,
        file: UploadFile,
    ) -> UUID:
        storage_url = await store_upload(
            file,
            doc_type=doc_type,
            company_id=str(company_id),
            compliance_type=ComplianceType.BPP_STATE.value,
        )

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                if role == UserRole.CLIENT:
                    if await require_company_client(conn, company_id, user_id, role) is None:
                        raise HTTPException(status_code=404, detail="Company not found")
                elif await require_company_agent(conn, company_id, user_id, role) is None:
                    raise HTTPException(status_code=404, detail="Company not found")

                engine = ComplianceEngine(conn)
                _raise_prerequisites(await engine.missing_for_bpp(company_id))

                return await reg_repo.insert_document(
                    conn,
                    company_id,
                    ComplianceType.BPP_STATE.value,
                    doc_type,
                    storage_url,
                )
