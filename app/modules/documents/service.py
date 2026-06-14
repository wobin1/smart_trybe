from pathlib import Path
from uuid import UUID

import asyncpg
from fastapi import HTTPException

from app.domain.enums import UserRole
from app.modules.access.company import require_company_client, require_company_read
from app.modules.compliance import repository as compliance_repo
from app.modules.documents.files import (
    build_file_path,
    build_public_url,
    filename_from_storage_ref,
    guess_media_type,
    resolve_upload_path,
)


def _ensure_company(row: asyncpg.Record | None) -> asyncpg.Record:
    if row is None:
        raise HTTPException(status_code=404, detail="Company not found")
    return row


def _format_document(company_id: UUID, row: asyncpg.Record) -> dict:
    filename = filename_from_storage_ref(row["s3_url"])
    view_path = build_file_path(str(company_id), str(row["id"]))
    download_path = build_file_path(str(company_id), str(row["id"]), download=True)
    return {
        "id": str(row["id"]),
        "compliance_type": row["compliance_type"],
        "doc_type": row["doc_type"],
        "filename": filename,
        "content_type": guess_media_type(filename),
        "storage_ref": row["s3_url"],
        "view_url": build_public_url(view_path),
        "download_url": build_public_url(download_path),
        "uploaded_at": row["uploaded_at"].isoformat(),
    }


class DocumentService:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def list_company_documents(
        self,
        *,
        company_id: UUID,
        user_id: UUID,
        role: UserRole,
        compliance_type: str | None = None,
        doc_type: str | None = None,
    ) -> dict:
        async with self._pool.acquire() as conn:
            _ensure_company(await require_company_read(conn, company_id, user_id, role))
            rows = await compliance_repo.list_documents_for_company(
                conn, company_id, compliance_type=compliance_type, doc_type=doc_type
            )
            return {
                "company_id": str(company_id),
                "documents": [_format_document(company_id, r) for r in rows],
            }

    async def get_document(
        self,
        *,
        company_id: UUID,
        document_id: UUID,
        user_id: UUID,
        role: UserRole,
    ) -> dict:
        async with self._pool.acquire() as conn:
            _ensure_company(await require_company_read(conn, company_id, user_id, role))
            row = await compliance_repo.fetch_document_for_company(conn, document_id, company_id)
            if row is None:
                raise HTTPException(status_code=404, detail="Document not found")
            return _format_document(company_id, row)

    async def open_document_file(
        self,
        *,
        company_id: UUID,
        document_id: UUID,
        user_id: UUID,
        role: UserRole,
    ) -> tuple[Path, str, str]:
        async with self._pool.acquire() as conn:
            _ensure_company(await require_company_read(conn, company_id, user_id, role))
            row = await compliance_repo.fetch_document_for_company(conn, document_id, company_id)
            if row is None:
                raise HTTPException(status_code=404, detail="Document not found")

        path = resolve_upload_path(row["s3_url"])
        filename = filename_from_storage_ref(row["s3_url"])
        media_type = guess_media_type(filename)
        return path, filename, media_type

    async def reuse_document(
        self,
        *,
        company_id: UUID,
        user_id: UUID,
        role: UserRole,
        document_id: UUID,
        target_compliance_type: str,
    ) -> dict:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                _ensure_company(await require_company_client(conn, company_id, user_id, role))
                source = await compliance_repo.fetch_document_for_company(
                    conn, document_id, company_id
                )
                if source is None:
                    raise HTTPException(status_code=404, detail="Document not found")

                if source["compliance_type"] == target_compliance_type:
                    payload = _format_document(company_id, source)
                    payload["reused"] = False
                    payload["message"] = "Document already linked to this compliance type"
                    return payload

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
                new_row = await compliance_repo.fetch_document_for_company(conn, new_id, company_id)
                assert new_row is not None
                payload = _format_document(company_id, new_row)
                payload["source_document_id"] = str(document_id)
                payload["reused"] = True
                return payload
