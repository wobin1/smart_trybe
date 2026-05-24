from datetime import date
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, db_pool, get_current_user
from app.domain.enums import ComplianceStatus
from app.modules.bpp_federal.service import BPPFederalService


router = APIRouter(prefix="/bpp/federal", tags=["BPP Federal"])


class BPPFederalRegistryBody(BaseModel):
    status: ComplianceStatus = Field(...)
    expiry_date: date | None = None


def get_bpp_federal_service(pool: asyncpg.Pool = Depends(db_pool)) -> BPPFederalService:
    return BPPFederalService(pool)


@router.get("/companies/{company_id}/registry")
async def get_bpp_federal_registry(
    company_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    svc: BPPFederalService = Depends(get_bpp_federal_service),
):
    row = await svc.get_registry(company_id, user.id)
    if row is None:
        return {
            "company_id": str(company_id),
            "compliance_type": "BPP_FEDERAL",
            "status": None,
        }
    return {
        "company_id": str(row["company_id"]),
        "compliance_type": row["compliance_type"],
        "status": row["status"],
        "expiry_date": row["expiry_date"].isoformat() if row["expiry_date"] else None,
        "last_updated": row["last_updated"].isoformat(),
    }


@router.put("/companies/{company_id}/registry")
async def put_bpp_federal_registry(
    company_id: UUID,
    body: BPPFederalRegistryBody,
    user: CurrentUser = Depends(get_current_user),
    svc: BPPFederalService = Depends(get_bpp_federal_service),
):
    await svc.upsert_registry(
        company_id, user.id, status=body.status, expiry_date=body.expiry_date
    )
    row = await svc.get_registry(company_id, user.id)
    assert row is not None
    return {
        "company_id": str(row["company_id"]),
        "compliance_type": row["compliance_type"],
        "status": row["status"],
        "expiry_date": row["expiry_date"].isoformat() if row["expiry_date"] else None,
        "last_updated": row["last_updated"].isoformat(),
    }


@router.post("/companies/{company_id}/documents", status_code=201)
async def upload_bpp_federal_document(
    company_id: UUID,
    doc_type: str = Form(...),
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
    svc: BPPFederalService = Depends(get_bpp_federal_service),
):
    doc_id = await svc.upload_document(company_id, user.id, doc_type=doc_type, file=file)
    return {"id": str(doc_id)}
