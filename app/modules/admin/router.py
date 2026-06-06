from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, db_pool, get_admin_user
from app.modules.admin.service import AdminService

router = APIRouter(prefix="/admin", tags=["Admin"])


def get_admin_service(pool: asyncpg.Pool = Depends(db_pool)) -> AdminService:
    return AdminService(pool)


@router.get("/companies")
async def list_all_companies(
    _admin: CurrentUser = Depends(get_admin_user),
    svc: AdminService = Depends(get_admin_service),
):
    return await svc.list_companies()


@router.get("/companies/{company_id}")
async def get_company_detail(
    company_id: UUID,
    _admin: CurrentUser = Depends(get_admin_user),
    svc: AdminService = Depends(get_admin_service),
):
    return await svc.get_company_detail(company_id)


@router.get("/companies/{company_id}/workflow-progress")
async def get_company_workflow_progress_admin(
    company_id: UUID,
    _admin: CurrentUser = Depends(get_admin_user),
    svc: AdminService = Depends(get_admin_service),
):
    return await svc.get_company_workflow_progress(company_id)
