"""Validation and storage of uploaded documents.

Every document upload endpoint goes through `store_upload`, so the limits below
hold no matter which screen or API client the file comes from. The browser
applies the same rules first for a faster error, but it is not trusted.
"""

from pathlib import Path

from fastapi import HTTPException, UploadFile

from app.core import storage

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_UPLOAD_LABEL = "10 MB"

ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".heic", ".doc", ".docx"}

# Statements are read page by page by the auditor, so photos and Word files are not accepted.
PDF_ONLY_DOC_TYPES = {"BANK_STATEMENTS"}


def is_pdf_only(doc_type: str) -> bool:
    return doc_type.strip().upper() in PDF_ONLY_DOC_TYPES


async def read_validated_upload(file: UploadFile, doc_type: str) -> tuple[str, bytes]:
    """Return (safe filename, bytes) or raise 400/413/415 with a message for the user."""
    safe_name = Path(file.filename or "upload").name
    extension = Path(safe_name).suffix.lower()

    if is_pdf_only(doc_type) and extension != ".pdf":
        raise HTTPException(status_code=415, detail="Bank statements must be uploaded as a PDF")
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail="Unsupported file type. Upload a PDF, JPG, PNG, HEIC or Word document.",
        )

    # Read one byte past the limit so an oversized file is detected without
    # pulling an arbitrarily large body into memory.
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File is too large. The limit is {MAX_UPLOAD_LABEL}.",
        )
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded file is empty")
    # A renamed image is not a PDF: check the signature, not just the extension.
    if extension == ".pdf" and b"%PDF-" not in data[:1024]:
        raise HTTPException(status_code=415, detail="This file is not a valid PDF")

    return safe_name, data


async def store_upload(
    file: UploadFile, *, doc_type: str, company_id: str, compliance_type: str
) -> str:
    """Validate an uploaded document, store it, and return its storage URL."""
    safe_name, data = await read_validated_upload(file, doc_type)
    folder = storage.build_upload_folder(company_id=company_id, compliance_type=compliance_type)
    return storage.upload_file(data=data, filename=safe_name, folder=folder)
