from uuid import UUID

import asyncpg


async def list_categories(conn: asyncpg.Connection, *, active_only: bool = True) -> list[asyncpg.Record]:
    if active_only:
        return await conn.fetch(
            """
            SELECT id, slug, name, description, display_order, is_active, created_at
            FROM compliance_categories
            WHERE is_active = TRUE
            ORDER BY display_order, name
            """
        )
    return await conn.fetch(
        """
        SELECT id, slug, name, description, display_order, is_active, created_at
        FROM compliance_categories
        ORDER BY display_order, name
        """
    )


async def fetch_category_by_slug(conn: asyncpg.Connection, slug: str) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT id, slug, name, description, display_order, is_active, created_at
        FROM compliance_categories
        WHERE slug = $1 AND is_active = TRUE
        """,
        slug,
    )


async def list_catalog_items(
    conn: asyncpg.Connection,
    *,
    category_slug: str | None = None,
    active_only: bool = True,
) -> list[asyncpg.Record]:
    clauses = ["TRUE"]
    args: list = []
    idx = 1

    if active_only:
        clauses.append("c.is_active = TRUE")
        clauses.append("cat.is_active = TRUE")

    if category_slug is not None:
        clauses.append(f"cat.slug = ${idx}")
        args.append(category_slug)
        idx += 1

    where = " AND ".join(clauses)
    return await conn.fetch(
        f"""
        SELECT
            c.id,
            c.compliance_type::text AS compliance_type,
            c.mode::text AS mode,
            c.display_name,
            c.description,
            c.icon_key,
            c.base_price_ngn,
            c.is_active,
            c.regulator_name,
            c.display_order,
            c.is_system,
            cat.id AS category_id,
            cat.slug AS category_slug,
            cat.name AS category_name
        FROM compliance_catalog c
        JOIN compliance_categories cat ON cat.id = c.category_id
        WHERE {where}
        ORDER BY c.display_order, c.display_name
        """,
        *args,
    )


async def fetch_catalog_item(
    conn: asyncpg.Connection,
    compliance_type: str,
    mode: str,
) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT
            c.id,
            c.compliance_type::text AS compliance_type,
            c.mode::text AS mode,
            c.display_name,
            c.description,
            c.icon_key,
            c.base_price_ngn,
            c.is_active,
            c.regulator_name,
            c.display_order,
            c.is_system,
            cat.id AS category_id,
            cat.slug AS category_slug,
            cat.name AS category_name
        FROM compliance_catalog c
        JOIN compliance_categories cat ON cat.id = c.category_id
        WHERE c.compliance_type = $1::compliance_type
          AND c.mode = $2::compliance_mode
          AND c.is_active = TRUE
        """,
        compliance_type,
        mode,
    )


async def fetch_catalog_item_admin(
    conn: asyncpg.Connection,
    compliance_type: str,
    mode: str,
) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT
            c.id,
            c.compliance_type::text AS compliance_type,
            c.mode::text AS mode,
            c.display_name,
            c.description,
            c.icon_key,
            c.base_price_ngn,
            c.is_active,
            c.regulator_name,
            c.display_order,
            c.is_system,
            cat.id AS category_id,
            cat.slug AS category_slug,
            cat.name AS category_name
        FROM compliance_catalog c
        JOIN compliance_categories cat ON cat.id = c.category_id
        WHERE c.compliance_type = $1::compliance_type
          AND c.mode = $2::compliance_mode
        """,
        compliance_type,
        mode,
    )


async def update_catalog_item(
    conn: asyncpg.Connection,
    compliance_type: str,
    mode: str,
    *,
    base_price_ngn: object | None = None,
    display_name: str | None = None,
    description: str | None = None,
    icon_key: str | None = None,
    is_active: bool | None = None,
) -> asyncpg.Record | None:
    sets: list[str] = []
    args: list[object] = [compliance_type, mode]
    idx = 3

    if base_price_ngn is not None:
        sets.append(f"base_price_ngn = ${idx}")
        args.append(base_price_ngn)
        idx += 1
    if display_name is not None:
        sets.append(f"display_name = ${idx}")
        args.append(display_name)
        idx += 1
    if description is not None:
        sets.append(f"description = ${idx}")
        args.append(description)
        idx += 1
    if icon_key is not None:
        sets.append(f"icon_key = ${idx}")
        args.append(icon_key)
        idx += 1
    if is_active is not None:
        sets.append(f"is_active = ${idx}")
        args.append(is_active)
        idx += 1

    if not sets:
        return await fetch_catalog_item_admin(conn, compliance_type, mode)

    return await conn.fetchrow(
        f"""
        UPDATE compliance_catalog
        SET {", ".join(sets)}
        WHERE compliance_type = $1::compliance_type
          AND mode = $2::compliance_mode
        RETURNING
            id,
            compliance_type::text AS compliance_type,
            mode::text AS mode,
            display_name,
            description,
            icon_key,
            base_price_ngn,
            is_active,
            category_id
        """,
        *args,
    )
