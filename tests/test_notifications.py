"""Zoho Flow notification emission tests."""

import asyncio

from app.modules.notifications.service import NotificationService


def test_notification_skips_when_url_not_configured(monkeypatch):
    monkeypatch.setattr(
        NotificationService,
        "_EVENT_URLS",
        {"payment.completed": ""},
    )
    asyncio.run(NotificationService._post("payment.completed", {"payment_id": "test"}))


def test_notification_posts_to_zoho_flow(monkeypatch):
    posted: list[dict] = []

    class FakeResponse:
        def raise_for_status(self):
            return None

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, content, headers):
            posted.append({"url": url, "content": content, "headers": headers})
            return FakeResponse()

    monkeypatch.setattr(
        NotificationService,
        "_EVENT_URLS",
        {"payment.completed": "https://flow.zoho.com/test/webhook"},
    )
    monkeypatch.setattr("app.modules.notifications.service.httpx.AsyncClient", lambda **kw: FakeClient())

    asyncio.run(NotificationService._post("payment.completed", {"payment_id": "abc"}))
    assert len(posted) == 1
    assert posted[0]["url"] == "https://flow.zoho.com/test/webhook"
    assert b'"event": "payment.completed"' in posted[0]["content"]
