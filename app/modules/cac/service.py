from datetime import date
from pathlib import Path
from uuid import UUID

import asyncpg
from fastapi import HTTPException, UploadFile

from app.core.storage import build_upload_folder, upload_file
from app.domain.enums import ComplianceStatus, ComplianceType, UserRole
from app.modules.access.company import (
    require_company_agent,
    require_company_client,
    require_company_read,
)
from app.modules.cac import repository as company_repo
from app.modules.compliance import repository as reg_repo


def _ensure_company(row: asyncpg.Record | None) -> asyncpg.Record:
    if row is None:
        raise HTTPException(status_code=404, detail="Company not found")
    return row


class CACService:
    """CAC registration & annual returns — registry + documents."""

    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def create_company(
        self,
        *,
        name: str,
        rc_number: str | None,
        tin: str | None,
        address: str | None,
        user_id: UUID,
        role: UserRole,
    ) -> UUID:
        if role != UserRole.CLIENT:
            raise HTTPException(status_code=403, detail="Only clients can create companies")
        async with self._pool.acquire() as conn:
            company_id = await company_repo.insert_company(
                conn, name=name, rc_number=rc_number, tin=tin, address=address, user_id=user_id
            )
            await reg_repo.upsert_registry_status(
                conn,
                company_id,
                ComplianceType.CAC.value,
                ComplianceStatus.NOT_STARTED.value,
                None,
            )
            return company_id

    async def get_company(
        self, company_id: UUID, user_id: UUID, role: UserRole
    ) -> asyncpg.Record:
        async with self._pool.acquire() as conn:
            row = await require_company_read(conn, company_id, user_id, role)
            return row

    async def update_company(
        self,
        company_id: UUID,
        user_id: UUID,
        role: UserRole,
        updates: dict[str, str | None],
    ) -> asyncpg.Record:
        async with self._pool.acquire() as conn:
            _ensure_company(await require_company_client(conn, company_id, user_id, role))
            row = await company_repo.update_company_for_user(
                conn, company_id, user_id, updates
            )
            return _ensure_company(row)

    async def list_companies(self, user_id: UUID, role: UserRole) -> list[asyncpg.Record]:
        if role != UserRole.CLIENT:
            raise HTTPException(status_code=403, detail="Only clients can list owned companies")
        async with self._pool.acquire() as conn:
            return await company_repo.list_companies_for_user(conn, user_id)

    async def get_cac_registry(
        self, company_id: UUID, user_id: UUID, role: UserRole
    ) -> asyncpg.Record | None:
        async with self._pool.acquire() as conn:
            _ensure_company(await require_company_read(conn, company_id, user_id, role))
            return await reg_repo.fetch_registry_row(conn, company_id, ComplianceType.CAC.value)

    async def update_cac_registry(
        self,
        company_id: UUID,
        user_id: UUID,
        role: UserRole,
        *,
        status: ComplianceStatus,
        expiry_date: date | None,
    ) -> None:
        async with self._pool.acquire() as conn:
            _ensure_company(await require_company_agent(conn, company_id, user_id, role))
            await reg_repo.upsert_registry_status(
                conn, company_id, ComplianceType.CAC.value, status.value, expiry_date
            )

    async def upload_document(
        self,
        company_id: UUID,
        user_id: UUID,
        role: UserRole,
        *,
        doc_type: str,
        file: UploadFile,
    ) -> UUID:
        async with self._pool.acquire() as conn:
            _ensure_company(await require_company_client(conn, company_id, user_id, role))

        safe_name = Path(file.filename or "upload").name
        data = await file.read()
        folder = build_upload_folder(
            company_id=str(company_id),
            compliance_type=ComplianceType.CAC.value,
        )
        storage_url = upload_file(data=data, filename=safe_name, folder=folder)

        async with self._pool.acquire() as conn:
            doc_id = await reg_repo.insert_document(
                conn,
                company_id,
                ComplianceType.CAC.value,
                doc_type,
                storage_url,
            )
        return doc_id
