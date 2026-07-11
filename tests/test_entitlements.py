"""Payment entitlement tests — submit requires paid cart line for compliance."""

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.modules.workflow.catalog import WORKFLOW_STEP_DEFINITIONS

needs_db = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="Set TEST_DATABASE_URL to run integration tests",
)


def test_all_workflows_end_with_make_payment():
    for key, steps in WORKFLOW_STEP_DEFINITIONS.items():
        assert steps, f"{key} has no steps"
        assert steps[-1] == "Make payment", f"{key} last step is {steps[-1]!r}"


def _register(client: TestClient) -> dict:
    email = f"ent_{uuid4().hex}@example.com"
    password = "securepassword123"
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password},
    )
    assert reg.status_code == 201
    return {"Authorization": f"Bearer {reg.json()['access_token']}"}


@needs_db
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

    status = client.get(
        f"/api/v1/workflow/FIRS/NEW/companies/{company_id}/status",
        headers=headers,
    )
    assert status.status_code == 200
    assert status.json()["payment"]["is_paid"] is False


@needs_db
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

    status = client.get(
        f"/api/v1/workflow/FIRS/NEW/companies/{company_id}/status",
        headers=headers,
    )
    assert status.status_code == 200
    body = status.json()
    assert body["payment"]["is_paid"] is True
    payment_step = next(s for s in body["steps"] if s["step_name"] == "Make payment")
    assert payment_step["is_completed"] is True

    submit = client.post(
        f"/api/v1/workflow/FIRS/NEW/companies/{company_id}/submit",
        headers=headers,
        json={},
    )
    assert submit.status_code == 403
    missing = submit.json()["detail"]["missing"]
    assert not any("PAYMENT" in m for m in missing)


@needs_db
def test_complete_make_payment_blocked_when_unpaid(client: TestClient):
    headers = _register(client)
    company = client.post(
        "/api/v1/cac/companies",
        headers=headers,
        json={"name": "Unpaid Step Co", "registration_type": "NEW"},
    )
    company_id = company.json()["id"]

    start = client.post(
        f"/api/v1/workflow/FIRS/NEW/companies/{company_id}/start",
        headers=headers,
    )
    assert start.status_code == 200
    total = start.json()["total_steps"]

    complete = client.post(
        f"/api/v1/workflow/FIRS/NEW/companies/{company_id}/steps/{total}/complete",
        headers=headers,
        json={"step_name": "Make payment", "data": {"payment_reference": "FAKE-REF"}},
    )
    assert complete.status_code == 402


@needs_db
def test_checkout_payment_from_workflow_step(client: TestClient):
    headers = _register(client)
    company = client.post(
        "/api/v1/cac/companies",
        headers=headers,
        json={"name": "Step Pay Co", "registration_type": "NEW"},
    )
    company_id = company.json()["id"]

    client.post(
        f"/api/v1/workflow/ITF/NEW/companies/{company_id}/start",
        headers=headers,
    )

    init = client.post(
        f"/api/v1/workflow/ITF/NEW/companies/{company_id}/checkout-payment",
        headers=headers,
    )
    assert init.status_code == 200
    body = init.json()
    assert "payment_id" in body

    pay = client.post(
        f"/api/v1/cart/companies/{company_id}/pay",
        headers=headers,
        json={
            "payment_id": body["payment_id"],
            "payment_reference": f"PAY-STEP-{uuid4().hex[:8]}",
            "start_workflows": True,
        },
    )
    assert pay.status_code == 200

    status = client.get(
        f"/api/v1/workflow/ITF/NEW/companies/{company_id}/status",
        headers=headers,
    )
    assert status.json()["payment"]["is_paid"] is True
    payment_step = next(s for s in status.json()["steps"] if s["step_name"] == "Make payment")
    assert payment_step["is_completed"] is True
