from decimal import Decimal

import asyncpg
from fastapi import HTTPException

from app.modules.catalog import repository as catalog_repo


class CatalogService:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def list_categories(self) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await catalog_repo.list_categories(conn)
            return [
                {
                    "id": str(r["id"]),
                    "slug": r["slug"],
                    "name": r["name"],
                    "description": r["description"],
                    "display_order": r["display_order"],
                }
                for r in rows
            ]

    async def list_items(self, *, category: str | None = None) -> dict:
        async with self._pool.acquire() as conn:
            if category and category.lower() != "all":
                cat = await catalog_repo.fetch_category_by_slug(conn, category)
                if cat is None:
                    raise HTTPException(status_code=404, detail="Category not found")
            rows = await catalog_repo.list_catalog_items(conn, category_slug=None if not category or category.lower() == "all" else category)
            items = [self._format_item(r) for r in rows]
            return {
                "category_filter": category or "all",
                "count": len(items),
                "items": items,
            }

    async def get_item(self, compliance_type: str, mode: str) -> dict:
        async with self._pool.acquire() as conn:
            row = await catalog_repo.fetch_catalog_item(conn, compliance_type, mode)
            if row is None:
                raise HTTPException(status_code=404, detail="Catalog item not found")
            return self._format_item(row)

    async def list_items_admin(self, *, category: str | None = None) -> dict:
        async with self._pool.acquire() as conn:
            if category and category.lower() != "all":
                cat = await catalog_repo.fetch_category_by_slug(conn, category)
                if cat is None:
                    raise HTTPException(status_code=404, detail="Category not found")
            rows = await catalog_repo.list_catalog_items(
                conn,
                category_slug=None if not category or category.lower() == "all" else category,
                active_only=False,
            )
            items = [self._format_item(r, include_inactive=True) for r in rows]
            return {
                "category_filter": category or "all",
                "count": len(items),
                "items": items,
            }

    async def get_item_admin(self, compliance_type: str, mode: str) -> dict:
        async with self._pool.acquire() as conn:
            row = await catalog_repo.fetch_catalog_item_admin(conn, compliance_type, mode)
            if row is None:
                raise HTTPException(status_code=404, detail="Catalog item not found")
            return self._format_item(row, include_inactive=True)

    async def update_item_admin(
        self,
        compliance_type: str,
        mode: str,
        *,
        base_price_ngn: Decimal | None = None,
        display_name: str | None = None,
        description: str | None = None,
        icon_key: str | None = None,
        is_active: bool | None = None,
    ) -> dict:
        async with self._pool.acquire() as conn:
            existing = await catalog_repo.fetch_catalog_item_admin(conn, compliance_type, mode)
            if existing is None:
                raise HTTPException(status_code=404, detail="Catalog item not found")

            row = await catalog_repo.update_catalog_item(
                conn,
                compliance_type,
                mode,
                base_price_ngn=base_price_ngn,
                display_name=display_name,
                description=description,
                icon_key=icon_key,
                is_active=is_active,
            )
            assert row is not None
            full = await catalog_repo.fetch_catalog_item_admin(conn, compliance_type, mode)
            assert full is not None
            return self._format_item(full, include_inactive=True)

    @staticmethod
    def _format_item(row: asyncpg.Record, *, include_inactive: bool = False) -> dict:
        payload = {
            "id": str(row["id"]),
            "compliance_type": row["compliance_type"],
            "mode": row["mode"],
            "display_name": row["display_name"],
            "description": row["description"],
            "icon_key": row["icon_key"],
            "base_price_ngn": float(row["base_price_ngn"]),
            "category": {
                "id": str(row["category_id"]),
                "slug": row["category_slug"],
                "name": row["category_name"],
            },
        }
        if include_inactive:
            payload["is_active"] = row["is_active"]
        return payload
