from datetime import date
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, db_pool, get_current_user
from app.domain.enums import ComplianceStatus
from app.modules.cac.service import CACService


router = APIRouter(prefix="/cac", tags=["CAC"])


class CompanyCreate(BaseModel):
    name: str = Field(..., min_length=1)
    rc_number: str | None = None
    tin: str | None = None
    address: str | None = None


class CompanyUpdate(BaseModel):
    name: str | None = None
    rc_number: str | None = None
    tin: str | None = None
    address: str | None = None


class CACRegistryUpdate(BaseModel):
    status: ComplianceStatus
    expiry_date: date | None = None


def get_cac_service(pool: asyncpg.Pool = Depends(db_pool)) -> CACService:
    return CACService(pool)


@router.post("/companies", status_code=201)
async def create_company(
    body: CompanyCreate,
    user: CurrentUser = Depends(get_current_user),
    svc: CACService = Depends(get_cac_service),
):
    company_id = await svc.create_company(
        name=body.name,
        rc_number=body.rc_number,
        tin=body.tin,
        address=body.address,
        user_id=user.id,
    )
    return {"id": str(company_id)}


@router.get("/companies")
async def list_companies(
    user: CurrentUser = Depends(get_current_user),
    svc: CACService = Depends(get_cac_service),
):
    rows = await svc.list_companies(user.id)
    return [
        {
            "id": str(r["id"]),
            "name": r["name"],
            "rc_number": r["rc_number"],
            "tin": r["tin"],
            "address": r["address"],
            "user_id": str(r["user_id"]),
            "created_at": r["created_at"].isoformat(),
        }
        for r in rows
    ]


@router.get("/companies/{company_id}")
async def get_company(
    company_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    svc: CACService = Depends(get_cac_service),
):
    r = await svc.get_company(company_id, user.id)
    return {
        "id": str(r["id"]),
        "name": r["name"],
        "rc_number": r["rc_number"],
        "tin": r["tin"],
        "address": r["address"],
        "user_id": str(r["user_id"]),
        "created_at": r["created_at"].isoformat(),
    }


@router.patch("/companies/{company_id}")
async def patch_company(
    company_id: UUID,
    body: CompanyUpdate,
    user: CurrentUser = Depends(get_current_user),
    svc: CACService = Depends(get_cac_service),
):
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(
            status_code=400,
            detail="Provide at least one field to update: name, rc_number, tin, address",
        )
    r = await svc.update_company(company_id, user.id, updates)
    return {
        "id": str(r["id"]),
        "name": r["name"],
        "rc_number": r["rc_number"],
        "tin": r["tin"],
        "address": r["address"],
        "user_id": str(r["user_id"]),
        "created_at": r["created_at"].isoformat(),
    }


@router.get("/companies/{company_id}/registry")
async def get_cac_registry(
    company_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    svc: CACService = Depends(get_cac_service),
):
    row = await svc.get_cac_registry(company_id, user.id)
    if row is None:
        return {"company_id": str(company_id), "compliance_type": "CAC", "status": None}
    return {
        "company_id": str(row["company_id"]),
        "compliance_type": row["compliance_type"],
        "status": row["status"],
        "expiry_date": row["expiry_date"].isoformat() if row["expiry_date"] else None,
        "last_updated": row["last_updated"].isoformat(),
    }


@router.put("/companies/{company_id}/registry")
async def put_cac_registry(
    company_id: UUID,
    body: CACRegistryUpdate,
    user: CurrentUser = Depends(get_current_user),
    svc: CACService = Depends(get_cac_service),
):
    await svc.update_cac_registry(
        company_id, user.id, status=body.status, expiry_date=body.expiry_date
    )
    row = await svc.get_cac_registry(company_id, user.id)
    assert row is not None
    return {
        "company_id": str(row["company_id"]),
        "compliance_type": row["compliance_type"],
        "status": row["status"],
        "expiry_date": row["expiry_date"].isoformat() if row["expiry_date"] else None,
        "last_updated": row["last_updated"].isoformat(),
    }


@router.post("/companies/{company_id}/documents", status_code=201)
async def upload_cac_document(
    company_id: UUID,
    doc_type: str = Form(...),
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
    svc: CACService = Depends(get_cac_service),
):
    doc_id = await svc.upload_document(company_id, user.id, doc_type=doc_type, file=file)
    return {"id": str(doc_id)}
