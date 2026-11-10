from decimal import Decimal
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, EmailStr, Field

from app.api.deps import CurrentUser, db_pool, get_admin_user
from app.domain.enums import ComplianceMode, ComplianceType, UserRole
from app.modules.admin.compliances import ComplianceAdminService
from app.modules.admin.service import AdminService
from app.modules.catalog.service import CatalogService
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
    assignment_reason: str | None = Field(default=None, max_length=1000)


class UpdateCatalogItemBody(BaseModel):
    base_price_ngn: Decimal | None = Field(default=None, ge=0)
    display_name: str | None = Field(default=None, min_length=1)
    description: str | None = None
    icon_key: str | None = Field(default=None, min_length=1)
    is_active: bool | None = None


class StepFieldBody(BaseModel):
    key: str | None = Field(default=None, max_length=60)
    label: str = Field(..., min_length=1, max_length=120)
    type: str = "text"
    required: bool = False
    options: list[str] | None = None
    description: str | None = Field(default=None, max_length=500)


class StepBody(BaseModel):
    step_name: str = Field(..., min_length=1, max_length=200)
    fields: list[StepFieldBody] = Field(default_factory=list)


class RequiredDocumentBody(BaseModel):
    doc_type: str | None = Field(default=None, max_length=60)
    label: str | None = Field(default=None, max_length=120)


class DependencyBody(BaseModel):
    compliance_type: ComplianceType
    mode: ComplianceMode


class CreateComplianceBody(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=120)
    code: str | None = Field(
        default=None,
        max_length=40,
        description="Short unique code, e.g. NAFDAC. Derived from the name when omitted.",
    )
    category_slug: str = Field(..., min_length=1)
    description: str | None = Field(default=None, max_length=1000)
    regulator_name: str | None = Field(default=None, max_length=200)
    base_price_ngn: Decimal = Field(default=Decimal("0"), ge=0)
    is_active: bool = False
    display_order: int | None = Field(default=None, ge=0)
    steps: list[StepBody] = Field(..., min_length=1)
    required_documents: list[RequiredDocumentBody] = Field(default_factory=list)
    depends_on: list[DependencyBody] = Field(default_factory=list)


class UpdateComplianceBody(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    category_slug: str | None = Field(default=None, min_length=1)
    description: str | None = Field(default=None, max_length=1000)
    regulator_name: str | None = Field(default=None, max_length=200)
    base_price_ngn: Decimal | None = Field(default=None, ge=0)
    is_active: bool | None = None
    display_order: int | None = Field(default=None, ge=0)
    steps: list[StepBody] | None = Field(default=None, min_length=1)
    required_documents: list[RequiredDocumentBody] | None = None
    depends_on: list[DependencyBody] | None = None


def get_compliance_admin_service(pool: asyncpg.Pool = Depends(db_pool)) -> ComplianceAdminService:
    return ComplianceAdminService(pool)


def get_admin_service(pool: asyncpg.Pool = Depends(db_pool)) -> AdminService:
    return AdminService(pool)


def get_user_management_service(pool: asyncpg.Pool = Depends(db_pool)) -> UserManagementService:
    return UserManagementService(pool)


def get_catalog_service(pool: asyncpg.Pool = Depends(db_pool)) -> CatalogService:
    return CatalogService(pool)


@router.get("/catalog/items")
async def list_catalog_items_admin(
    category: str | None = Query(default="all", description="Category slug or 'all'"),
    _admin: CurrentUser = Depends(get_admin_user),
    svc: CatalogService = Depends(get_catalog_service),
):
    return await svc.list_items_admin(category=category)


@router.get("/catalog/items/{compliance_type}/{mode}")
async def get_catalog_item_admin(
    compliance_type: ComplianceType,
    mode: ComplianceMode,
    _admin: CurrentUser = Depends(get_admin_user),
    svc: CatalogService = Depends(get_catalog_service),
):
    return await svc.get_item_admin(compliance_type.value, mode.value)


@router.patch("/catalog/items/{compliance_type}/{mode}")
async def update_catalog_item_admin(
    compliance_type: ComplianceType,
    mode: ComplianceMode,
    body: UpdateCatalogItemBody,
    _admin: CurrentUser = Depends(get_admin_user),
    svc: CatalogService = Depends(get_catalog_service),
    compliances: ComplianceAdminService = Depends(get_compliance_admin_service),
):
    result = await svc.update_item_admin(
        compliance_type.value,
        mode.value,
        base_price_ngn=body.base_price_ngn,
        display_name=body.display_name,
        description=body.description,
        icon_key=body.icon_key,
    )
    if body.is_active is not None:
        # Goes through the compliance service so the workflow template is switched
        # with the catalog row and a zero-priced compliance cannot be put on sale.
        await compliances.update(compliance_type.value, mode.value, is_active=body.is_active)
        result = await svc.get_item_admin(compliance_type.value, mode.value)
    return result


@router.get("/compliances/meta")
async def compliance_editor_meta(
    _admin: CurrentUser = Depends(get_admin_user),
    svc: ComplianceAdminService = Depends(get_compliance_admin_service),
):
    return await svc.meta()


@router.get("/compliances")
async def list_compliances_admin(
    _admin: CurrentUser = Depends(get_admin_user),
    svc: ComplianceAdminService = Depends(get_compliance_admin_service),
):
    """Every compliance (on or off) with its steps, documents and dependencies."""
    return await svc.list_all()


@router.post("/compliances", status_code=201)
async def create_compliance_admin(
    body: CreateComplianceBody,
    _admin: CurrentUser = Depends(get_admin_user),
    svc: ComplianceAdminService = Depends(get_compliance_admin_service),
):
    return await svc.create(
        display_name=body.display_name,
        code=body.code,
        category_slug=body.category_slug,
        description=body.description,
        regulator_name=body.regulator_name,
        base_price_ngn=body.base_price_ngn,
        is_active=body.is_active,
        display_order=body.display_order,
        steps=[s.model_dump() for s in body.steps],
        required_documents=[d.model_dump() for d in body.required_documents],
        depends_on=[d.model_dump(mode="json") for d in body.depends_on],
    )


@router.get("/compliances/{compliance_type}/{mode}")
async def get_compliance_admin(
    compliance_type: ComplianceType,
    mode: ComplianceMode,
    _admin: CurrentUser = Depends(get_admin_user),
    svc: ComplianceAdminService = Depends(get_compliance_admin_service),
):
    return await svc.get(compliance_type.value, mode.value)


@router.put("/compliances/{compliance_type}/{mode}")
async def update_compliance_admin(
    compliance_type: ComplianceType,
    mode: ComplianceMode,
    body: UpdateComplianceBody,
    _admin: CurrentUser = Depends(get_admin_user),
    svc: ComplianceAdminService = Depends(get_compliance_admin_service),
):
    """Update any part of a compliance. Omitted fields are left as they are.

    Step, field and document changes apply to filings started afterwards; filings
    already in progress keep the definition they started with.
    """
    sent = body.model_fields_set
    kwargs: dict = {}
    if "description" in sent:
        kwargs["description"] = body.description
    if "regulator_name" in sent:
        kwargs["regulator_name"] = body.regulator_name
    return await svc.update(
        compliance_type.value,
        mode.value,
        display_name=body.display_name,
        category_slug=body.category_slug,
        base_price_ngn=body.base_price_ngn,
        is_active=body.is_active,
        display_order=body.display_order,
        steps=[s.model_dump() for s in body.steps] if body.steps is not None else None,
        required_documents=(
            [d.model_dump() for d in body.required_documents]
            if body.required_documents is not None
            else None
        ),
        depends_on=(
            [d.model_dump(mode="json") for d in body.depends_on]
            if body.depends_on is not None
            else None
        ),
        **kwargs,
    )


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
        assignment_reason=body.assignment_reason,
    )


@router.delete("/companies/{company_id}/assign-agent/{agent_user_id}")
async def unassign_agent_from_company(
    company_id: UUID,
    agent_user_id: UUID,
    _admin: CurrentUser = Depends(get_admin_user),
    svc: UserManagementService = Depends(get_user_management_service),
):
    return await svc.unassign_agent(company_id=company_id, agent_user_id=agent_user_id)
