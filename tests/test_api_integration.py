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
    assert body["role"] == "CLIENT"

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
        files={"file": ("cert.pdf", b"%PDF-1.4 test certificate content", "application/pdf")},
        data={"doc_type": "CAC_CERTIFICATE"},
    )
    assert upload.status_code == 201
    doc_id = upload.json()["id"]

    library = client.get(f"/api/v1/companies/{cid}/documents", headers=headers)
    assert library.status_code == 200
    doc = next(d for d in library.json()["documents"] if d["id"] == doc_id)
    assert doc["filename"] == "cert.pdf"
    assert doc["content_type"] == "application/pdf"
    assert doc["view_url"].endswith(f"/documents/{doc_id}/file")

    view = client.get(
        f"/api/v1/companies/{cid}/documents/{doc_id}/file",
        headers=headers,
    )
    assert view.status_code == 200
    assert view.headers["content-type"].startswith("application/pdf")
    assert b"PDF" in view.content

    view_query = client.get(
        f"/api/v1/companies/{cid}/documents/{doc_id}/file",
        params={"access_token": token},
    )
    assert view_query.status_code == 200

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


async def _set_user_role(email: str, role: str) -> None:
    import asyncpg

    conn = await asyncpg.connect(os.environ["TEST_DATABASE_URL"])
    try:
        await conn.execute(
            """
            UPDATE users
            SET role = $1::user_role, is_admin = $2
            WHERE LOWER(email) = LOWER($3)
            """,
            role,
            role == "ADMIN",
            email,
        )
    finally:
        await conn.close()


def test_user_roles_and_agent_assignment(client: TestClient):
    import asyncio

    admin_email = f"admin_{uuid4().hex}@example.com"
    agent_email = f"agent_{uuid4().hex}@example.com"
    client_email = f"client_{uuid4().hex}@example.com"
    password = "securepassword123"

    admin_reg = client.post(
        "/api/v1/auth/register",
        json={"email": admin_email, "password": password, "full_name": "Admin"},
    )
    assert admin_reg.status_code == 201
    asyncio.run(_set_user_role(admin_email, "ADMIN"))
    admin_token = client.post(
        "/api/v1/auth/login",
        json={"email": admin_email, "password": password},
    ).json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    client.post(
        "/api/v1/auth/register",
        json={"email": agent_email, "password": password, "full_name": "Unassigned Agent"},
    )

    created_agent = client.post(
        "/api/v1/admin/users",
        headers=admin_headers,
        json={
            "email": f"agent2_{uuid4().hex}@example.com",
            "password": password,
            "full_name": "Agent Two",
            "role": "AGENT",
        },
    )
    assert created_agent.status_code == 201
    agent2_id = created_agent.json()["id"]

    client_reg = client.post(
        "/api/v1/auth/register",
        json={"email": client_email, "password": password, "full_name": "Client"},
    )
    assert client_reg.status_code == 201
    client_token = client_reg.json()["access_token"]
    client_headers = {"Authorization": f"Bearer {client_token}"}

    company = client.post(
        "/api/v1/cac/companies",
        headers=client_headers,
        json={"name": "Role Test Co", "address": "Lagos"},
    )
    assert company.status_code == 201
    cid = company.json()["id"]

    assign = client.post(
        f"/api/v1/admin/companies/{cid}/assign-agent",
        headers=admin_headers,
        json={"agent_user_id": agent2_id},
    )
    assert assign.status_code == 201

    asyncio.run(_set_user_role(agent_email, "AGENT"))
    agent_token = client.post(
        "/api/v1/auth/login",
        json={"email": agent_email, "password": password},
    ).json()["access_token"]
    agent_headers = {"Authorization": f"Bearer {agent_token}"}

    agent_companies = client.get("/api/v1/agent/companies", headers=agent_headers)
    assert agent_companies.status_code == 200

    unassigned_detail = client.get(
        f"/api/v1/agent/companies/{cid}", headers=agent_headers
    )
    assert unassigned_detail.status_code == 404

    agent2_token = client.post(
        "/api/v1/auth/login",
        json={"email": created_agent.json()["email"], "password": password},
    ).json()["access_token"]
    agent2_headers = {"Authorization": f"Bearer {agent2_token}"}

    assigned_detail = client.get(
        f"/api/v1/agent/companies/{cid}", headers=agent2_headers
    )
    assert assigned_detail.status_code == 200
    assert assigned_detail.json()["company"]["name"] == "Role Test Co"

    client_progress = client.get(
        f"/api/v1/workflow/companies/{cid}/progress", headers=client_headers
    )
    assert client_progress.status_code == 200
