"""Tests for catalog, cart, and dashboard APIs."""

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="Set TEST_DATABASE_URL to run integration tests",
)


def _register_client(client: TestClient) -> tuple[str, dict]:
    email = f"cart_{uuid4().hex}@example.com"
    password = "securepassword123"
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": "Cart User"},
    )
    assert reg.status_code == 201
    token = reg.json()["access_token"]
    return token, {"Authorization": f"Bearer {token}"}


def _create_company(client: TestClient, headers: dict) -> str:
    create = client.post(
        "/api/v1/cac/companies",
        headers=headers,
        json={
            "name": "Cart Test Ltd",
            "rc_number": "RC999",
            "registration_type": "EXISTING",
        },
    )
    assert create.status_code == 201
    return create.json()["id"]


def test_catalog_categories_and_filter(client: TestClient):
    token, headers = _register_client(client)

    categories = client.get("/api/v1/catalog/categories", headers=headers)
    assert categories.status_code == 200
    slugs = {c["slug"] for c in categories.json()["categories"]}
    assert "corporate_registration" in slugs
    assert "tax_finance" in slugs

    all_items = client.get("/api/v1/catalog/items", headers=headers)
    assert all_items.status_code == 200
    assert all_items.json()["category_filter"] == "all"
    assert all_items.json()["count"] >= 10

    tax_items = client.get(
        "/api/v1/catalog/items",
        headers=headers,
        params={"category": "tax_finance"},
    )
    assert tax_items.status_code == 200
    assert all(
        i["category"]["slug"] == "tax_finance" for i in tax_items.json()["items"]
    )


def test_cart_checkout_and_shared_fields(client: TestClient):
    _, headers = _register_client(client)
    company_id = _create_company(client, headers)

    empty = client.get(f"/api/v1/cart/companies/{company_id}", headers=headers)
    assert empty.status_code == 200
    assert empty.json()["cart"] is None

    add_cac = client.post(
        f"/api/v1/cart/companies/{company_id}/items",
        headers=headers,
        json={"compliance_type": "CAC", "mode": "RENEWAL"},
    )
    assert add_cac.status_code == 201
    assert len(add_cac.json()["items"]) == 1

    add_firs = client.post(
        f"/api/v1/cart/companies/{company_id}/items",
        headers=headers,
        json={"compliance_type": "FIRS", "mode": "NEW"},
    )
    assert add_firs.status_code == 201
    assert len(add_firs.json()["items"]) == 2
    assert add_firs.json()["subtotal_ngn"] > 0

    company_data = client.get(f"/api/v1/companies/{company_id}/data", headers=headers)
    assert company_data.status_code == 200
    assert company_data.json()["data"].get("rc_number") == "RC999"

    checkout = client.post(
        f"/api/v1/cart/companies/{company_id}/checkout",
        headers=headers,
    )
    assert checkout.status_code == 200
    body = checkout.json()
    assert body["status"] == "CHECKOUT"
    assert len(body["breakdown"]) == 2
    assert body["total_amount_ngn"] == sum(i["amount_ngn"] for i in body["breakdown"])

    pay = client.post(
        f"/api/v1/cart/companies/{company_id}/pay",
        headers=headers,
        json={
            "payment_id": body["payment_id"],
            "payment_reference": f"PAY-{uuid4().hex[:8]}",
        },
    )
    assert pay.status_code == 200
    assert pay.json()["status"] == "COMPLETED"
    assert len(pay.json()["workflows_started"]) == 2


def test_cross_compliance_data_propagation(client: TestClient):
    _, headers = _register_client(client)
    company_id = _create_company(client, headers)

    client.post(
        f"/api/v1/workflow/CAC/NEW/companies/{company_id}/start",
        headers=headers,
    )
    client.post(
        f"/api/v1/workflow/FIRS/NEW/companies/{company_id}/start",
        headers=headers,
    )

    complete = client.post(
        f"/api/v1/workflow/CAC/NEW/companies/{company_id}/steps/5/complete",
        headers=headers,
        json={
            "step_name": "Provide company address",
            "data": {
                "address": "42 Marina Road, Lagos",
                "city": "Lagos",
                "state": "Lagos",
            },
        },
    )
    assert complete.status_code == 200

    firs_status = client.get(
        f"/api/v1/workflow/FIRS/NEW/companies/{company_id}/status",
        headers=headers,
    )
    assert firs_status.status_code == 200
    firs_step_2 = next(
        s for s in firs_status.json()["steps"] if s["step_number"] == 2
    )
    assert firs_step_2["step_data"].get("business_address") == "42 Marina Road, Lagos"

    client.post(
        f"/api/v1/cart/companies/{company_id}/items",
        headers=headers,
        json={"compliance_type": "ITF", "mode": "NEW"},
    )
    update_data = client.put(
        f"/api/v1/companies/{company_id}/data",
        headers=headers,
        json={
            "data": {
                "directors": [{"name": "Jane Doe", "email": "jane@carttest.com"}],
                "rc_number": "RC999",
            }
        },
    )
    assert update_data.status_code == 200
    assert update_data.json()["data"]["rc_number"] == "RC999"

    firs_status = client.get(
        f"/api/v1/workflow/FIRS/NEW/companies/{company_id}/status",
        headers=headers,
    )
    firs_step_1 = next(
        s for s in firs_status.json()["steps"] if s["step_number"] == 1
    )
    assert firs_step_1["step_data"].get("cac_rc_number") == "RC999"


def test_dashboard_and_renewals(client: TestClient):
    _, headers = _register_client(client)
    company_id = _create_company(client, headers)

    dash = client.get("/api/v1/dashboard", headers=headers)
    assert dash.status_code == 200
    assert dash.json()["summary"]["company_count"] == 1

    company_dash = client.get(
        f"/api/v1/dashboard/companies/{company_id}",
        headers=headers,
    )
    assert company_dash.status_code == 200
    assert company_dash.json()["company"]["id"] == company_id

    renewals = client.get("/api/v1/dashboard/renewals", headers=headers)
    assert renewals.status_code == 200
    assert "renewals" in renewals.json()
