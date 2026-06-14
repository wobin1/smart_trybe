from datetime import date
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, db_pool, get_agent_user
from app.domain.enums import ComplianceMode, ComplianceStatus, ComplianceType
from app.modules.agent.service import AgentService

router = APIRouter(prefix="/agent", tags=["Compliance Agent"])


class UpdateWorkflowStatusBody(BaseModel):
    status: ComplianceStatus
    current_step: int | None = None


class CompleteWorkflowBody(BaseModel):
    expiry_date: date | None = None


class AddOutputBody(BaseModel):
    output_type: str = Field(..., min_length=1)
    output_value: str = Field(..., min_length=1)


class UpdateRegistryBody(BaseModel):
    status: ComplianceStatus
    expiry_date: date | None = None


def get_agent_service(pool: asyncpg.Pool = Depends(db_pool)) -> AgentService:
    return AgentService(pool)


@router.get("/companies")
async def list_assigned_companies(
    user: CurrentUser = Depends(get_agent_user),
    svc: AgentService = Depends(get_agent_service),
):
    return await svc.list_assigned_companies(agent_user_id=user.id, role=user.role)


@router.get("/companies/{company_id}")
async def get_assigned_company_detail(
    company_id: UUID,
    user: CurrentUser = Depends(get_agent_user),
    svc: AgentService = Depends(get_agent_service),
):
    return await svc.get_company_detail(company_id=company_id, user_id=user.id, role=user.role)


@router.get("/companies/{company_id}/progress")
async def get_assigned_company_progress(
    company_id: UUID,
    user: CurrentUser = Depends(get_agent_user),
    svc: AgentService = Depends(get_agent_service),
):
    detail = await svc.get_company_detail(
        company_id=company_id, user_id=user.id, role=user.role
    )
    return detail["workflow_progress"]


@router.post("/companies/{company_id}/workflows/{compliance_type}/documents", status_code=201)
async def upload_company_document(
    company_id: UUID,
    compliance_type: ComplianceType,
    doc_type: str = Form(...),
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_agent_user),
    svc: AgentService = Depends(get_agent_service),
):
    doc_id = await svc.upload_document(
        company_id=company_id,
        user_id=user.id,
        role=user.role,
        compliance_type=compliance_type,
        doc_type=doc_type,
        file=file,
    )
    return {"id": str(doc_id)}


@router.patch("/companies/{company_id}/workflows/{compliance_type}/{mode}/status")
async def update_workflow_status(
    company_id: UUID,
    compliance_type: ComplianceType,
    mode: ComplianceMode,
    body: UpdateWorkflowStatusBody,
    user: CurrentUser = Depends(get_agent_user),
    svc: AgentService = Depends(get_agent_service),
):
    return await svc.update_workflow_status(
        company_id=company_id,
        user_id=user.id,
        role=user.role,
        compliance_type=compliance_type,
        mode=mode,
        status=body.status,
        current_step=body.current_step,
    )


@router.post("/companies/{company_id}/workflows/{compliance_type}/{mode}/complete")
async def complete_workflow(
    company_id: UUID,
    compliance_type: ComplianceType,
    mode: ComplianceMode,
    body: CompleteWorkflowBody,
    user: CurrentUser = Depends(get_agent_user),
    svc: AgentService = Depends(get_agent_service),
):
    return await svc.complete_workflow(
        company_id=company_id,
        user_id=user.id,
        role=user.role,
        compliance_type=compliance_type,
        mode=mode,
        expiry_date=body.expiry_date,
    )


@router.post(
    "/companies/{company_id}/workflows/{compliance_type}/{mode}/outputs",
    status_code=201,
)
async def add_workflow_output(
    company_id: UUID,
    compliance_type: ComplianceType,
    mode: ComplianceMode,
    body: AddOutputBody,
    user: CurrentUser = Depends(get_agent_user),
    svc: AgentService = Depends(get_agent_service),
):
    output_id = await svc.add_output(
        company_id=company_id,
        user_id=user.id,
        role=user.role,
        compliance_type=compliance_type,
        mode=mode,
        output_type=body.output_type,
        output_value=body.output_value,
    )
    return {"id": str(output_id)}


@router.put("/companies/{company_id}/registry/{compliance_type}")
async def update_company_registry(
    company_id: UUID,
    compliance_type: ComplianceType,
    body: UpdateRegistryBody,
    user: CurrentUser = Depends(get_agent_user),
    svc: AgentService = Depends(get_agent_service),
):
    return await svc.update_registry(
        company_id=company_id,
        user_id=user.id,
        role=user.role,
        compliance_type=compliance_type,
        status=body.status,
        expiry_date=body.expiry_date,
    )
