from decimal import Decimal
from uuid import UUID

import asyncpg


async def create_entitlements_for_cart_items(
    conn: asyncpg.Connection,
    *,
    company_id: UUID,
    payment_id: UUID,
    items: list[asyncpg.Record],
) -> int:
    """Idempotent: one entitlement row per cart line item after payment completes."""
    existing = await conn.fetchval(
        "SELECT 1 FROM compliance_entitlements WHERE payment_id = $1 LIMIT 1",
        payment_id,
    )
    if existing:
        return 0

    created = 0
    for item in items:
        await conn.execute(
            """
            INSERT INTO compliance_entitlements (
                company_id, compliance_type, mode, payment_id, amount_ngn
            )
            VALUES ($1, $2::compliance_type, $3::compliance_mode, $4, $5)
            """,
            company_id,
            item["compliance_type"],
            item["mode"],
            payment_id,
            Decimal(str(item["unit_price_ngn"])),
        )
        created += 1
    return created


async def fetch_unconsumed_entitlement(
    conn: asyncpg.Connection,
    *,
    company_id: UUID,
    compliance_type: str,
    mode: str,
) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT e.id, e.company_id, e.compliance_type::text AS compliance_type,
               e.mode::text AS mode, e.payment_id, e.amount_ngn, e.paid_at
        FROM compliance_entitlements e
        JOIN compliance_payments p ON p.id = e.payment_id
        WHERE e.company_id = $1
          AND e.compliance_type = $2::compliance_type
          AND e.mode = $3::compliance_mode
          AND e.consumed_at IS NULL
          AND p.status = 'COMPLETED'::payment_status
        ORDER BY e.paid_at DESC
        LIMIT 1
        """,
        company_id,
        compliance_type,
        mode,
    )


async def fetch_payment_entitlement(
    conn: asyncpg.Connection,
    *,
    company_id: UUID,
    compliance_type: str,
    mode: str,
) -> asyncpg.Record | None:
    """Any completed-payment entitlement (consumed or not) — used for is_paid."""
    return await conn.fetchrow(
        """
        SELECT e.id, e.company_id, e.compliance_type::text AS compliance_type,
               e.mode::text AS mode, e.payment_id, e.amount_ngn, e.paid_at,
               e.consumed_at, e.workflow_id,
               p.payment_reference
        FROM compliance_entitlements e
        JOIN compliance_payments p ON p.id = e.payment_id
        WHERE e.company_id = $1
          AND e.compliance_type = $2::compliance_type
          AND e.mode = $3::compliance_mode
          AND p.status = 'COMPLETED'::payment_status
        ORDER BY e.paid_at DESC
        LIMIT 1
        """,
        company_id,
        compliance_type,
        mode,
    )


async def consume_entitlement(
    conn: asyncpg.Connection,
    *,
    entitlement_id: UUID,
    workflow_id: UUID,
) -> bool:
    result = await conn.execute(
        """
        UPDATE compliance_entitlements
        SET consumed_at = NOW(), workflow_id = $2
        WHERE id = $1 AND consumed_at IS NULL
        """,
        entitlement_id,
        workflow_id,
    )
    return result.endswith("1")
