from datetime import date
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, db_pool, get_current_user
from app.domain.enums import ComplianceMode, ComplianceType
from app.modules.workflow.service import WorkflowService

router = APIRouter(prefix="/workflow", tags=["Compliance Workflow"])


class CompleteStepBody(BaseModel):
    step_name: str = Field(..., min_length=1)


class AddOutputBody(BaseModel):
    output_type: str = Field(..., min_length=1)
    output_value: str = Field(..., min_length=1)


class SubmitBody(BaseModel):
    expiry_date: date | None = None


def get_workflow_service(pool: asyncpg.Pool = Depends(db_pool)) -> WorkflowService:
    return WorkflowService(pool)


@router.post("/{compliance_type}/{mode}/companies/{company_id}/start")
async def start_workflow(
    compliance_type: ComplianceType,
    mode: ComplianceMode,
    company_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    svc: WorkflowService = Depends(get_workflow_service),
):
    row = await svc.start(
        company_id=company_id,
        user_id=user.id,
        compliance_type=compliance_type,
        mode=mode,
    )
    return {
        "id": str(row["id"]),
        "company_id": str(row["company_id"]),
        "compliance_type": row["compliance_type"],
        "mode": row["mode"],
        "status": row["status"],
        "current_step": row["current_step"],
        "total_steps": row["total_steps"],
    }


@router.post("/{compliance_type}/{mode}/companies/{company_id}/steps/{step_number}/complete")
async def complete_step(
    compliance_type: ComplianceType,
    mode: ComplianceMode,
    company_id: UUID,
    step_number: int,
    body: CompleteStepBody,
    user: CurrentUser = Depends(get_current_user),
    svc: WorkflowService = Depends(get_workflow_service),
):
    row = await svc.complete_step(
        company_id=company_id,
        user_id=user.id,
        compliance_type=compliance_type,
        mode=mode,
        step_number=step_number,
        step_name=body.step_name,
    )
    return {
        "id": str(row["id"]),
        "status": row["status"],
        "current_step": row["current_step"],
        "total_steps": row["total_steps"],
    }


@router.post("/{compliance_type}/companies/{company_id}/documents", status_code=201)
async def upload_workflow_document(
    compliance_type: ComplianceType,
    company_id: UUID,
    doc_type: str = Form(...),
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
    svc: WorkflowService = Depends(get_workflow_service),
):
    doc_id = await svc.upload_document(
        company_id=company_id,
        user_id=user.id,
        compliance_type=compliance_type,
        doc_type=doc_type,
        file=file,
    )
    return {"id": str(doc_id)}


@router.post("/{compliance_type}/{mode}/companies/{company_id}/outputs", status_code=201)
async def add_workflow_output(
    compliance_type: ComplianceType,
    mode: ComplianceMode,
    company_id: UUID,
    body: AddOutputBody,
    user: CurrentUser = Depends(get_current_user),
    svc: WorkflowService = Depends(get_workflow_service),
):
    output_id = await svc.add_output(
        company_id=company_id,
        user_id=user.id,
        compliance_type=compliance_type,
        mode=mode,
        output_type=body.output_type,
        output_value=body.output_value,
    )
    return {"id": str(output_id)}


@router.get("/{compliance_type}/{mode}/companies/{company_id}/status")
async def get_workflow_status(
    compliance_type: ComplianceType,
    mode: ComplianceMode,
    company_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    svc: WorkflowService = Depends(get_workflow_service),
):
    return await svc.get_status(
        company_id=company_id,
        user_id=user.id,
        compliance_type=compliance_type,
        mode=mode,
    )


@router.post("/{compliance_type}/{mode}/companies/{company_id}/submit")
async def submit_workflow(
    compliance_type: ComplianceType,
    mode: ComplianceMode,
    company_id: UUID,
    body: SubmitBody,
    user: CurrentUser = Depends(get_current_user),
    svc: WorkflowService = Depends(get_workflow_service),
):
    return await svc.submit(
        company_id=company_id,
        user_id=user.id,
        compliance_type=compliance_type,
        mode=mode,
        expiry_date=body.expiry_date,
    )
