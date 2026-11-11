"""Pytest configuration — runs before test module imports."""

import os
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

# Prefer explicit test DB URL when running integration tests.
if os.getenv("TEST_DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

os.environ.setdefault("JWT_SECRET_KEY", "pytest-jwt-secret-key-at-least-32-characters-long")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-google-client-id.apps.googleusercontent.com")
os.environ.setdefault("CLOUDINARY_CLOUD_NAME", "test-cloud")
os.environ.setdefault("CLOUDINARY_API_KEY", "test-key")
os.environ.setdefault("CLOUDINARY_API_SECRET", "test-secret")
os.environ["PAYMENT_DEV_MODE"] = os.environ.get("PAYMENT_DEV_MODE", "true")
os.environ.setdefault("PAYSTACK_SECRET_KEY", "")


async def _reactivate_firs_registration() -> None:
    """Switch the retired FIRS/NEW application back on in the test database.

    FIRS new registration was retired from the client catalog (each agency now has
    one application), but many tests use it as their sample multi-step workflow.
    Those tests are about workflow mechanics, not about which applications are on
    sale, so the test database keeps it active. Retirement itself is covered by
    tests/test_admin_compliances.py using ITF/RENEWAL.
    """
    import asyncpg

    conn = await asyncpg.connect(os.environ["TEST_DATABASE_URL"])
    try:
        for table in ("compliance_catalog", "workflow_templates"):
            await conn.execute(
                f"UPDATE {table} SET is_active = TRUE "
                "WHERE compliance_type = 'FIRS' AND mode = 'NEW'::compliance_mode"
            )
    finally:
        await conn.close()


@pytest.fixture(scope="module")
def client() -> TestClient:
    import asyncio

    from app.main import app

    with TestClient(app) as c:
        if os.getenv("TEST_DATABASE_URL"):
            asyncio.run(_reactivate_firs_registration())
        yield c


@pytest.fixture(autouse=True)
def mock_cloudinary_upload(monkeypatch):
    """Avoid real Cloudinary calls during tests."""

    def fake_upload(*, data: bytes, filename: str, folder: str) -> str:
        safe_name = Path(filename or "upload").name
        stem = Path(safe_name).stem or "upload"
        public_id = f"{uuid4().hex}_{stem}"
        return f"https://res.cloudinary.com/test-cloud/auto/upload/v1/{folder}/{public_id}.{Path(safe_name).suffix.lstrip('.') or 'bin'}"

    monkeypatch.setattr("app.core.storage.upload_file", fake_upload)
