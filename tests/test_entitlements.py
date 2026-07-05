"""Payment entitlement tests — submit requires paid cart line for compliance."""

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="Set TEST_DATABASE_URL to run integration tests",
)


def _register(client: TestClient) -> dict:
    email = f"ent_{uuid4().hex}@example.com"
    password = "securepassword123"
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password},
    )
    assert reg.status_code == 201
    return {"Authorization": f"Bearer {reg.json()['access_token']}"}


def test_submit_blocked_without_payment(client: TestClient):
    headers = _register(client)
    company = client.post(
        "/api/v1/cac/companies",
        headers=headers,
        json={"name": "Entitlement Co", "registration_type": "NEW"},
    )
    company_id = company.json()["id"]

    start = client.post(
        f"/api/v1/workflow/FIRS/NEW/companies/{company_id}/start",
        headers=headers,
    )
    assert start.status_code == 200

    submit = client.post(
        f"/api/v1/workflow/FIRS/NEW/companies/{company_id}/submit",
        headers=headers,
        json={},
    )
    assert submit.status_code == 403
    missing = submit.json()["detail"]["missing"]
    assert any("PAYMENT" in m for m in missing)


def test_submit_allowed_after_payment(client: TestClient):
    headers = _register(client)
    company = client.post(
        "/api/v1/cac/companies",
        headers=headers,
        json={
            "name": "Paid Co",
            "rc_number": "RC-ENT-001",
            "registration_type": "EXISTING",
        },
    )
    company_id = company.json()["id"]

    client.post(
        f"/api/v1/workflow/FIRS/NEW/companies/{company_id}/start",
        headers=headers,
    )

    client.post(
        f"/api/v1/cart/companies/{company_id}/items",
        headers=headers,
        json={"compliance_type": "FIRS", "mode": "NEW"},
    )
    checkout = client.post(
        f"/api/v1/cart/companies/{company_id}/checkout",
        headers=headers,
    )
    payment_id = checkout.json()["payment_id"]

    pay = client.post(
        f"/api/v1/cart/companies/{company_id}/pay",
        headers=headers,
        json={
            "payment_id": payment_id,
            "payment_reference": f"PAY-{uuid4().hex[:8]}",
            "start_workflows": False,
        },
    )
    assert pay.status_code == 200

    submit = client.post(
        f"/api/v1/workflow/FIRS/NEW/companies/{company_id}/submit",
        headers=headers,
        json={},
    )
    assert submit.status_code == 403
    missing = submit.json()["detail"]["missing"]
    assert not any("PAYMENT" in m for m in missing)
