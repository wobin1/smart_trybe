"""API integration tests — require PostgreSQL and TEST_DATABASE_URL."""

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient


pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="Set TEST_DATABASE_URL to run integration tests",
)


@pytest.fixture(scope="module")
def client() -> TestClient:
    from app.main import app

    with TestClient(app) as c:
        yield c


def test_health(client: TestClient):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_auth_flow(client: TestClient):
    email = f"user_{uuid4().hex}@example.com"
    password = "securepassword123"

    reg = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": "Test User"},
    )
    assert reg.status_code == 201
    token = reg.json()["access_token"]
    assert token

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    body = me.json()
    assert body["email"] == email.lower()
    assert body["full_name"] == "Test User"

    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200
    assert login.json()["access_token"]


def test_protected_route_without_token_returns_401(client: TestClient):
    r = client.get("/api/v1/cac/companies")
    assert r.status_code == 403 or r.status_code == 401


def test_cac_company_requires_auth(client: TestClient):
    email = f"cac_{uuid4().hex}@example.com"
    password = "securepassword123"
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password},
    )
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    create = client.post(
        "/api/v1/cac/companies",
        headers=headers,
        json={
            "name": "Acme Ltd",
            "rc_number": "RC123",
            "tin": None,
            "address": "Lagos",
        },
    )
    assert create.status_code == 201
    cid = create.json()["id"]

    listed = client.get("/api/v1/cac/companies", headers=headers)
    assert listed.status_code == 200
    assert any(row["id"] == cid for row in listed.json())

    patch = client.patch(
        f"/api/v1/cac/companies/{cid}",
        headers=headers,
        json={"name": "Acme Ltd (updated)", "address": "Abuja"},
    )
    assert patch.status_code == 200
    assert patch.json()["name"] == "Acme Ltd (updated)"
    assert patch.json()["address"] == "Abuja"

    got = client.get(f"/api/v1/cac/companies/{cid}", headers=headers)
    assert got.status_code == 200
    assert got.json()["name"] == "Acme Ltd (updated)"
    assert got.json()["address"] == "Abuja"

    empty_patch = client.patch(f"/api/v1/cac/companies/{cid}", headers=headers, json={})
    assert empty_patch.status_code == 400

    progress = client.get(f"/api/v1/workflow/companies/{cid}/progress", headers=headers)
    assert progress.status_code == 200
    body = progress.json()
    assert body["company_id"] == cid
    assert len(body["workflows"]) > 0

    cac_new = next(w for w in body["workflows"] if w["compliance_type"] == "CAC" and w["mode"] == "NEW")
    assert cac_new["started"] is False
    assert cac_new["status"] == "NOT_STARTED"

    start = client.post(f"/api/v1/workflow/CAC/NEW/companies/{cid}/start", headers=headers)
    assert start.status_code == 200

    progress2 = client.get(f"/api/v1/workflow/companies/{cid}/progress", headers=headers)
    cac_new2 = next(
        w for w in progress2.json()["workflows"] if w["compliance_type"] == "CAC" and w["mode"] == "NEW"
    )
    assert cac_new2["started"] is True
    assert cac_new2["status"] == "PENDING"
    assert cac_new2["total_steps"] == 8

    # Upload under CAC, list library, reuse for FIRS workflow
    upload = client.post(
        f"/api/v1/cac/companies/{cid}/documents",
        headers=headers,
        files={"file": ("cert.pdf", b"test certificate content", "application/pdf")},
        data={"doc_type": "CAC_CERTIFICATE"},
    )
    assert upload.status_code == 201
    doc_id = upload.json()["id"]

    library = client.get(f"/api/v1/companies/{cid}/documents", headers=headers)
    assert library.status_code == 200
    assert any(d["id"] == doc_id for d in library.json()["documents"])

    reuse = client.post(
        f"/api/v1/companies/{cid}/documents/reuse",
        headers=headers,
        json={"document_id": doc_id, "compliance_type": "FIRS"},
    )
    assert reuse.status_code == 201
    assert reuse.json()["reused"] is True
    assert reuse.json()["doc_type"] == "CAC_CERTIFICATE"

    firs_docs = client.get(
        f"/api/v1/companies/{cid}/documents?compliance_type=FIRS",
        headers=headers,
    )
    assert any(d["doc_type"] == "CAC_CERTIFICATE" for d in firs_docs.json()["documents"])

    start_cac = client.post(f"/api/v1/workflow/CAC/NEW/companies/{cid}/start", headers=headers)
    assert start_cac.status_code == 200

    draft = client.put(
        f"/api/v1/workflow/CAC/NEW/companies/{cid}/steps/1/draft",
        headers=headers,
        json={
            "data": {
                "proposed_name_1": "Acme Alpha Ltd",
                "proposed_name_2": "Acme Beta Ltd",
            }
        },
    )
    assert draft.status_code == 200
    assert draft.json()["is_draft"] is True
    assert draft.json()["step_data"]["proposed_name_1"] == "Acme Alpha Ltd"

    complete1 = client.post(
        f"/api/v1/workflow/CAC/NEW/companies/{cid}/steps/1/complete",
        headers=headers,
        json={
            "step_name": "Choose 2 proposed company names",
            "data": {
                "proposed_name_1": "Acme Alpha Ltd",
                "proposed_name_2": "Acme Beta Ltd",
            },
        },
    )
    assert complete1.status_code == 200

    status = client.get(f"/api/v1/workflow/CAC/NEW/companies/{cid}/status", headers=headers)
    step1 = next(s for s in status.json()["steps"] if s["step_number"] == 1)
    assert step1["is_completed"] is True
    assert step1["step_data"]["proposed_name_1"] == "Acme Alpha Ltd"
