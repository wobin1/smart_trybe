"""Tests for workflow step form endpoint."""

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="Set TEST_DATABASE_URL to run integration tests",
)


def _register_client(client: TestClient) -> dict:
    email = f"stepform_{uuid4().hex}@example.com"
    password = "securepassword123"
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": "Step Form User"},
    )
    assert reg.status_code == 201
    return {"Authorization": f"Bearer {reg.json()['access_token']}"}


def test_get_step_form_with_prefilled_company_data(client: TestClient):
    headers = _register_client(client)

    company = client.post(
        "/api/v1/cac/companies",
        headers=headers,
        json={
            "name": "Step Form Ltd",
            "rc_number": "RC-STEP-001",
            "registration_type": "EXISTING",
        },
    )
    assert company.status_code == 201
    company_id = company.json()["id"]

    client.post(
        f"/api/v1/workflow/FIRS/NEW/companies/{company_id}/start",
        headers=headers,
    )
    client.put(
        f"/api/v1/companies/{company_id}/data",
        headers=headers,
        json={
            "data": {
                "rc_number": "RC-STEP-001",
                "company_address": "1 Test Street, Lagos",
                "contact_email": "hello@stepform.ng",
            }
        },
    )

    form = client.get(
        f"/api/v1/workflow/FIRS/NEW/companies/{company_id}/steps/form",
        headers=headers,
        params={"step_name": "Provide CAC details"},
    )
    assert form.status_code == 200
    body = form.json()
    assert body["step_name"] == "Provide CAC details"
    assert body["step_number"] == 1
    rc_field = next(f for f in body["fields"] if f["key"] == "cac_rc_number")
    assert rc_field["value"] == "RC-STEP-001"
    assert rc_field["filled"] is True
    assert rc_field["shared"] is True
    assert rc_field["canonical_key"] == "rc_number"
    assert body["ready_to_complete"] is True

    contact_form = client.get(
        f"/api/v1/workflow/FIRS/NEW/companies/{company_id}/steps/form",
        headers=headers,
        params={"step_number": 3},
    )
    assert contact_form.status_code == 200
    email_field = next(f for f in contact_form.json()["fields"] if f["key"] == "contact_email")
    assert email_field["value"] == "hello@stepform.ng"
    assert "contact_phone" in contact_form.json()["missing_required"]

    save = client.put(
        f"/api/v1/workflow/FIRS/NEW/companies/{company_id}/steps/3/draft",
        headers=headers,
        json={"data": {"contact_phone": "+2348011111111"}},
    )
    assert save.status_code == 200

    refreshed = client.get(
        f"/api/v1/workflow/FIRS/NEW/companies/{company_id}/steps/form",
        headers=headers,
        params={"step_name": "Provide contact details"},
    )
    phone_field = next(f for f in refreshed.json()["fields"] if f["key"] == "contact_phone")
    assert phone_field["value"] == "+2348011111111"
    assert refreshed.json()["ready_to_complete"] is True
