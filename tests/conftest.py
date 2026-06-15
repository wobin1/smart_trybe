"""Pytest configuration — runs before test module imports."""

import os
from pathlib import Path
from uuid import uuid4

import pytest

# Prefer explicit test DB URL when running integration tests.
if os.getenv("TEST_DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

os.environ.setdefault("JWT_SECRET_KEY", "pytest-jwt-secret-key-at-least-32-characters-long")
os.environ.setdefault("CLOUDINARY_CLOUD_NAME", "test-cloud")
os.environ.setdefault("CLOUDINARY_API_KEY", "test-key")
os.environ.setdefault("CLOUDINARY_API_SECRET", "test-secret")


@pytest.fixture(autouse=True)
def mock_cloudinary_upload(monkeypatch):
    """Avoid real Cloudinary calls during tests."""

    def fake_upload(*, data: bytes, filename: str, folder: str) -> str:
        safe_name = Path(filename or "upload").name
        stem = Path(safe_name).stem or "upload"
        public_id = f"{uuid4().hex}_{stem}"
        return f"https://res.cloudinary.com/test-cloud/auto/upload/v1/{folder}/{public_id}.{Path(safe_name).suffix.lstrip('.') or 'bin'}"

    monkeypatch.setattr("app.core.storage.upload_file", fake_upload)
