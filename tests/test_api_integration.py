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
