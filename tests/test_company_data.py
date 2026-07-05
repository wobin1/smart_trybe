"""Tests for central company_data reuse across compliances."""

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="Set TEST_DATABASE_URL to run integration tests",
)


def _register_client(client: TestClient) -> dict:
    email = f"data_{uuid4().hex}@example.com"
    password = "securepassword123"
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": "Data User"},
    )
    assert reg.status_code == 201
    return {"Authorization": f"Bearer {reg.json()['access_token']}"}


def test_company_data_prefills_workflow_on_read(client: TestClient):
    headers = _register_client(client)

    company = client.post(
        "/api/v1/cac/companies",
        headers=headers,
        json={"name": "Data Reuse Ltd", "rc_number": "RC555", "registration_type": "EXISTING"},
    )
    assert company.status_code == 201
    company_id = company.json()["id"]

    client.post(f"/api/v1/workflow/FIRS/NEW/companies/{company_id}/start", headers=headers)

    update = client.put(
        f"/api/v1/companies/{company_id}/data",
        headers=headers,
        json={"data": {"rc_number": "RC555", "company_address": "10 Broad Street, Lagos"}},
    )
    assert update.status_code == 200

    status = client.get(
        f"/api/v1/workflow/FIRS/NEW/companies/{company_id}/status",
        headers=headers,
    )
    assert status.status_code == 200
    step_1 = next(s for s in status.json()["steps"] if s["step_number"] == 1)
    step_2 = next(s for s in status.json()["steps"] if s["step_number"] == 2)
    assert step_1["step_data"].get("cac_rc_number") == "RC555"
    assert step_2["step_data"].get("business_address") == "10 Broad Street, Lagos"


def test_get_and_update_company_data_endpoint(client: TestClient):
    headers = _register_client(client)

    company = client.post(
        "/api/v1/cac/companies",
        headers=headers,
        json={"name": "Data API Ltd", "rc_number": "RC777", "registration_type": "EXISTING"},
    )
    assert company.status_code == 201
    company_id = company.json()["id"]

    empty = client.get(f"/api/v1/companies/{company_id}/data", headers=headers)
    assert empty.status_code == 200
    assert empty.json()["company_id"] == company_id
    assert empty.json()["data"].get("rc_number") == "RC777"
    assert empty.json()["data"].get("company_name") == "Data API Ltd"

    update = client.put(
        f"/api/v1/companies/{company_id}/data",
        headers=headers,
        json={"data": {"directors": [{"name": "Ada Lovelace", "email": "ada@example.com"}]}},
    )
    assert update.status_code == 200

    filled = client.get(f"/api/v1/companies/{company_id}/data", headers=headers)
    assert filled.status_code == 200
    assert filled.json()["field_count"] >= 2
    assert filled.json()["data"]["directors"][0]["name"] == "Ada Lovelace"
    director_field = next(f for f in filled.json()["fields"] if f["key"] == "directors")
    assert director_field["label"] == "Directors"
