import json
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
                cart = await conn.fetchrow(
                    """
                    SELECT id, status::text AS status
                    FROM compliance_carts
                    WHERE company_id = $1 AND status = 'CHECKOUT'::cart_status
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    company_id,
                )
                if cart is None:
                    raise HTTPException(status_code=404, detail="No cart in checkout")

                payment = await cart_repo.fetch_payment_by_id(conn, payment_id)
                if payment is None:
                    raise HTTPException(status_code=404, detail="Payment not found")
                if str(payment["cart_id"]) != str(cart["id"]):
                    raise HTTPException(status_code=400, detail="Payment does not belong to active cart")
                if payment["status"] != PaymentStatus.PENDING.value:
                    raise HTTPException(status_code=400, detail="Payment is not pending")

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
        payment_reference: str,
        start_workflows: bool = True,
    ) -> dict:
        from app.core.config import settings

        if PaystackClient.configured() and not settings.payment_dev_mode:
            raise HTTPException(
                status_code=400,
                detail="Use Paystack checkout — payment is confirmed via webhook after authorization",
            )
        return await self.finalize_payment(
            company_id=company_id,
            user_id=user_id,
            role=role,
            payment_id=payment_id,
            payment_reference=payment_reference,
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
                cart = await conn.fetchrow(
                    """
                    SELECT id, status::text AS status
                    FROM compliance_carts
                    WHERE company_id = $1 AND status = 'CHECKOUT'::cart_status
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    company_id,
                )
                if cart is None:
                    raise HTTPException(status_code=404, detail="No cart in checkout")

                payment = await cart_repo.complete_payment(conn, payment_id, payment_reference)
                if payment is None:
                    existing = await cart_repo.fetch_payment_by_id(conn, payment_id)
                    if existing and existing["status"] == PaymentStatus.COMPLETED.value:
                        raise HTTPException(status_code=409, detail="Payment already completed")
                    raise HTTPException(status_code=404, detail="Payment not found")

                if str(payment["cart_id"]) != str(cart["id"]):
                    raise HTTPException(status_code=400, detail="Payment does not belong to active cart")

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
