"""Payment and Paystack webhook tests."""

import hashlib
import hmac
import json
import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient


pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="Set TEST_DATABASE_URL to run integration tests",
)


def _register_client(client: TestClient) -> tuple[str, dict]:
    email = f"pay_{uuid4().hex}@example.com"
    password = "securepassword123"
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password},
    )
    assert reg.status_code == 201
    token = reg.json()["access_token"]
    return token, {"Authorization": f"Bearer {token}"}


def _checkout(client: TestClient, headers: dict) -> tuple[str, str, str]:
    company = client.post(
        "/api/v1/cac/companies",
        headers=headers,
        json={"name": "Pay Co", "registration_type": "NEW"},
    )
    assert company.status_code == 201
    company_id = company.json()["id"]

    client.post(
        f"/api/v1/cart/companies/{company_id}/items",
        headers=headers,
        json={"compliance_type": "ITF", "mode": "NEW"},
    )
    checkout = client.post(
        f"/api/v1/cart/companies/{company_id}/checkout",
        headers=headers,
    )
    assert checkout.status_code == 200
    body = checkout.json()
    return company_id, body["payment_id"], body


def test_initialize_payment_dev_mode(client: TestClient, monkeypatch):
    monkeypatch.setenv("PAYMENT_DEV_MODE", "true")
    monkeypatch.setenv("PAYSTACK_SECRET_KEY", "")
    from app.core.config import settings

    settings.payment_dev_mode = True
    settings.paystack_secret_key = ""

    _, headers = _register_client(client)
    company_id, payment_id, _ = _checkout(client, headers)

    init = client.post(
        f"/api/v1/cart/companies/{company_id}/initialize-payment",
        headers=headers,
        json={"payment_id": payment_id},
    )
    assert init.status_code == 200
    assert init.json()["dev_mode"] is True
    assert init.json()["provider"] == "manual"


def test_initialize_payment_dev_mode_ignores_placeholder_paystack(
    client: TestClient, monkeypatch
):
    """PAYMENT_DEV_MODE=true must not call Paystack even if a secret key is set."""
    monkeypatch.setenv("PAYMENT_DEV_MODE", "true")
    monkeypatch.setenv("PAYSTACK_SECRET_KEY", "sk_test_xxxxxxxx")
    from app.core.config import settings

    settings.payment_dev_mode = True
    settings.paystack_secret_key = "sk_test_xxxxxxxx"

    _, headers = _register_client(client)
    company_id, payment_id, _ = _checkout(client, headers)

    init = client.post(
        f"/api/v1/cart/companies/{company_id}/initialize-payment",
        headers=headers,
        json={"payment_id": payment_id},
    )
    assert init.status_code == 200
    assert init.json()["dev_mode"] is True
    assert init.json()["provider"] == "manual"


def test_manual_pay_in_dev_mode(client: TestClient, monkeypatch):
    monkeypatch.setenv("PAYMENT_DEV_MODE", "true")
    monkeypatch.setenv("PAYSTACK_SECRET_KEY", "")
    from app.core.config import settings

    settings.payment_dev_mode = True
    settings.paystack_secret_key = ""

    _, headers = _register_client(client)
    company_id, payment_id, checkout_body = _checkout(client, headers)

    pay = client.post(
        f"/api/v1/cart/companies/{company_id}/pay",
        headers=headers,
        json={
            "payment_id": payment_id,
            "payment_reference": f"PAY-{uuid4().hex[:8]}",
        },
    )
    assert pay.status_code == 200
    assert pay.json()["status"] == "COMPLETED"
    assert len(pay.json()["workflows_started"]) == 1
    assert pay.json()["total_amount_ngn"] == checkout_body["total_amount_ngn"]


def test_paystack_webhook_completes_payment(client: TestClient, monkeypatch):
    secret = "sk_test_webhook_secret_key_12345"
    monkeypatch.setenv("PAYSTACK_SECRET_KEY", secret)
    monkeypatch.setenv("PAYMENT_DEV_MODE", "false")
    from app.core.config import settings

    settings.paystack_secret_key = secret
    settings.payment_dev_mode = False

    _, headers = _register_client(client)
    company_id, payment_id, checkout_body = _checkout(client, headers)
    reference = f"st_webhook_{uuid4().hex[:8]}"

    import asyncpg

    async def _set_provider_ref():
        conn = await asyncpg.connect(os.environ["TEST_DATABASE_URL"])
        try:
            await conn.execute(
                """
                UPDATE compliance_payments
                SET provider = 'paystack', provider_reference = $2
                WHERE id = $1
                """,
                payment_id,
                reference,
            )
        finally:
            await conn.close()

    import asyncio

    asyncio.run(_set_provider_ref())

    payload = {
        "event": "charge.success",
        "data": {
            "reference": reference,
            "amount": int(checkout_body["total_amount_ngn"] * 100),
            "metadata": {"payment_id": payment_id},
        },
    }
    raw = json.dumps(payload).encode()
    signature = hmac.new(secret.encode(), raw, hashlib.sha512).hexdigest()

    response = client.post(
        "/api/v1/webhooks/paystack",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "x-paystack-signature": signature,
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "completed"

    progress = client.get(
        f"/api/v1/workflow/companies/{company_id}/progress",
        headers=headers,
    )
    itf = next(
        w for w in progress.json()["workflows"]
        if w["compliance_type"] == "ITF" and w["mode"] == "NEW"
    )
    assert itf["started"] is True
