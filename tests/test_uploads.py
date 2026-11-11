"""Upload limits: 10 MB, supported types only, bank statements as PDF only."""

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.uploads import MAX_UPLOAD_BYTES

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="Set TEST_DATABASE_URL to run integration tests",
)

PDF = b"%PDF-1.4\n" + b"0" * 2048
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 2048


@pytest.fixture(scope="module")
def uploader(client: TestClient):
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": f"upl_{uuid4().hex}@example.com", "password": "securepassword123"},
    )
    headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    company = client.post(
        "/api/v1/cac/companies",
        headers=headers,
        json={"name": "Upload Ltd", "rc_number": "RC777", "registration_type": "EXISTING"},
    )
    company_id = company.json()["id"]

    def upload(doc_type: str, filename: str, data: bytes, *, compliance: str = "ACCOUNT_AUDITING"):
        return client.post(
            f"/api/v1/workflow/{compliance}/companies/{company_id}/documents",
            headers=headers,
            files={"file": (filename, data, "application/octet-stream")},
            data={"doc_type": doc_type},
        )

    upload.company_id = company_id
    upload.headers = headers
    return upload


def test_bank_statements_accept_pdf_only(uploader):
    assert uploader("BANK_STATEMENTS", "statement.pdf", PDF).status_code == 201

    image = uploader("BANK_STATEMENTS", "statement.png", PNG)
    assert image.status_code == 415
    assert "PDF" in image.json()["detail"]

    assert uploader("BANK_STATEMENTS", "statement.docx", b"PK" + b"0" * 2048).status_code == 415
    # An image renamed to .pdf is still not a PDF.
    assert uploader("BANK_STATEMENTS", "statement.pdf", PNG).status_code == 415


def test_other_documents_accept_images_but_not_arbitrary_files(uploader):
    assert uploader("TRANSACTION_RECORDS", "records.png", PNG).status_code == 201
    assert uploader("TRANSACTION_RECORDS", "records.exe", b"MZ" + b"0" * 2048).status_code == 415
    assert uploader("TRANSACTION_RECORDS", "records.pdf", b"").status_code == 400


def test_upload_limit_is_10_mb(uploader):
    at_limit = b"%PDF-1.4\n" + b"0" * (MAX_UPLOAD_BYTES - 9)
    assert len(at_limit) == MAX_UPLOAD_BYTES
    assert uploader("TRANSACTION_RECORDS", "big.pdf", at_limit).status_code == 201

    over = uploader("TRANSACTION_RECORDS", "big.pdf", at_limit + b"0")
    assert over.status_code == 413
    assert "10 MB" in over.json()["detail"]


def test_limits_apply_to_the_cac_upload_endpoint_too(client: TestClient, uploader):
    response = client.post(
        f"/api/v1/cac/companies/{uploader.company_id}/documents",
        headers=uploader.headers,
        files={"file": ("cert.exe", b"MZ" + b"0" * 2048, "application/octet-stream")},
        data={"doc_type": "CAC_CERTIFICATE"},
    )
    assert response.status_code == 415
