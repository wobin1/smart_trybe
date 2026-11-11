import json
import uuid
from decimal import Decimal
from uuid import UUID

import asyncpg
from fastapi import HTTPException

from app.domain.enums import CartStatus, ComplianceMode, ComplianceType, PaymentStatus, UserRole
from app.modules.access.company import require_company_client, require_company_read
from app.modules.cart import repository as cart_repo
from app.modules.catalog import repository as catalog_repo
from app.modules.entitlements import repository as entitlements_repo
from app.modules.notifications.service import NotificationService
from app.modules.payments.paystack import PaystackClient
from app.modules.workflow.service import WorkflowService


class CartService:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def get_cart(
        self, *, company_id: UUID, user_id: UUID, role: UserRole
    ) -> dict:
        async with self._pool.acquire() as conn:
            await require_company_read(conn, company_id, user_id, role)
            cart = await cart_repo.fetch_open_cart(conn, company_id)
            if cart is None:
                return {
                    "company_id": str(company_id),
                    "cart": None,
                    "items": [],
                    "subtotal_ngn": 0,
                }
            return await self._format_cart(conn, cart)

    async def get_payment_status(self, *, user_id: UUID, reference: str) -> dict:
        """Look up a payment (or a combined "pay all" batch of them) by its
        Paystack reference — powers the /payments/callback page, which lands
        here before the webhook may have finished processing the charge."""
        async with self._pool.acquire() as conn:
            payments = await cart_repo.fetch_payments_by_provider_reference(conn, reference)
            owned: list[asyncpg.Record] = []
            for p in payments:
                cart = await cart_repo.fetch_cart_by_id(conn, p["cart_id"])
                if cart is not None and str(cart["user_id"]) == str(user_id):
                    owned.append(p)

        if not owned:
            raise HTTPException(status_code=404, detail="Payment not found")

        statuses = {p["status"] for p in owned}
        if statuses == {PaymentStatus.COMPLETED.value}:
            overall = PaymentStatus.COMPLETED.value
        elif PaymentStatus.FAILED.value in statuses:
            overall = PaymentStatus.FAILED.value
        else:
            overall = PaymentStatus.PENDING.value

        return {
            "reference": reference,
            "status": overall,
            "total_amount_ngn": sum(float(p["total_amount_ngn"]) for p in owned),
            "payments": [
                {
                    "payment_id": str(p["id"]),
                    "status": p["status"],
                    "total_amount_ngn": float(p["total_amount_ngn"]),
                }
                for p in owned
            ],
        }

    async def get_my_carts(self, *, user_id: UUID) -> dict:
        """Aggregate every OPEN/CHECKOUT cart the user has across all of their
        companies — powers the global cart icon in the app header."""
        async with self._pool.acquire() as conn:
            rows = await cart_repo.list_carts_for_user(conn, user_id)

            carts: dict[UUID, dict] = {}
            for row in rows:
                cart_id = row["cart_id"]
                cart = carts.get(cart_id)
                if cart is None:
                    cart = {
                        "cart_id": str(cart_id),
                        "company_id": str(row["company_id"]),
                        "company_name": row["company_name"],
                        "cart_status": row["cart_status"],
                        "items": [],
                        "subtotal_ngn": 0.0,
                    }
                    carts[cart_id] = cart
                cart["items"].append(
                    {
                        "id": str(row["item_id"]),
                        "compliance_type": row["compliance_type"],
                        "mode": row["mode"],
                        "display_name": row["display_name"]
                        or f"{row['compliance_type']} ({row['mode']})",
                        "icon_key": row["icon_key"],
                        "unit_price_ngn": float(row["unit_price_ngn"]),
                        "added_at": row["added_at"].isoformat(),
                    }
                )
                cart["subtotal_ngn"] += float(row["unit_price_ngn"])

            # Checked-out carts are mid-payment — surface where to resume so
            # a stalled Paystack redirect doesn't strand the client.
            for cart_id, cart in carts.items():
                if cart["cart_status"] != CartStatus.CHECKOUT.value:
                    continue
                payment = await cart_repo.fetch_latest_payment(conn, cart_id)
                if payment is not None and payment["status"] == PaymentStatus.PENDING.value:
                    cart["pending_payment"] = {
                        "payment_id": str(payment["id"]),
                        "authorization_url": payment["authorization_url"],
                    }

            cart_list = sorted(
                carts.values(), key=lambda c: (c["company_name"], c["cart_id"])
            )
            return {
                "carts": cart_list,
                "total_items": sum(len(c["items"]) for c in cart_list),
                "total_ngn": sum(c["subtotal_ngn"] for c in cart_list),
            }

    async def add_item(
        self,
        *,
        company_id: UUID,
        user_id: UUID,
        role: UserRole,
        compliance_type: ComplianceType,
        mode: ComplianceMode,
    ) -> dict:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await require_company_client(conn, company_id, user_id, role)
                catalog = await catalog_repo.fetch_catalog_item(
                    conn, compliance_type.value, mode.value
                )
                if catalog is None:
                    raise HTTPException(status_code=404, detail="Compliance not available in catalog")

                cart = await cart_repo.fetch_open_cart(conn, company_id)
                if cart is None:
                    cart = await cart_repo.create_cart(conn, company_id, user_id)

                await cart_repo.add_cart_item(
                    conn,
                    cart["id"],
                    compliance_type.value,
                    mode.value,
                    Decimal(str(catalog["base_price_ngn"])),
                )
                cart = await cart_repo.fetch_cart_by_id(conn, cart["id"])
                assert cart is not None
                return await self._format_cart(conn, cart)

    async def remove_item(
        self,
        *,
        company_id: UUID,
        user_id: UUID,
        role: UserRole,
        item_id: UUID,
    ) -> dict:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await require_company_client(conn, company_id, user_id, role)
                cart = await cart_repo.fetch_open_cart(conn, company_id)
                if cart is None:
                    raise HTTPException(status_code=404, detail="No open cart found")
                removed = await cart_repo.remove_cart_item(conn, cart["id"], item_id)
                if not removed:
                    raise HTTPException(status_code=404, detail="Cart item not found")
                return await self._format_cart(conn, cart)

    async def checkout_all(self, *, user_id: UUID, role: UserRole) -> dict:
        """Check out every OPEN cart the client has across all their
        companies in one go — the backend half of a header "Pay All" action.
        Each company still gets its own cart/payment row (the schema ties a
        payment to exactly one cart), but the client only has to act once."""
        async with self._pool.acquire() as conn:
            company_ids = await cart_repo.list_open_company_ids_for_user(conn, user_id)

        results = [
            await self.checkout(company_id=cid, user_id=user_id, role=role)
            for cid in company_ids
        ]
        if not results:
            raise HTTPException(status_code=404, detail="No open carts to check out")
        return {
            "payments": results,
            "total_amount_ngn": sum(r["total_amount_ngn"] for r in results),
        }

    async def initialize_all_payments(self, *, user_id: UUID, role: UserRole) -> dict:
        """One combined Paystack charge covering every pending (CHECKOUT)
        payment across all the client's companies. All of those payment rows
        get stamped with the same provider reference so the webhook can
        finalize each of them once the single charge succeeds."""
        async with self._pool.acquire() as conn:
            pending = await cart_repo.list_pending_payments_for_user(conn, user_id)
            if not pending:
                raise HTTPException(status_code=404, detail="No pending payments to pay")

            total = sum(Decimal(str(p["total_amount_ngn"])) for p in pending)
            payment_ids = [p["payment_id"] for p in pending]

            user = await conn.fetchrow("SELECT email FROM users WHERE id = $1", user_id)
            if user is None:
                raise HTTPException(status_code=404, detail="User not found")

            if settings_payment_dev_mode():
                return {
                    "payment_ids": [str(pid) for pid in payment_ids],
                    "provider": "manual",
                    "dev_mode": True,
                    "message": "Dev/manual payment — use POST /cart/mine/pay",
                    "total_amount_ngn": float(total),
                }

            if not PaystackClient.configured():
                raise HTTPException(status_code=503, detail="Paystack is not configured")

            init = await PaystackClient.initialize_transaction(
                email=user["email"],
                amount_ngn=total,
                payment_id=str(payment_ids[0]),
                company_id="multiple",
                metadata={
                    "payment_ids": [str(pid) for pid in payment_ids],
                    "batch": True,
                },
            )
            async with conn.transaction():
                for pid in payment_ids:
                    await cart_repo.update_payment_provider(
                        conn,
                        pid,
                        provider="paystack",
                        provider_reference=init["reference"],
                        authorization_url=init["authorization_url"],
                        provider_payload=init,
                    )

            return {
                "payment_ids": [str(pid) for pid in payment_ids],
                "provider": "paystack",
                "authorization_url": init["authorization_url"],
                "reference": init["reference"],
                "public_key": settings_paystack_public_key(),
                "total_amount_ngn": float(total),
            }

    async def confirm_all_payments(
        self, *, user_id: UUID, role: UserRole, start_workflows: bool = True
    ) -> dict:
        """Dev/manual confirmation for a combined "pay all" charge — finalizes
        every pending payment across the client's companies under one shared
        server-generated reference."""
        from app.core.config import settings

        if PaystackClient.configured() and not settings.payment_dev_mode:
            raise HTTPException(
                status_code=400,
                detail="Use Paystack checkout — payment is confirmed via webhook after authorization",
            )
        if not settings.payment_dev_mode:
            raise HTTPException(
                status_code=403,
                detail="Manual payment confirmation is disabled outside dev mode",
            )

        async with self._pool.acquire() as conn:
            pending = await cart_repo.list_pending_payments_for_user(conn, user_id)
        if not pending:
            raise HTTPException(status_code=404, detail="No pending payments to pay")

        server_reference = f"DEV-{uuid.uuid4()}"
        results = [
            await self.finalize_payment(
                company_id=p["company_id"],
                user_id=user_id,
                role=role,
                payment_id=p["payment_id"],
                payment_reference=server_reference,
                start_workflows=start_workflows,
            )
            for p in pending
        ]
        return {
            "status": PaymentStatus.COMPLETED.value,
            "payment_reference": server_reference,
            "total_amount_ngn": sum(r["total_amount_ngn"] for r in results),
            "results": results,
        }

    async def checkout(
        self, *, company_id: UUID, user_id: UUID, role: UserRole
    ) -> dict:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await require_company_client(conn, company_id, user_id, role)
                cart = await cart_repo.fetch_open_cart(conn, company_id)
                if cart is None:
                    raise HTTPException(status_code=404, detail="No open cart found")

                items = await cart_repo.list_cart_items(conn, cart["id"])
                if not items:
                    raise HTTPException(status_code=400, detail="Cart is empty")

                breakdown = [
                    {
                        "compliance_type": i["compliance_type"],
                        "mode": i["mode"],
                        "display_name": i["display_name"] or f"{i['compliance_type']} ({i['mode']})",
                        "amount_ngn": float(i["unit_price_ngn"]),
                    }
                    for i in items
                ]
                total = sum(Decimal(str(line["amount_ngn"])) for line in breakdown)

                await cart_repo.update_cart_status(conn, cart["id"], CartStatus.CHECKOUT.value)
                payment = await cart_repo.insert_payment(
                    conn,
                    cart["id"],
                    total,
                    breakdown,
                    status=PaymentStatus.PENDING.value,
                )

                return {
                    "cart_id": str(cart["id"]),
                    "payment_id": str(payment["id"]),
                    "status": CartStatus.CHECKOUT.value,
                    "breakdown": breakdown,
                    "total_amount_ngn": float(total),
                    "paystack_configured": PaystackClient.configured(),
                    "payment_dev_mode": settings_payment_dev_mode(),
                }

    async def initialize_payment(
        self,
        *,
        company_id: UUID,
        user_id: UUID,
        role: UserRole,
        payment_id: UUID,
    ) -> dict:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await require_company_client(conn, company_id, user_id, role)

                payment = await cart_repo.fetch_payment_by_id(conn, payment_id)
                if payment is None:
                    raise HTTPException(status_code=404, detail="Payment not found")
                if payment["status"] != PaymentStatus.PENDING.value:
                    raise HTTPException(status_code=400, detail="Payment is not pending")

                # Resolve the cart from the payment itself rather than
                # guessing "the" CHECKOUT cart for this company — a company
                # can have more than one cart mid-checkout at once (e.g. new
                # items started while an earlier payment is still pending),
                # and picking the wrong one used to reject a valid payment.
                cart = await cart_repo.fetch_cart_by_id(conn, payment["cart_id"])
                if cart is None or str(cart["company_id"]) != str(company_id):
                    raise HTTPException(status_code=400, detail="Payment does not belong to this company")
                if cart["status"] != CartStatus.CHECKOUT.value:
                    raise HTTPException(status_code=400, detail="Cart is not in checkout")

                user = await conn.fetchrow(
                    "SELECT email FROM users WHERE id = $1",
                    user_id,
                )
                if user is None:
                    raise HTTPException(status_code=404, detail="User not found")

                # Dev mode always skips live Paystack (even if a placeholder secret is set).
                if settings_payment_dev_mode():
                    return {
                        "payment_id": str(payment_id),
                        "provider": "manual",
                        "dev_mode": True,
                        "message": "Dev/manual payment — use POST /cart/companies/{id}/pay with a payment_reference",
                        "total_amount_ngn": float(payment["total_amount_ngn"]),
                    }

                if not PaystackClient.configured():
                    raise HTTPException(status_code=503, detail="Paystack is not configured")

                company = await conn.fetchrow(
                    "SELECT name FROM companies WHERE id = $1",
                    company_id,
                )
                init = await PaystackClient.initialize_transaction(
                    email=user["email"],
                    amount_ngn=Decimal(str(payment["total_amount_ngn"])),
                    payment_id=str(payment_id),
                    company_id=str(company_id),
                    metadata={"company_name": company["name"] if company else None},
                )
                await cart_repo.update_payment_provider(
                    conn,
                    payment_id,
                    provider="paystack",
                    provider_reference=init["reference"],
                    authorization_url=init["authorization_url"],
                    provider_payload=init,
                )

                return {
                    "payment_id": str(payment_id),
                    "provider": "paystack",
                    "authorization_url": init["authorization_url"],
                    "reference": init["reference"],
                    "public_key": settings_paystack_public_key(),
                    "total_amount_ngn": float(payment["total_amount_ngn"]),
                }

    async def confirm_payment(
        self,
        *,
        company_id: UUID,
        user_id: UUID,
        role: UserRole,
        payment_id: UUID,
        payment_reference: str | None = None,
        start_workflows: bool = True,
    ) -> dict:
        from app.core.config import settings

        if PaystackClient.configured() and not settings.payment_dev_mode:
            raise HTTPException(
                status_code=400,
                detail="Use Paystack checkout — payment is confirmed via webhook after authorization",
            )
        if not settings.payment_dev_mode:
            raise HTTPException(
                status_code=403,
                detail="Manual payment confirmation is disabled outside dev mode",
            )
        # Compliance audit finding PF-2: never trust a client-supplied payment
        # reference — it is generated server-side even in the manual/dev-mode path.
        server_reference = f"DEV-{uuid.uuid4()}"
        return await self.finalize_payment(
            company_id=company_id,
            user_id=user_id,
            role=role,
            payment_id=payment_id,
            payment_reference=server_reference,
            start_workflows=start_workflows,
        )

    async def finalize_payment_from_webhook(
        self,
        *,
        payment_id: UUID,
        payment_reference: str,
        start_workflows: bool = True,
    ) -> dict | None:
        """Finalize payment without client auth (Paystack webhook). Returns None if already completed."""
        async with self._pool.acquire() as conn:
            payment = await cart_repo.fetch_payment_by_id(conn, payment_id)
            if payment is None:
                raise HTTPException(status_code=404, detail="Payment not found")
            if payment["status"] == PaymentStatus.COMPLETED.value:
                return None
            cart = await cart_repo.fetch_cart_by_id(conn, payment["cart_id"])
            if cart is None:
                raise HTTPException(status_code=404, detail="Cart not found")
            company_id = cart["company_id"]
            user_id = cart["user_id"]

        return await self.finalize_payment(
            company_id=company_id,
            user_id=user_id,
            role=UserRole.CLIENT,
            payment_id=payment_id,
            payment_reference=payment_reference,
            start_workflows=start_workflows,
            skip_client_check=True,
        )

    async def finalize_payment(
        self,
        *,
        company_id: UUID,
        user_id: UUID,
        role: UserRole,
        payment_id: UUID,
        payment_reference: str,
        start_workflows: bool = True,
        skip_client_check: bool = False,
    ) -> dict:
        workflow_svc = WorkflowService(self._pool)
        started: list[dict] = []
        owner_email: str | None = None
        company_name: str | None = None

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                if not skip_client_check:
                    await require_company_client(conn, company_id, user_id, role)

                payment = await cart_repo.complete_payment(conn, payment_id, payment_reference)
                if payment is None:
                    existing = await cart_repo.fetch_payment_by_id(conn, payment_id)
                    if existing and existing["status"] == PaymentStatus.COMPLETED.value:
                        raise HTTPException(status_code=409, detail="Payment already completed")
                    raise HTTPException(status_code=404, detail="Payment not found")

                # Resolve the cart from the payment itself rather than
                # guessing "the" CHECKOUT cart for this company — see the
                # matching note in initialize_payment above for why.
                cart = await cart_repo.fetch_cart_by_id(conn, payment["cart_id"])
                if cart is None or str(cart["company_id"]) != str(company_id):
                    raise HTTPException(status_code=400, detail="Payment does not belong to this company")
                if cart["status"] != CartStatus.CHECKOUT.value:
                    raise HTTPException(status_code=400, detail="Cart is not in checkout")

                await cart_repo.update_cart_status(conn, cart["id"], CartStatus.PAID.value)
                items = await cart_repo.list_cart_items(conn, cart["id"])
                await entitlements_repo.create_entitlements_for_cart_items(
                    conn,
                    company_id=company_id,
                    payment_id=payment_id,
                    items=items,
                )

                owner = await conn.fetchrow(
                    """
                    SELECT u.email, c.name
                    FROM companies c
                    JOIN users u ON u.id = c.user_id
                    WHERE c.id = $1
                    """,
                    company_id,
                )
                if owner:
                    owner_email = owner["email"]
                    company_name = owner["name"]

        if start_workflows:
            for item in items:
                ct = ComplianceType(item["compliance_type"])
                mode = ComplianceMode(item["mode"])
                row = await workflow_svc.start(
                    company_id=company_id,
                    user_id=user_id,
                    role=role,
                    compliance_type=ct,
                    mode=mode,
                )
                started.append(
                    {
                        "compliance_type": row["compliance_type"],
                        "mode": row["mode"],
                        "workflow_id": str(row["id"]),
                        "status": row["status"],
                    }
                )

        # Always mark Make payment complete for paid cart lines (pay-before or pay-after fill).
        for item in items:
            ct = ComplianceType(item["compliance_type"])
            mode = ComplianceMode(item["mode"])
            await workflow_svc.mark_make_payment_complete(
                company_id=company_id,
                user_id=user_id,
                role=role,
                compliance_type=ct,
                mode=mode,
                payment_reference=payment_reference,
                payment_amount=float(item["unit_price_ngn"]),
                ensure_started=True,
            )

        # The client can only reach "Pay Now" once every step/document is
        # already filled in, so paying is the last real gate — auto-submit
        # each paid compliance straight into IN_REVIEW instead of making the
        # client come back and click a separate "Submit for review" button.
        # If a cross-compliance requirement still blocks it, the entitlement
        # stays unconsumed and it's submitted normally once that's resolved.
        submitted: list[dict] = []
        for item in items:
            ct = ComplianceType(item["compliance_type"])
            mode = ComplianceMode(item["mode"])
            try:
                submitted.append(
                    await workflow_svc.submit(
                        company_id=company_id,
                        user_id=user_id,
                        role=role,
                        compliance_type=ct,
                        mode=mode,
                        expiry_date=None,
                    )
                )
            except HTTPException:
                continue

        breakdown = payment["breakdown"] if isinstance(payment["breakdown"], list) else json.loads(payment["breakdown"])

        NotificationService.emit(
            "payment.completed",
            {
                "company_id": str(company_id),
                "company_name": company_name,
                "owner_email": owner_email,
                "payment_id": str(payment_id),
                "payment_reference": payment_reference,
                "total_amount_ngn": float(payment["total_amount_ngn"]),
                "breakdown": breakdown,
                "workflows_started": started,
                "submitted_for_review": submitted,
            },
        )

        return {
            "cart_id": str(cart["id"]),
            "payment_id": str(payment["id"]),
            "payment_reference": payment["payment_reference"],
            "status": PaymentStatus.COMPLETED.value,
            "total_amount_ngn": float(payment["total_amount_ngn"]),
            "breakdown": breakdown,
            "workflows_started": started,
            "submitted_for_review": submitted,
        }

    async def _format_cart(self, conn: asyncpg.Connection, cart: asyncpg.Record) -> dict:
        items = await cart_repo.list_cart_items(conn, cart["id"])
        subtotal = sum(Decimal(str(i["unit_price_ngn"])) for i in items)
        return {
            "company_id": str(cart["company_id"]),
            "cart": {
                "id": str(cart["id"]),
                "status": cart["status"],
                "created_at": cart["created_at"].isoformat(),
                "updated_at": cart["updated_at"].isoformat(),
            },
            "items": [
                {
                    "id": str(i["id"]),
                    "compliance_type": i["compliance_type"],
                    "mode": i["mode"],
                    "display_name": i["display_name"],
                    "description": i["description"],
                    "icon_key": i["icon_key"],
                    "category_slug": i["category_slug"],
                    "category_name": i["category_name"],
                    "unit_price_ngn": float(i["unit_price_ngn"]),
                    "added_at": i["added_at"].isoformat(),
                }
                for i in items
            ],
            "subtotal_ngn": float(subtotal),
        }


def settings_payment_dev_mode() -> bool:
    from app.core.config import settings

    return settings.payment_dev_mode


def settings_paystack_public_key() -> str:
    from app.core.config import settings

    return settings.paystack_public_key
