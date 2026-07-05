"""Inbound payment webhooks."""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.deps import db_pool
from app.modules.cart import repository as cart_repo
from app.modules.cart.service import CartService
from app.modules.payments.paystack import PaystackClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


def get_cart_service(pool=Depends(db_pool)) -> CartService:
    return CartService(pool)


@router.post("/paystack")
async def paystack_webhook(
    request: Request,
    svc: CartService = Depends(get_cart_service),
    pool=Depends(db_pool),
):
    raw_body = await request.body()
    signature = request.headers.get("x-paystack-signature")
    if not PaystackClient.verify_webhook_signature(raw_body, signature):
        raise HTTPException(status_code=401, detail="Invalid Paystack signature")

    payload = await request.json()
    event = payload.get("event")
    data = payload.get("data") or {}

    if event != "charge.success":
        return {"received": True, "ignored": event}

    reference = data.get("reference")
    if not reference:
        raise HTTPException(status_code=400, detail="Missing payment reference")

    async with pool.acquire() as conn:
        payment = await cart_repo.fetch_payment_by_provider_reference(conn, reference)
        if payment is None:
            metadata = data.get("metadata") or {}
            payment_id_str = metadata.get("payment_id")
            if payment_id_str:
                payment = await cart_repo.fetch_payment_by_id(conn, UUID(payment_id_str))

    if payment is None:
        logger.warning("Paystack webhook: unknown reference %s", reference)
        raise HTTPException(status_code=404, detail="Payment not found")

    amount_kobo = data.get("amount")
    expected_kobo = int(float(payment["total_amount_ngn"]) * 100)
    if amount_kobo is not None and int(amount_kobo) != expected_kobo:
        raise HTTPException(status_code=400, detail="Payment amount mismatch")

    result = await svc.finalize_payment_from_webhook(
        payment_id=payment["id"],
        payment_reference=reference,
        start_workflows=True,
    )
    if result is None:
        return {"received": True, "status": "already_completed"}
    return {"received": True, "status": "completed", "payment_id": str(payment["id"])}
