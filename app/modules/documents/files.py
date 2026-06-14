import mimetypes
from pathlib import Path

from fastapi import HTTPException

from app.core.config import settings


def upload_root() -> Path:
    return Path(settings.upload_dir).resolve()


def filename_from_storage_ref(storage_ref: str) -> str:
    name = Path(storage_ref).name
    if "_" in name:
        return name.split("_", 1)[1]
    return name


def guess_media_type(filename: str) -> str:
    media_type, _ = mimetypes.guess_type(filename)
    return media_type or "application/octet-stream"


def resolve_upload_path(storage_ref: str) -> Path:
    path = Path(storage_ref).resolve()
    root = upload_root()
    if not str(path).startswith(str(root)):
        raise HTTPException(status_code=404, detail="File not found")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return path


def build_file_path(company_id: str, document_id: str, *, download: bool = False) -> str:
    suffix = "?download=true" if download else ""
    return f"/api/v1/companies/{company_id}/documents/{document_id}/file{suffix}"


def build_public_url(relative_path: str) -> str:
    base = settings.public_api_base_url.strip().rstrip("/")
    if not base:
        return relative_path
    return f"{base}{relative_path}"
