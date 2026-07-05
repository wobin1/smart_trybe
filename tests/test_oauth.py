"""OAuth login tests."""

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.modules.auth.oauth import OAuthUserInfo


pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="Set TEST_DATABASE_URL to run integration tests",
)


@pytest.fixture(scope="module")
def client() -> TestClient:
    from app.main import app

    with TestClient(app) as c:
        yield c


def _mock_google_user(email: str, *, provider_user_id: str | None = None) -> OAuthUserInfo:
    return OAuthUserInfo(
        provider_user_id=provider_user_id or uuid4().hex,
        email=email,
        full_name="Google User",
        email_verified=True,
    )


def test_oauth_login_creates_client_and_returns_token(client: TestClient, monkeypatch):
    email = f"oauth_{uuid4().hex}@example.com"
    info = _mock_google_user(email)

    monkeypatch.setattr(
        "app.modules.auth.service.verify_oauth_token",
        lambda provider, token: info,
    )

    r = client.post(
        "/api/v1/auth/oauth/google",
        json={"id_token": "fake-google-token"},
    )
    assert r.status_code == 200
    token = r.json()["access_token"]
    assert token

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == email.lower()
    assert me.json()["role"] == "CLIENT"


def test_oauth_login_links_existing_password_user(client: TestClient, monkeypatch):
    email = f"link_{uuid4().hex}@example.com"
    password = "securepassword123"
    provider_user_id = uuid4().hex

    reg = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": "Local User"},
    )
    assert reg.status_code == 201

    info = _mock_google_user(email, provider_user_id=provider_user_id)
    monkeypatch.setattr(
        "app.modules.auth.service.verify_oauth_token",
        lambda provider, token: info,
    )

    oauth = client.post(
        "/api/v1/auth/oauth/google",
        json={"id_token": "fake-google-token"},
    )
    assert oauth.status_code == 200
    oauth_token = oauth.json()["access_token"]

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {oauth_token}"})
    assert me.status_code == 200
    assert me.json()["full_name"] == "Local User"

    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200


def test_oauth_login_rejects_unverified_email(client: TestClient, monkeypatch):
    email = f"unverified_{uuid4().hex}@example.com"
    info = OAuthUserInfo(
        provider_user_id=uuid4().hex,
        email=email,
        full_name="Google User",
        email_verified=False,
    )
    monkeypatch.setattr(
        "app.modules.auth.service.verify_oauth_token",
        lambda provider, token: info,
    )

    r = client.post(
        "/api/v1/auth/oauth/google",
        json={"id_token": "fake-google-token"},
    )
    assert r.status_code == 401
    assert "not verified" in r.json()["detail"].lower()


def test_oauth_only_user_cannot_password_login(client: TestClient, monkeypatch):
    email = f"oauthonly_{uuid4().hex}@example.com"
    info = _mock_google_user(email)
    monkeypatch.setattr(
        "app.modules.auth.service.verify_oauth_token",
        lambda provider, token: info,
    )

    oauth = client.post(
        "/api/v1/auth/oauth/google",
        json={"id_token": "fake-google-token"},
    )
    assert oauth.status_code == 200

    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "anypassword123"},
    )
    assert login.status_code == 401
