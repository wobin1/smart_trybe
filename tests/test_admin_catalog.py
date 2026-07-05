"""Tests for admin catalog management."""

import asyncio
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


def _admin_headers(client: TestClient) -> dict:
    email = f"catalog_admin_{uuid4().hex}@example.com"
    password = "securepassword123"
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": "Catalog Admin"},
    )
    assert reg.status_code == 201
    asyncio.run(_set_user_role(email, "ADMIN"))
    token = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_admin_catalog_list_and_update_price(client: TestClient):
    headers = _admin_headers(client)

    listed = client.get("/api/v1/admin/catalog/items", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["count"] >= 10
    cac_new = next(
        i
        for i in listed.json()["items"]
        if i["compliance_type"] == "CAC" and i["mode"] == "NEW"
    )
    original_price = cac_new["base_price_ngn"]
    assert "is_active" in cac_new

    updated = client.patch(
        "/api/v1/admin/catalog/items/CAC/NEW",
        headers=headers,
        json={"base_price_ngn": 99000},
    )
    assert updated.status_code == 200
    assert updated.json()["base_price_ngn"] == 99000

    detail = client.get("/api/v1/admin/catalog/items/CAC/NEW", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["base_price_ngn"] == 99000

    client.patch(
        "/api/v1/admin/catalog/items/CAC/NEW",
        headers=headers,
        json={"base_price_ngn": original_price},
    )


def test_cart_price_snapshot_after_admin_price_change(client: TestClient):
    admin_headers = _admin_headers(client)

    client.patch(
        "/api/v1/admin/catalog/items/CAC/RENEWAL",
        headers=admin_headers,
        json={"base_price_ngn": 11111},
    )

    email = f"cart_snap_{uuid4().hex}@example.com"
    password = "securepassword123"
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": "Snap User"},
    )
    assert reg.status_code == 201
    user_headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}

    company = client.post(
        "/api/v1/cac/companies",
        headers=user_headers,
        json={"name": "Snap Ltd", "rc_number": "RC111", "registration_type": "EXISTING"},
    )
    assert company.status_code == 201
    company_id = company.json()["id"]

    add = client.post(
        f"/api/v1/cart/companies/{company_id}/items",
        headers=user_headers,
        json={"compliance_type": "CAC", "mode": "RENEWAL"},
    )
    assert add.status_code == 201
    snapshotted = add.json()["items"][0]["unit_price_ngn"]
    assert snapshotted == 11111

    client.patch(
        "/api/v1/admin/catalog/items/CAC/RENEWAL",
        headers=admin_headers,
        json={"base_price_ngn": 22222},
    )

    cart = client.get(f"/api/v1/cart/companies/{company_id}", headers=user_headers)
    assert cart.status_code == 200
    assert cart.json()["items"][0]["unit_price_ngn"] == snapshotted

    client.patch(
        "/api/v1/admin/catalog/items/CAC/RENEWAL",
        headers=admin_headers,
        json={"base_price_ngn": 25000},
    )


def test_non_admin_cannot_update_catalog(client: TestClient):
    email = f"not_admin_{uuid4().hex}@example.com"
    password = "securepassword123"
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": "Regular User"},
    )
    headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}

    resp = client.patch(
        "/api/v1/admin/catalog/items/CAC/NEW",
        headers=headers,
        json={"base_price_ngn": 1},
    )
    assert resp.status_code == 403
