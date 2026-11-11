"""Agent workflow mutation and dashboard tests."""

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient


pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="Set TEST_DATABASE_URL to run integration tests",
)


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


async def _seed_bpp_prerequisites(company_id: str) -> None:
    """Directly mark FIRS/PENCOM/ITF/NSITF as satisfied, bypassing their own onboarding
    flows — only BPP's cross-compliance gate is under test here."""
    import asyncpg
    from datetime import date, timedelta
    from uuid import UUID

    conn = await asyncpg.connect(os.environ["TEST_DATABASE_URL"])
    try:
        future = date.today() + timedelta(days=365)
        cid = UUID(company_id)
        for ct in ("FIRS", "PENCOM", "ITF", "NSITF"):
            await conn.execute(
                """
                INSERT INTO compliance_registry (company_id, compliance_type, status, expiry_date, last_updated)
                VALUES ($1, $2::compliance_type, 'COMPLETED'::compliance_status, $3, NOW())
                ON CONFLICT (company_id, compliance_type)
                DO UPDATE SET status = 'COMPLETED'::compliance_status,
                              expiry_date = EXCLUDED.expiry_date,
                              last_updated = NOW()
                """,
                cid,
                ct,
                future,
            )
            await conn.execute(
                """
                INSERT INTO compliance_workflows
                    (company_id, compliance_type, mode, status, total_steps, current_step)
                VALUES ($1, $2::compliance_type, 'RENEWAL'::compliance_mode,
                        'COMPLETED'::compliance_status, 1, 1)
                ON CONFLICT (company_id, compliance_type, mode)
                DO UPDATE SET status = 'COMPLETED'::compliance_status
                """,
                cid,
                ct,
            )
    finally:
        await conn.close()


def _register(client: TestClient, prefix: str) -> tuple[str, dict, str]:
    email = f"{prefix}_{uuid4().hex}@example.com"
    password = "securepassword123"
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": prefix.title()},
    )
    assert reg.status_code == 201
    token = reg.json()["access_token"]
    return email, {"Authorization": f"Bearer {token}"}, password


def test_agent_workflow_complete_and_dashboard(client: TestClient):
    import asyncio

    admin_email, _, admin_password = _register(client, "adm")
    asyncio.run(_set_user_role(admin_email, "ADMIN"))
    admin_token = client.post(
        "/api/v1/auth/login",
        json={"email": admin_email, "password": admin_password},
    ).json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    agent_resp = client.post(
        "/api/v1/admin/users",
        headers=admin_headers,
        json={
            "email": f"agent_{uuid4().hex}@example.com",
            "password": "securepassword123",
            "full_name": "Workflow Agent",
            "role": "AGENT",
        },
    )
    assert agent_resp.status_code == 201
    agent_id = agent_resp.json()["id"]
    agent_email = agent_resp.json()["email"]

    _, client_headers, _ = _register(client, "cli")
    company = client.post(
        "/api/v1/cac/companies",
        headers=client_headers,
        json={"name": "Agent Flow Co", "address": "Lagos"},
    )
    company_id = company.json()["id"]

    client.post(
        f"/api/v1/workflow/CAC/NEW/companies/{company_id}/start",
        headers=client_headers,
    )

    assign = client.post(
        f"/api/v1/admin/companies/{company_id}/assign-agent",
        headers=admin_headers,
        json={"agent_user_id": agent_id},
    )
    assert assign.status_code == 201

    agent_token = client.post(
        "/api/v1/auth/login",
        json={"email": agent_email, "password": "securepassword123"},
    ).json()["access_token"]
    agent_headers = {"Authorization": f"Bearer {agent_token}"}

    agent_dash = client.get("/api/v1/dashboard", headers=agent_headers)
    assert agent_dash.status_code == 200
    assert agent_dash.json()["role"] == "AGENT"
    assert agent_dash.json()["summary"]["assigned_companies"] == 1

    admin_dash = client.get("/api/v1/dashboard", headers=admin_headers)
    assert admin_dash.status_code == 200
    assert admin_dash.json()["role"] == "ADMIN"
    assert admin_dash.json()["summary"]["companies"] >= 1

    status = client.patch(
        f"/api/v1/agent/companies/{company_id}/workflows/CAC/NEW/status",
        headers=agent_headers,
        json={"status": "IN_REVIEW", "current_step": 1},
    )
    assert status.status_code == 200

    output = client.post(
        f"/api/v1/agent/companies/{company_id}/workflows/CAC/NEW/outputs",
        headers=agent_headers,
        json={"output_type": "RC_NUMBER", "output_value": "RC123456"},
    )
    assert output.status_code == 201

    complete = client.post(
        f"/api/v1/agent/companies/{company_id}/workflows/CAC/NEW/complete",
        headers=agent_headers,
        json={"expiry_date": "2027-12-31"},
    )
    assert complete.status_code == 200
    assert complete.json()["status"] == "COMPLETED"

    registry = client.put(
        f"/api/v1/agent/companies/{company_id}/registry/CAC",
        headers=agent_headers,
        json={"status": "COMPLETED", "expiry_date": "2027-12-31"},
    )
    assert registry.status_code == 200


def test_bpp_workflow_blocked_without_prerequisites(client: TestClient):
    """BPP registration must not be startable before FIRS/PENCOM/ITF/NSITF are in place —
    surfacing this at submit time (after the client has paid) is the bug being guarded against."""
    _, headers, _ = _register(client, "bpp")
    company = client.post(
        "/api/v1/cac/companies",
        headers=headers,
        json={"name": "BPP Co", "registration_type": "NEW"},
    )
    company_id = company.json()["id"]

    start = client.post(
        f"/api/v1/workflow/BPP_FEDERAL/REGISTRATION/companies/{company_id}/start",
        headers=headers,
    )
    assert start.status_code == 403
    missing = start.json()["detail"]["missing_compliance"]
    assert set(missing) == {"FIRS", "PENCOM", "ITF", "NSITF"}


def test_bpp_workflow_has_steps(client: TestClient):
    import asyncio

    _, headers, _ = _register(client, "bpp")
    company = client.post(
        "/api/v1/cac/companies",
        headers=headers,
        json={"name": "BPP Co", "registration_type": "NEW"},
    )
    company_id = company.json()["id"]
    asyncio.run(_seed_bpp_prerequisites(company_id))

    start = client.post(
        f"/api/v1/workflow/BPP_FEDERAL/REGISTRATION/companies/{company_id}/start",
        headers=headers,
    )
    assert start.status_code == 200
    assert start.json()["total_steps"] == 6

    form = client.get(
        f"/api/v1/workflow/BPP_FEDERAL/REGISTRATION/companies/{company_id}/steps/form",
        headers=headers,
        params={"step_number": 2},
    )
    assert form.status_code == 200
    keys = {f["key"] for f in form.json()["fields"]}
    assert "cac_rc_number" in keys
    assert "contractor_category" in keys
