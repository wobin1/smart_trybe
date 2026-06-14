from uuid import UUID

import asyncpg
from fastapi import HTTPException

from app.domain.enums import UserRole
from app.modules.cac.repository import fetch_company_by_id, list_all_companies
from app.modules.compliance import repository as compliance_repo
from app.modules.documents.service import DocumentService
from app.modules.workflow.service import WorkflowService


class AdminService:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool
        self._workflows = WorkflowService(pool)
        self._documents = DocumentService(pool)

    async def list_companies(self) -> dict:
        async with self._pool.acquire() as conn:
            rows = await list_all_companies(conn)
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
                        "created_at": r["created_at"].isoformat(),
                    }
                    for r in rows
                ]
            }

    async def get_company_detail(self, company_id: UUID) -> dict:
        async with self._pool.acquire() as conn:
            company = await fetch_company_by_id(conn, company_id)
            if company is None:
                raise HTTPException(status_code=404, detail="Company not found")

            progress = await self._workflows.get_company_progress_admin(company_id=company_id)
            docs = await self._documents.list_company_documents(
                company_id=company_id,
                user_id=company["user_id"],
                role=UserRole.ADMIN,
            )
            registry = await compliance_repo.list_registry_for_company(conn, company_id)

            return {
                "company": {
                    "id": str(company["id"]),
                    "name": company["name"],
                    "rc_number": company["rc_number"],
                    "tin": company["tin"],
                    "address": company["address"],
                    "owner_email": company["owner_email"],
                    "owner_name": company["owner_name"],
                    "created_at": company["created_at"].isoformat(),
                },
                "workflow_progress": progress,
                "documents": docs["documents"],
                "registry": [
                    {
                        "compliance_type": r["compliance_type"],
                        "status": r["status"],
                        "expiry_date": r["expiry_date"].isoformat() if r["expiry_date"] else None,
                        "last_updated": r["last_updated"].isoformat(),
                    }
                    for r in registry
                ],
            }

    async def get_company_workflow_progress(self, company_id: UUID) -> dict:
        return await self._workflows.get_company_progress_admin(company_id=company_id)
