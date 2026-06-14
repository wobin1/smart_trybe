from datetime import date
from uuid import UUID

import asyncpg
from fastapi import HTTPException, UploadFile

from app.domain.enums import ComplianceMode, ComplianceStatus, ComplianceType, UserRole
from app.modules.access.company import require_company_agent, require_company_read
from app.modules.compliance import repository as compliance_repo
from app.modules.documents.service import DocumentService
from app.modules.users import repository as users_repo
from app.modules.workflow.service import WorkflowService


def _ensure_company(row: asyncpg.Record | None) -> asyncpg.Record:
    if row is None:
        raise HTTPException(status_code=404, detail="Company not found")
    return row


class AgentService:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool
        self._workflows = WorkflowService(pool)
        self._documents = DocumentService(pool)

    async def list_assigned_companies(self, *, agent_user_id: UUID, role: UserRole) -> dict:
        if role not in (UserRole.AGENT, UserRole.ADMIN):
            raise HTTPException(status_code=403, detail="Agent access required")
        async with self._pool.acquire() as conn:
            if role == UserRole.ADMIN:
                from app.modules.cac.repository import list_all_companies

                rows = await list_all_companies(conn)
            else:
                rows = await users_repo.list_companies_for_agent(conn, agent_user_id)
            return {
                "companies": [
                    {
                        "id": str(r["id"]),
                        "name": r["name"],
                        "rc_number": r["rc_number"],
                        "tin": r["tin"],
                        "address": r["address"],
                        "owner_email": r["owner_email"],
                        "owner_name": r["owner_name"],
                        "assigned_at": r["assigned_at"].isoformat()
                        if r.get("assigned_at")
                        else None,
                    }
                    for r in rows
                ]
            }

    async def get_company_detail(
        self, *, company_id: UUID, user_id: UUID, role: UserRole
    ) -> dict:
        async with self._pool.acquire() as conn:
            company = _ensure_company(
                await require_company_read(conn, company_id, user_id, role)
            )
            progress = await self._workflows.get_company_progress(
                company_id=company_id, user_id=user_id, role=role
            )
            docs = await self._documents.list_company_documents(
                company_id=company_id,
                user_id=user_id,
                role=role,
            )
            registry = await compliance_repo.list_registry_for_company(conn, company_id)
            return {
                "company": {
                    "id": str(company["id"]),
                    "name": company["name"],
                    "rc_number": company["rc_number"],
                    "tin": company["tin"],
                    "address": company["address"],
                    "owner_email": company.get("owner_email"),
                    "owner_name": company.get("owner_name"),
                },
                "workflow_progress": progress,
                "documents": docs["documents"],
                "registry": [
                    {
                        "compliance_type": r["compliance_type"],
                        "status": r["status"],
                        "expiry_date": r["expiry_date"].isoformat()
                        if r["expiry_date"]
                        else None,
                        "last_updated": r["last_updated"].isoformat(),
                    }
                    for r in registry
                ],
            }

    async def upload_document(
        self,
        *,
        company_id: UUID,
        user_id: UUID,
        role: UserRole,
        compliance_type: ComplianceType,
        doc_type: str,
        file: UploadFile,
    ) -> UUID:
        return await self._workflows.upload_document(
            company_id=company_id,
            user_id=user_id,
            role=role,
            compliance_type=compliance_type,
            doc_type=doc_type,
            file=file,
        )

    async def update_workflow_status(
        self,
        *,
        company_id: UUID,
        user_id: UUID,
        role: UserRole,
        compliance_type: ComplianceType,
        mode: ComplianceMode,
        status: ComplianceStatus,
        current_step: int | None = None,
    ) -> dict:
        return await self._workflows.update_workflow_status(
            company_id=company_id,
            user_id=user_id,
            role=role,
            compliance_type=compliance_type,
            mode=mode,
            status=status,
            current_step=current_step,
        )

    async def complete_workflow(
        self,
        *,
        company_id: UUID,
        user_id: UUID,
        role: UserRole,
        compliance_type: ComplianceType,
        mode: ComplianceMode,
        expiry_date: date | None,
    ) -> dict:
        return await self._workflows.complete_workflow_as_agent(
            company_id=company_id,
            user_id=user_id,
            role=role,
            compliance_type=compliance_type,
            mode=mode,
            expiry_date=expiry_date,
        )

    async def add_output(
        self,
        *,
        company_id: UUID,
        user_id: UUID,
        role: UserRole,
        compliance_type: ComplianceType,
        mode: ComplianceMode,
        output_type: str,
        output_value: str,
    ) -> UUID:
        return await self._workflows.add_output(
            company_id=company_id,
            user_id=user_id,
            role=role,
            compliance_type=compliance_type,
            mode=mode,
            output_type=output_type,
            output_value=output_value,
        )

    async def update_registry(
        self,
        *,
        company_id: UUID,
        user_id: UUID,
        role: UserRole,
        compliance_type: ComplianceType,
        status: ComplianceStatus,
        expiry_date: date | None,
    ) -> dict:
        return await self._workflows.update_registry(
            company_id=company_id,
            user_id=user_id,
            role=role,
            compliance_type=compliance_type,
            status=status,
            expiry_date=expiry_date,
        )
