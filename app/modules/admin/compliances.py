"""Admin management of compliances: create, edit, switch on/off.

A compliance is one catalog row (name, price, category, regulator, order, on/off)
plus one workflow template (steps with form fields, required documents,
dependencies). The two are always written together here.
"""

from decimal import Decimal
from typing import Any

import asyncpg
from fastapi import HTTPException

from app.domain.enums import ComplianceMode, ComplianceType
from app.modules.catalog import repository as catalog_repo
from app.modules.workflow import definitions

# Admin-created compliances have a single application, so they share one mode.
CREATED_COMPLIANCE_MODE = ComplianceMode.REGISTRATION

_UNSET: Any = object()


def _bad_request(exc: Exception) -> HTTPException:
    return HTTPException(status_code=422, detail=str(exc))


def _format(item: asyncpg.Record, definition: dict | None, open_filings: int = 0) -> dict:
    payload = {
        "id": str(item["id"]),
        "compliance_type": item["compliance_type"],
        "mode": item["mode"],
        "display_name": item["display_name"],
        "description": item["description"],
        "icon_key": item["icon_key"],
        "base_price_ngn": float(item["base_price_ngn"]),
        "regulator_name": item["regulator_name"],
        "display_order": item["display_order"],
        "is_system": item["is_system"],
        "is_active": item["is_active"],
        "category": {
            "id": str(item["category_id"]),
            "slug": item["category_slug"],
            "name": item["category_name"],
        },
        "open_filings": open_filings,
        "total_steps": 0,
        "steps": [],
        "required_documents": [],
        "depends_on": [],
    }
    if definition is not None:
        payload.update(
            total_steps=definition["total_steps"],
            steps=definition["steps"],
            required_documents=definition["required_documents"],
            depends_on=definition["depends_on"],
        )
    return payload


class ComplianceAdminService:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def meta(self) -> dict:
        """Choices the admin editor needs to build its form."""
        async with self._pool.acquire() as conn:
            categories = await catalog_repo.list_categories(conn, active_only=False)
            return {
                "field_types": list(definitions.ADMIN_FIELD_TYPES),
                "payment_step_name": definitions.MAKE_PAYMENT_STEP_NAME,
                "created_mode": CREATED_COMPLIANCE_MODE.value,
                "limits": {
                    "max_steps": definitions.MAX_STEPS,
                    "max_fields_per_step": definitions.MAX_FIELDS_PER_STEP,
                    "max_required_documents": definitions.MAX_REQUIRED_DOCUMENTS,
                },
                "categories": [
                    {"slug": c["slug"], "name": c["name"], "is_active": c["is_active"]}
                    for c in categories
                ],
            }

    async def list_all(self) -> dict:
        async with self._pool.acquire() as conn:
            items = await catalog_repo.list_catalog_items(conn, active_only=False)
            by_key = {
                (d["compliance_type"], d["mode"]): d
                for d in await definitions.list_template_definitions(conn, include_inactive=True)
            }
            open_counts = await self._open_filing_counts(conn)
            compliances = [
                _format(
                    i,
                    by_key.get((i["compliance_type"], i["mode"])),
                    open_counts.get((i["compliance_type"], i["mode"]), 0),
                )
                for i in items
            ]
            return {"count": len(compliances), "compliances": compliances}

    async def get(self, compliance_type: str, mode: str) -> dict:
        async with self._pool.acquire() as conn:
            return await self._get(conn, compliance_type, mode)

    async def create(
        self,
        *,
        display_name: str,
        code: str | None,
        category_slug: str,
        description: str | None,
        regulator_name: str | None,
        base_price_ngn: Decimal,
        is_active: bool,
        display_order: int | None,
        steps: list[dict],
        required_documents: list[dict],
        depends_on: list[dict],
    ) -> dict:
        try:
            compliance_type = ComplianceType(code or definitions.slugify_code(display_name)).value
        except ValueError as exc:
            raise _bad_request(exc) from exc
        mode = CREATED_COMPLIANCE_MODE.value

        try:
            clean_steps = definitions.normalise_steps(steps)
            clean_docs = definitions.normalise_required_documents(required_documents)
            clean_deps = definitions.normalise_depends_on(depends_on, own=(compliance_type, mode))
        except definitions.DefinitionError as exc:
            raise _bad_request(exc) from exc
        self._check_can_be_active(is_active, base_price_ngn)

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                taken = await conn.fetchval(
                    "SELECT 1 FROM compliance_catalog WHERE compliance_type = $1::compliance_type LIMIT 1",
                    compliance_type,
                )
                if taken:
                    raise HTTPException(
                        status_code=409,
                        detail=f"A compliance with the code {compliance_type} already exists",
                    )
                category = await self._category(conn, category_slug)
                await self._check_dependencies(conn, compliance_type, clean_deps)

                if display_order is None:
                    # After the last on-sale compliance, before the retired block (900+).
                    display_order = await conn.fetchval(
                        "SELECT COALESCE(MAX(display_order), 0) + 10 FROM compliance_catalog WHERE display_order < 900"
                    )

                await conn.execute(
                    """
                    INSERT INTO compliance_catalog (
                        compliance_type, mode, category_id, display_name, description, icon_key,
                        base_price_ngn, is_active, regulator_name, display_order, is_system
                    )
                    VALUES ($1::compliance_type, $2::compliance_mode, $3, $4, $5, $6, $7, $8, $9, $10, FALSE)
                    """,
                    compliance_type,
                    mode,
                    category["id"],
                    display_name.strip(),
                    (description or "").strip() or None,
                    "generic",
                    base_price_ngn,
                    is_active,
                    (regulator_name or "").strip() or None,
                    display_order,
                )
                await definitions.save_template_definition(
                    conn,
                    compliance_type,
                    mode,
                    steps=clean_steps,
                    required_documents=clean_docs,
                    depends_on=clean_deps,
                    is_active=is_active,
                )
                return await self._get(conn, compliance_type, mode)

    async def update(
        self,
        compliance_type: str,
        mode: str,
        *,
        display_name: str | None = None,
        category_slug: str | None = None,
        description: Any = _UNSET,
        regulator_name: Any = _UNSET,
        base_price_ngn: Decimal | None = None,
        is_active: bool | None = None,
        display_order: int | None = None,
        steps: list[dict] | None = None,
        required_documents: list[dict] | None = None,
        depends_on: list[dict] | None = None,
    ) -> dict:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                item = await catalog_repo.fetch_catalog_item_admin(conn, compliance_type, mode)
                if item is None:
                    raise HTTPException(status_code=404, detail="Compliance not found")
                current = await definitions.load_template_definition(
                    conn, compliance_type, mode, include_inactive=True
                )

                try:
                    # Built-in steps may keep the "json" fields their bespoke screens use.
                    clean_steps = (
                        definitions.normalise_steps(steps, allow_json=item["is_system"])
                        if steps is not None
                        else (current["steps"] if current else None)
                    )
                    clean_docs = (
                        definitions.normalise_required_documents(required_documents)
                        if required_documents is not None
                        else (current["required_documents"] if current else [])
                    )
                    clean_deps = (
                        definitions.normalise_depends_on(depends_on, own=(compliance_type, mode))
                        if depends_on is not None
                        else (current["depends_on"] if current else [])
                    )
                except definitions.DefinitionError as exc:
                    raise _bad_request(exc) from exc
                if clean_steps is None:
                    raise HTTPException(
                        status_code=422, detail="This compliance has no steps yet; provide steps"
                    )
                if depends_on is not None:
                    await self._check_dependencies(conn, compliance_type, clean_deps)

                new_active = item["is_active"] if is_active is None else is_active
                new_price = item["base_price_ngn"] if base_price_ngn is None else base_price_ngn
                self._check_can_be_active(new_active, new_price)

                sets: dict[str, Any] = {}
                if display_name is not None:
                    sets["display_name"] = display_name.strip()
                if category_slug is not None:
                    sets["category_id"] = (await self._category(conn, category_slug))["id"]
                if description is not _UNSET:
                    sets["description"] = (description or "").strip() or None
                if regulator_name is not _UNSET:
                    sets["regulator_name"] = (regulator_name or "").strip() or None
                if base_price_ngn is not None:
                    sets["base_price_ngn"] = base_price_ngn
                if is_active is not None:
                    sets["is_active"] = is_active
                if display_order is not None:
                    sets["display_order"] = display_order
                if sets:
                    columns = list(sets)
                    assignments = ", ".join(f"{c} = ${i}" for i, c in enumerate(columns, start=3))
                    await conn.execute(
                        f"""
                        UPDATE compliance_catalog SET {assignments}
                        WHERE compliance_type = $1::compliance_type AND mode = $2::compliance_mode
                        """,
                        compliance_type,
                        mode,
                        *[sets[c] for c in columns],
                    )

                await definitions.save_template_definition(
                    conn,
                    compliance_type,
                    mode,
                    steps=clean_steps,
                    required_documents=clean_docs,
                    depends_on=clean_deps,
                    is_active=new_active,
                )
                return await self._get(conn, compliance_type, mode)

    # ── helpers ───────────────────────────────────────────────────────────────

    async def _get(self, conn: asyncpg.Connection, compliance_type: str, mode: str) -> dict:
        item = await catalog_repo.fetch_catalog_item_admin(conn, compliance_type, mode)
        if item is None:
            raise HTTPException(status_code=404, detail="Compliance not found")
        definition = await definitions.load_template_definition(
            conn, compliance_type, mode, include_inactive=True
        )
        open_counts = await self._open_filing_counts(conn, compliance_type, mode)
        return _format(item, definition, open_counts.get((compliance_type, mode), 0))

    @staticmethod
    async def _open_filing_counts(
        conn: asyncpg.Connection, compliance_type: str | None = None, mode: str | None = None
    ) -> dict[tuple[str, str], int]:
        """Filings not yet completed. They keep the steps they started with."""
        rows = await conn.fetch(
            """
            SELECT compliance_type::text AS compliance_type, mode::text AS mode, COUNT(*)::int AS c
            FROM compliance_workflows
            WHERE status <> 'COMPLETED'::compliance_status
              AND ($1::text IS NULL OR compliance_type = $1::compliance_type)
              AND ($2::text IS NULL OR mode::text = $2::text)
            GROUP BY 1, 2
            """,
            compliance_type,
            mode,
        )
        return {(r["compliance_type"], r["mode"]): r["c"] for r in rows}

    @staticmethod
    async def _category(conn: asyncpg.Connection, slug: str) -> asyncpg.Record:
        category = await catalog_repo.fetch_category_by_slug(conn, slug)
        if category is None:
            raise HTTPException(status_code=422, detail=f"Unknown category {slug!r}")
        return category

    @staticmethod
    def _check_can_be_active(is_active: bool, price: Decimal) -> None:
        if is_active and Decimal(str(price)) <= 0:
            raise HTTPException(
                status_code=422,
                detail="Set a price above zero before switching this compliance on",
            )

    @staticmethod
    async def _check_dependencies(
        conn: asyncpg.Connection, compliance_type: str, depends_on: list[dict]
    ) -> None:
        """Every dependency must exist, and must not (indirectly) depend back on this one."""
        graph: dict[str, set[str]] = {}
        known: set[tuple[str, str]] = set()
        for d in await definitions.list_template_definitions(conn, include_inactive=True):
            known.add((d["compliance_type"], d["mode"]))
            graph.setdefault(d["compliance_type"], set()).update(
                dep["compliance_type"] for dep in d["depends_on"]
            )
        for dep in depends_on:
            if (dep["compliance_type"], dep["mode"]) not in known:
                raise HTTPException(
                    status_code=422,
                    detail=f"Dependency {dep['compliance_type']} ({dep['mode']}) does not exist",
                )

        graph[compliance_type] = {dep["compliance_type"] for dep in depends_on}
        stack, seen = list(graph[compliance_type]), set()
        while stack:
            code = stack.pop()
            if code == compliance_type:
                raise HTTPException(
                    status_code=422,
                    detail="These dependencies form a loop: one of them already depends on this compliance",
                )
            if code in seen:
                continue
            seen.add(code)
            stack.extend(graph.get(code, ()))
