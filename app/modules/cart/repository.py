from decimal import Decimal
from uuid import UUID

import asyncpg


async def fetch_open_cart(
    conn: asyncpg.Connection, company_id: UUID
) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT id, company_id, user_id, status::text AS status,
               created_at, updated_at
        FROM compliance_carts
        WHERE company_id = $1 AND status = 'OPEN'::cart_status
        """,
        company_id,
    )


async def fetch_checkout_cart(
    conn: asyncpg.Connection, company_id: UUID
) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT id, company_id, user_id, status::text AS status,
               created_at, updated_at
        FROM compliance_carts
        WHERE company_id = $1 AND status = 'CHECKOUT'::cart_status
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        company_id,
    )


async def create_cart(
    conn: asyncpg.Connection, company_id: UUID, user_id: UUID
) -> asyncpg.Record:
    row = await conn.fetchrow(
        """
        INSERT INTO compliance_carts (company_id, user_id, status)
        VALUES ($1, $2, 'OPEN'::cart_status)
        RETURNING id, company_id, user_id, status::text AS status, created_at, updated_at
        """,
        company_id,
        user_id,
    )
    assert row is not None
    return row


async def fetch_cart_by_id(
    conn: asyncpg.Connection, cart_id: UUID
) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT id, company_id, user_id, status::text AS status, created_at, updated_at
        FROM compliance_carts
        WHERE id = $1
        """,
        cart_id,
    )


async def list_cart_items(conn: asyncpg.Connection, cart_id: UUID) -> list[asyncpg.Record]:
    return await conn.fetch(
        """
        SELECT
            ci.id,
            ci.compliance_type::text AS compliance_type,
            ci.mode::text AS mode,
            ci.unit_price_ngn,
            ci.added_at,
            cc.display_name,
            cc.description,
            cc.icon_key,
            cat.slug AS category_slug,
            cat.name AS category_name
        FROM compliance_cart_items ci
        LEFT JOIN compliance_catalog cc
          ON cc.compliance_type = ci.compliance_type AND cc.mode = ci.mode
        LEFT JOIN compliance_categories cat ON cat.id = cc.category_id
        WHERE ci.cart_id = $1
        ORDER BY ci.added_at
        """,
        cart_id,
    )


async def add_cart_item(
    conn: asyncpg.Connection,
    cart_id: UUID,
    compliance_type: str,
    mode: str,
    unit_price_ngn: Decimal,
) -> asyncpg.Record:
    row = await conn.fetchrow(
        """
        INSERT INTO compliance_cart_items (cart_id, compliance_type, mode, unit_price_ngn)
        VALUES ($1, $2::compliance_type, $3::compliance_mode, $4)
        ON CONFLICT (cart_id, compliance_type, mode) DO UPDATE SET
            unit_price_ngn = EXCLUDED.unit_price_ngn
        RETURNING id, compliance_type::text AS compliance_type, mode::text AS mode,
                  unit_price_ngn, added_at
        """,
        cart_id,
        compliance_type,
        mode,
        unit_price_ngn,
    )
    assert row is not None
    return row


async def remove_cart_item(
    conn: asyncpg.Connection, cart_id: UUID, item_id: UUID
) -> bool:
    result = await conn.execute(
        """
        DELETE FROM compliance_cart_items
        WHERE id = $1 AND cart_id = $2
        """,
        item_id,
        cart_id,
    )
    return result.endswith("1")


async def update_cart_status(
    conn: asyncpg.Connection, cart_id: UUID, status: str
) -> None:
    await conn.execute(
        """
        UPDATE compliance_carts
        SET status = $2::cart_status, updated_at = NOW()
        WHERE id = $1
        """,
        cart_id,
        status,
    )


async def insert_payment(
    conn: asyncpg.Connection,
    cart_id: UUID,
    total_amount_ngn: Decimal,
    breakdown: list[dict],
    payment_reference: str | None = None,
    status: str = "PENDING",
) -> asyncpg.Record:
    import json

    row = await conn.fetchrow(
        """
        INSERT INTO compliance_payments (
            cart_id, payment_reference, total_amount_ngn, status, breakdown
        )
        VALUES ($1, $2, $3, $4::payment_status, $5::jsonb)
        RETURNING id, cart_id, payment_reference, total_amount_ngn,
                  status::text AS status, breakdown, paid_at, created_at
        """,
        cart_id,
        payment_reference,
        total_amount_ngn,
        status,
        json.dumps(breakdown),
    )
    assert row is not None
    return row


async def complete_payment(
    conn: asyncpg.Connection, payment_id: UUID, payment_reference: str
) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        UPDATE compliance_payments
        SET status = 'COMPLETED'::payment_status,
            payment_reference = $2,
            paid_at = NOW()
        WHERE id = $1 AND status = 'PENDING'::payment_status
        RETURNING id, cart_id, payment_reference, total_amount_ngn,
                  status::text AS status, breakdown, paid_at, created_at,
                  provider, provider_reference, authorization_url
        """,
        payment_id,
        payment_reference,
    )


async def fetch_payment_by_id(
    conn: asyncpg.Connection, payment_id: UUID
) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT id, cart_id, payment_reference, total_amount_ngn,
               status::text AS status, breakdown, paid_at, created_at,
               provider, provider_reference, authorization_url
        FROM compliance_payments
        WHERE id = $1
        """,
        payment_id,
    )


async def fetch_payment_by_provider_reference(
    conn: asyncpg.Connection, provider_reference: str
) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT id, cart_id, payment_reference, total_amount_ngn,
               status::text AS status, breakdown, paid_at, created_at,
               provider, provider_reference, authorization_url
        FROM compliance_payments
        WHERE provider_reference = $1
        """,
        provider_reference,
    )


async def update_payment_provider(
    conn: asyncpg.Connection,
    payment_id: UUID,
    *,
    provider: str,
    provider_reference: str,
    authorization_url: str | None = None,
    provider_payload: dict | None = None,
) -> asyncpg.Record | None:
    import json

    return await conn.fetchrow(
        """
        UPDATE compliance_payments
        SET provider = $2,
            provider_reference = $3,
            authorization_url = $4,
            provider_payload = COALESCE($5::jsonb, provider_payload)
        WHERE id = $1
        RETURNING id, cart_id, payment_reference, total_amount_ngn,
                  status::text AS status, breakdown, paid_at, created_at,
                  provider, provider_reference, authorization_url
        """,
        payment_id,
        provider,
        provider_reference,
        authorization_url,
        json.dumps(provider_payload) if provider_payload else None,
    )


async def fetch_latest_payment(conn: asyncpg.Connection, cart_id: UUID) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT id, cart_id, payment_reference, total_amount_ngn,
               status::text AS status, breakdown, paid_at, created_at
        FROM compliance_payments
        WHERE cart_id = $1
        ORDER BY created_at DESC
        LIMIT 1
        """,
        cart_id,
    )
