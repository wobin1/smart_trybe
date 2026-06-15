from pathlib import Path
from uuid import uuid4

import cloudinary
import cloudinary.uploader
from fastapi import HTTPException

from app.core.config import settings


def _configure_cloudinary() -> None:
    if not settings.cloudinary_configured:
        raise HTTPException(
            status_code=503,
            detail="Cloudinary is not configured. Set CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, and CLOUDINARY_API_SECRET.",
        )
    cloudinary.config(
        cloud_name=settings.cloudinary_cloud_name,
        api_key=settings.cloudinary_api_key,
        api_secret=settings.cloudinary_api_secret,
        secure=True,
    )


def upload_file(*, data: bytes, filename: str, folder: str) -> str:
    """Upload bytes to Cloudinary and return the secure URL."""
    _configure_cloudinary()
    safe_name = Path(filename or "upload").name
    stem = Path(safe_name).stem or "upload"
    public_id = f"{uuid4().hex}_{stem}"

    result = cloudinary.uploader.upload(
        data,
        folder=folder,
        public_id=public_id,
        resource_type="auto",
        use_filename=False,
        unique_filename=False,
        overwrite=False,
    )
    return result["secure_url"]


def build_upload_folder(*, company_id: str, compliance_type: str) -> str:
    return f"smart_trybe/{company_id}/{compliance_type.lower()}"
