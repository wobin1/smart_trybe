from uuid import UUID

import asyncpg
from fastapi import HTTPException

from app.modules.cac.repository import fetch_company_for_user
from app.modules.compliance import repository as compliance_repo


def _ensure_company(row: asyncpg.Record | None) -> asyncpg.Record:
    if row is None:
        raise HTTPException(status_code=404, detail="Company not found")
    return row


class DocumentService:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def list_company_documents(
        self,
        *,
        company_id: UUID,
        user_id: UUID,
        compliance_type: str | None = None,
        doc_type: str | None = None,
    ) -> dict:
        async with self._pool.acquire() as conn:
            _ensure_company(await fetch_company_for_user(conn, company_id, user_id))
            rows = await compliance_repo.list_documents_for_company(
                conn, company_id, compliance_type=compliance_type, doc_type=doc_type
            )
            return {
                "company_id": str(company_id),
                "documents": [
                    {
                        "id": str(r["id"]),
                        "compliance_type": r["compliance_type"],
                        "doc_type": r["doc_type"],
                        "storage_ref": r["s3_url"],
                        "uploaded_at": r["uploaded_at"].isoformat(),
                    }
                    for r in rows
                ],
            }

    async def reuse_document(
        self,
        *,
        company_id: UUID,
        user_id: UUID,
        document_id: UUID,
        target_compliance_type: str,
    ) -> dict:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                _ensure_company(await fetch_company_for_user(conn, company_id, user_id))
                source = await compliance_repo.fetch_document_for_company(
                    conn, document_id, company_id
                )
                if source is None:
                    raise HTTPException(status_code=404, detail="Document not found")

                if source["compliance_type"] == target_compliance_type:
                    return {
                        "id": str(source["id"]),
                        "compliance_type": source["compliance_type"],
                        "doc_type": source["doc_type"],
                        "reused": False,
                        "message": "Document already linked to this compliance type",
                    }

                exists = await compliance_repo.document_exists(
                    conn, company_id, target_compliance_type, source["doc_type"]
                )
                if exists:
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "message": "This document type is already uploaded for the target compliance",
                            "doc_type": source["doc_type"],
                            "compliance_type": target_compliance_type,
                        },
                    )

                new_id = await compliance_repo.insert_document(
                    conn,
                    company_id,
                    target_compliance_type,
                    source["doc_type"],
                    source["s3_url"],
                )
                return {
                    "id": str(new_id),
                    "source_document_id": str(document_id),
                    "compliance_type": target_compliance_type,
                    "doc_type": source["doc_type"],
                    "storage_ref": source["s3_url"],
                    "reused": True,
                }
