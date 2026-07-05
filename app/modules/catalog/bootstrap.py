import logging

import asyncpg

from app.modules.catalog.seed import CATALOG_SEED, CATEGORY_SEED

logger = logging.getLogger(__name__)


async def seed_compliance_catalog(conn: asyncpg.Connection) -> int:
    category_ids: dict[str, str] = {}
    for row in CATEGORY_SEED:
        record = await conn.fetchrow(
            """
            INSERT INTO compliance_categories (slug, name, description, display_order)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (slug) DO UPDATE SET
                name = EXCLUDED.name,
                description = EXCLUDED.description,
                display_order = EXCLUDED.display_order
            RETURNING id
            """,
            row["slug"],
            row["name"],
            row["description"],
            row["display_order"],
        )
        assert record is not None
        category_ids[row["slug"]] = str(record["id"])

    count = 0
    for item in CATALOG_SEED:
        category_id = category_ids[item["category_slug"]]
        result = await conn.execute(
            """
            INSERT INTO compliance_catalog (
                compliance_type, mode, category_id, display_name, description,
                icon_key, base_price_ngn
            )
            VALUES (
                $1::compliance_type, $2::compliance_mode, $3::uuid,
                $4, $5, $6, $7
            )
            ON CONFLICT (compliance_type, mode) DO UPDATE SET
                category_id = EXCLUDED.category_id,
                display_name = EXCLUDED.display_name,
                description = EXCLUDED.description,
                icon_key = EXCLUDED.icon_key,
                base_price_ngn = EXCLUDED.base_price_ngn
            """,
            item["compliance_type"].value,
            item["mode"].value,
            category_id,
            item["display_name"],
            item["description"],
            item["icon_key"],
            item["base_price_ngn"],
        )
        if result.endswith("1"):
            count += 1
    logger.info("Seeded/updated %s compliance catalog items", count)
    return count
