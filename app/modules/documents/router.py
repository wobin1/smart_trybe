from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, db_pool, get_current_user
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
        compliance_type=compliance_type.value if compliance_type else None,
        doc_type=doc_type,
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
        document_id=body.document_id,
        target_compliance_type=body.compliance_type.value,
    )
