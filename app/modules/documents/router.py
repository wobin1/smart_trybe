from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field

from app.api.deps import (
    CurrentUser,
    db_pool,
    get_current_user,
    get_current_user_from_header_or_query,
)
from app.domain.enums import ComplianceType
from app.modules.documents.service import DocumentService

router = APIRouter(prefix="/companies", tags=["Company Documents"])


class ReuseDocumentBody(BaseModel):
    document_id: UUID
    compliance_type: ComplianceType = Field(
        ...,
        description="Compliance workflow to attach this document to (e.g. FIRS, ITF)",
    )


def get_document_service(pool: asyncpg.Pool = Depends(db_pool)) -> DocumentService:
    return DocumentService(pool)


@router.get("/{company_id}/documents")
async def list_company_documents(
    company_id: UUID,
    compliance_type: ComplianceType | None = Query(default=None),
    doc_type: str | None = Query(default=None),
    user: CurrentUser = Depends(get_current_user),
    svc: DocumentService = Depends(get_document_service),
):
    return await svc.list_company_documents(
        company_id=company_id,
        user_id=user.id,
        role=user.role,
        compliance_type=compliance_type.value if compliance_type else None,
        doc_type=doc_type,
    )


@router.get("/{company_id}/documents/{document_id}")
async def get_company_document(
    company_id: UUID,
    document_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    svc: DocumentService = Depends(get_document_service),
):
    return await svc.get_document(
        company_id=company_id,
        document_id=document_id,
        user_id=user.id,
        role=user.role,
    )


@router.get("/{company_id}/documents/{document_id}/file")
async def view_company_document_file(
    company_id: UUID,
    document_id: UUID,
    download: bool = Query(default=False),
    user: CurrentUser = Depends(get_current_user_from_header_or_query),
    svc: DocumentService = Depends(get_document_service),
):
    source, filename, media_type = await svc.open_document_file(
        company_id=company_id,
        document_id=document_id,
        user_id=user.id,
        role=user.role,
        download=download,
    )
    if isinstance(source, str):
        return RedirectResponse(source, status_code=307)

    disposition = "attachment" if download else "inline"
    return FileResponse(
        source,
        media_type=media_type,
        filename=filename,
        headers={"Content-Disposition": f'{disposition}; filename="{filename}"'},
    )


@router.post("/{company_id}/documents/reuse", status_code=201)
async def reuse_company_document(
    company_id: UUID,
    body: ReuseDocumentBody,
    user: CurrentUser = Depends(get_current_user),
    svc: DocumentService = Depends(get_document_service),
):
    return await svc.reuse_document(
        company_id=company_id,
        user_id=user.id,
        role=user.role,
        document_id=body.document_id,
        target_compliance_type=body.compliance_type.value,
    )
