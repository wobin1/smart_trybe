"""Fire-and-forget Zoho Flow webhook notifications."""

import asyncio
import hashlib
import hmac
import json
import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class NotificationService:
    """Posts structured events to Zoho Flow webhook URLs for email/SMS workflows."""

    _EVENT_URLS: dict[str, str] = {}

    @classmethod
    def _url_for(cls, event: str) -> str | None:
        if not cls._EVENT_URLS:
            cls._EVENT_URLS = {
                "payment.completed": settings.zoho_flow_webhook_payment.strip(),
                "workflow.submitted": settings.zoho_flow_webhook_workflow_submitted.strip(),
                "agent.assigned": settings.zoho_flow_webhook_agent_assigned.strip(),
                "workflow.completed": settings.zoho_flow_webhook_workflow_completed.strip(),
            }
        url = cls._EVENT_URLS.get(event, "")
        return url or None

    @classmethod
    def _sign_payload(cls, body: bytes) -> str | None:
        secret = settings.zoho_flow_webhook_secret.strip()
        if not secret:
            return None
        return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    @classmethod
    async def _post(cls, event: str, payload: dict[str, Any]) -> None:
        url = cls._url_for(event)
        if not url:
            logger.debug("Zoho Flow webhook not configured for %s", event)
            return

        envelope = {"event": event, "payload": payload}
        body = json.dumps(envelope, default=str).encode()
        headers = {"Content-Type": "application/json"}
        signature = cls._sign_payload(body)
        if signature:
            headers["X-Webhook-Signature"] = signature

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, content=body, headers=headers)
                response.raise_for_status()
        except Exception:
            logger.exception("Zoho Flow webhook failed for event %s", event)

    @classmethod
    def emit(cls, event: str, payload: dict[str, Any]) -> None:
        """Schedule notification without blocking the request."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(cls._post(event, payload))
        except RuntimeError:
            asyncio.run(cls._post(event, payload))
