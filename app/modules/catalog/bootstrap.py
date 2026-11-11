import logging

import asyncpg

from app.modules.catalog.seed import CATALOG_SEED, CATEGORY_SEED

logger = logging.getLogger(__name__)


async def seed_compliance_catalog(conn: asyncpg.Connection) -> int:
    """Insert built-in categories and compliances that are missing.

    Existing rows are never overwritten: the admin dashboard owns them from then on.
    """
    for row in CATEGORY_SEED:
        await conn.execute(
            """
            INSERT INTO compliance_categories (slug, name, description, display_order)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (slug) DO NOTHING
            """,
            row["slug"],
            row["name"],
            row["description"],
            row["display_order"],
        )

    count = 0
    for item in CATALOG_SEED:
        result = await conn.execute(
            """
            INSERT INTO compliance_catalog (
                compliance_type, mode, category_id, display_name, description,
                icon_key, base_price_ngn, is_active, regulator_name, display_order, is_system
            )
            SELECT
                $1::compliance_type, $2::compliance_mode, cat.id,
                $4, $5, $6, $7, $8, $9, $10, TRUE
            FROM compliance_categories cat
            WHERE cat.slug = $3
            ON CONFLICT (compliance_type, mode) DO NOTHING
            """,
            item["compliance_type"].value,
            item["mode"].value,
            item["category_slug"],
            item["display_name"],
            item["description"],
            item["icon_key"],
            item["base_price_ngn"],
            item["is_active"],
            item["regulator_name"],
            item["display_order"],
        )
        if result.endswith(" 1"):
            count += 1
    if count:
        logger.info("Added %s built-in compliance catalog item(s)", count)
    return count
