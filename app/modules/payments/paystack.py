"""Paystack payment provider client."""

import hashlib
import hmac
import uuid
from decimal import Decimal
from typing import Any

import httpx
from fastapi import HTTPException

from app.core.config import settings

PAYSTACK_BASE = "https://api.paystack.co"


class PaystackClient:
    @staticmethod
    def configured() -> bool:
        return bool(settings.paystack_secret_key.strip())

    @staticmethod
    def _headers() -> dict[str, str]:
        return {
            "Authorization": f"Bearer {settings.paystack_secret_key}",
            "Content-Type": "application/json",
        }

    @classmethod
    async def initialize_transaction(
        cls,
        *,
        email: str,
        amount_ngn: Decimal,
        payment_id: str,
        company_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not cls.configured():
            raise HTTPException(status_code=503, detail="Paystack is not configured")

        reference = f"st_{payment_id.replace('-', '')}_{uuid.uuid4().hex[:8]}"
        amount_kobo = int(amount_ngn * 100)
        if amount_kobo < 1:
            raise HTTPException(status_code=400, detail="Payment amount must be positive")

        payload: dict[str, Any] = {
            "email": email,
            "amount": amount_kobo,
            "reference": reference,
            "currency": "NGN",
            "metadata": {
                "payment_id": payment_id,
                "company_id": company_id,
                **(metadata or {}),
            },
        }
        callback = settings.paystack_callback_url.strip()
        if callback:
            payload["callback_url"] = callback

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{PAYSTACK_BASE}/transaction/initialize",
                json=payload,
                headers=cls._headers(),
            )
            data = response.json()
            if not response.is_success or not data.get("status"):
                message = data.get("message", "Paystack initialization failed")
                raise HTTPException(status_code=502, detail=message)

        inner = data["data"]
        return {
            "authorization_url": inner["authorization_url"],
            "access_code": inner["access_code"],
            "reference": inner["reference"],
        }

    @classmethod
    def verify_webhook_signature(cls, raw_body: bytes, signature: str | None) -> bool:
        if not signature or not cls.configured():
            return False
        digest = hmac.new(
            settings.paystack_secret_key.encode(),
            raw_body,
            hashlib.sha512,
        ).hexdigest()
        return hmac.compare_digest(digest, signature)

    @classmethod
    async def verify_transaction(cls, reference: str) -> dict[str, Any]:
        if not cls.configured():
            raise HTTPException(status_code=503, detail="Paystack is not configured")

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{PAYSTACK_BASE}/transaction/verify/{reference}",
                headers=cls._headers(),
            )
            data = response.json()
            if not response.is_success or not data.get("status"):
                raise HTTPException(status_code=502, detail=data.get("message", "Verification failed"))
        return data["data"]
