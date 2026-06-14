from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, EmailStr, Field

from app.api.deps import CurrentUser, db_pool, get_admin_user
from app.domain.enums import UserRole
from app.modules.admin.service import AdminService
from app.modules.users.service import UserManagementService

router = APIRouter(prefix="/admin", tags=["Admin"])


class CreateUserBody(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    full_name: str | None = None
    role: UserRole = Field(..., description="AGENT or ADMIN only")


class UpdateUserBody(BaseModel):
    full_name: str | None = None
    is_active: bool | None = None
    role: UserRole | None = None


class AssignAgentBody(BaseModel):
    agent_user_id: UUID


def get_admin_service(pool: asyncpg.Pool = Depends(db_pool)) -> AdminService:
    return AdminService(pool)


def get_user_management_service(pool: asyncpg.Pool = Depends(db_pool)) -> UserManagementService:
    return UserManagementService(pool)


@router.get("/users")
async def list_users(
    role: UserRole | None = Query(default=None),
    _admin: CurrentUser = Depends(get_admin_user),
    svc: UserManagementService = Depends(get_user_management_service),
):
    return await svc.list_users(role=role)


@router.post("/users", status_code=201)
async def create_user(
    body: CreateUserBody,
    _admin: CurrentUser = Depends(get_admin_user),
    svc: UserManagementService = Depends(get_user_management_service),
):
    if body.role == UserRole.CLIENT:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="Clients must self-register")
    return await svc.create_user(
        email=str(body.email),
        password=body.password,
        full_name=body.full_name,
        role=body.role,
    )


@router.patch("/users/{user_id}")
async def update_user(
    user_id: UUID,
    body: UpdateUserBody,
    _admin: CurrentUser = Depends(get_admin_user),
    svc: UserManagementService = Depends(get_user_management_service),
):
    return await svc.update_user(
        user_id,
        full_name=body.full_name,
        is_active=body.is_active,
        role=body.role,
    )


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


@router.get("/companies/{company_id}/assignments")
async def list_company_agent_assignments(
    company_id: UUID,
    _admin: CurrentUser = Depends(get_admin_user),
    svc: UserManagementService = Depends(get_user_management_service),
):
    return await svc.list_company_assignments(company_id)


@router.post("/companies/{company_id}/assign-agent", status_code=201)
async def assign_agent_to_company(
    company_id: UUID,
    body: AssignAgentBody,
    admin: CurrentUser = Depends(get_admin_user),
    svc: UserManagementService = Depends(get_user_management_service),
):
    return await svc.assign_agent(
        company_id=company_id,
        agent_user_id=body.agent_user_id,
        assigned_by=admin.id,
    )


@router.delete("/companies/{company_id}/assign-agent/{agent_user_id}")
async def unassign_agent_from_company(
    company_id: UUID,
    agent_user_id: UUID,
    _admin: CurrentUser = Depends(get_admin_user),
    svc: UserManagementService = Depends(get_user_management_service),
):
    return await svc.unassign_agent(company_id=company_id, agent_user_id=agent_user_id)
