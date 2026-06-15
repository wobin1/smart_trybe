from datetime import date
from pathlib import Path
from uuid import UUID

import asyncpg
from fastapi import HTTPException, UploadFile

from app.core.storage import build_upload_folder, upload_file
from app.domain.enums import ComplianceStatus, ComplianceType
from app.modules.bpp_federal import repository as bpp_repo
from app.modules.cac.repository import fetch_company_for_user
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


class BPPFederalService:
    """Federal contractor registration gated by active TCC, PENCOM, ITF, NSITF."""

    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def get_registry(self, company_id: UUID, user_id: UUID) -> asyncpg.Record | None:
        async with self._pool.acquire() as conn:
            if await fetch_company_for_user(conn, company_id, user_id) is None:
                raise HTTPException(status_code=404, detail="Company not found")
            return await bpp_repo.fetch_bpp_federal(conn, company_id)

    async def upsert_registry(
        self,
        company_id: UUID,
        user_id: UUID,
        *,
        status: ComplianceStatus,
        expiry_date: date | None,
    ) -> None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                if await fetch_company_for_user(conn, company_id, user_id) is None:
                    raise HTTPException(status_code=404, detail="Company not found")

                engine = ComplianceEngine(conn)
                missing = await engine.missing_for_bpp(company_id)
                if status == ComplianceStatus.COMPLETED:
                    _raise_prerequisites(missing)

                await bpp_repo.upsert_bpp_federal(
                    conn, company_id, status.value, expiry_date
                )

    async def upload_document(
        self,
        company_id: UUID,
        user_id: UUID,
        *,
        doc_type: str,
        file: UploadFile,
    ) -> UUID:
        safe_name = Path(file.filename or "upload").name
        data = await file.read()
        folder = build_upload_folder(
            company_id=str(company_id),
            compliance_type=ComplianceType.BPP_FEDERAL.value,
        )
        storage_url = upload_file(data=data, filename=safe_name, folder=folder)

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                if await fetch_company_for_user(conn, company_id, user_id) is None:
                    raise HTTPException(status_code=404, detail="Company not found")
                engine = ComplianceEngine(conn)
                _raise_prerequisites(await engine.missing_for_bpp(company_id))

                return await reg_repo.insert_document(
                    conn,
                    company_id,
                    ComplianceType.BPP_FEDERAL.value,
                    doc_type,
                    storage_url,
                )
