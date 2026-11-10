"""One-off data migrations.

Each runs exactly once per database (recorded in `schema_migrations`) inside a
transaction, after the schema is applied and the built-ins are seeded. Add new
migrations to the end of MIGRATIONS; never edit one that has shipped.
"""

import json
import logging
from collections.abc import Awaitable, Callable

import asyncpg

from app.modules.catalog.seed import CATALOG_SEED
from app.modules.workflow import definitions

logger = logging.getLogger(__name__)


async def _store_template_definitions(conn: asyncpg.Connection) -> None:
    """Move steps' fields, required documents and dependencies from code into the database.

    Templates created before admins could edit compliances only stored step names.
    This writes the code defaults onto them, applies the two definition changes
    shipped with this release, and freezes every existing filing onto the result.
    """
    templates = await conn.fetch(
        """
        SELECT id, compliance_type::text AS compliance_type, mode::text AS mode,
               required_documents, depends_on
        FROM workflow_templates
        """
    )
    for t in templates:
        ct, mode = t["compliance_type"], t["mode"]
        await conn.execute(
            """
            UPDATE workflow_templates
            SET required_documents = COALESCE(required_documents, $2::jsonb),
                depends_on = $3::jsonb
            WHERE id = $1
            """,
            t["id"],
            json.dumps(definitions.default_required_documents(ct, mode)),
            # Dependencies were never editable before, so the code default is
            # authoritative here (BPP now points at the single ITF/NSITF/PENCOM application).
            json.dumps(definitions.default_depends_on(ct, mode)),
        )
        steps = await conn.fetch(
            "SELECT step_number FROM workflow_template_steps WHERE template_id = $1 AND fields IS NULL",
            t["id"],
        )
        for s in steps:
            await conn.execute(
                "UPDATE workflow_template_steps SET fields = $3::jsonb WHERE template_id = $1 AND step_number = $2",
                t["id"],
                s["step_number"],
                json.dumps(definitions.default_step_fields(ct, mode, s["step_number"])),
            )

    # CAC new registration now takes three proposed names (two required, one optional).
    await conn.execute(
        """
        UPDATE workflow_template_steps s
        SET step_name = 'Choose proposed company names', fields = $1::jsonb
        FROM workflow_templates t
        WHERE t.id = s.template_id
          AND t.compliance_type = 'CAC'::compliance_type
          AND t.mode = 'NEW'::compliance_mode
          AND s.step_number = 1
          AND s.step_name = 'Choose 2 proposed company names'
        """,
        json.dumps(definitions.default_step_fields("CAC", "NEW", 1)),
    )
    await conn.execute(
        """
        UPDATE compliance_step_progress p
        SET step_name = 'Choose proposed company names'
        FROM compliance_workflows w
        WHERE w.id = p.workflow_id
          AND w.compliance_type = 'CAC'::compliance_type
          AND w.mode = 'NEW'::compliance_mode
          AND p.step_number = 1
          AND p.step_name = 'Choose 2 proposed company names'
        """
    )

    # Freeze every filing that exists today onto its current template, so admin
    # edits made from now on only affect filings started afterwards.
    for definition in await definitions.list_template_definitions(conn, include_inactive=True):
        await conn.execute(
            """
            UPDATE compliance_workflows
            SET definition = $3::jsonb
            WHERE compliance_type = $1::compliance_type
              AND mode = $2::compliance_mode
              AND definition IS NULL
            """,
            definition["compliance_type"],
            definition["mode"],
            json.dumps(definitions.snapshot_payload(definition)),
        )


async def _one_application_per_agency(conn: asyncpg.Connection) -> None:
    """Apply the agreed application list to catalogs created before it.

    Sets names, descriptions, order, regulator and the on/off state of the built-in
    compliances, and retires the second variant each agency used to have. Prices
    are deliberately left alone.
    """
    for item in CATALOG_SEED:
        ct, mode = item["compliance_type"].value, item["mode"].value
        await conn.execute(
            """
            UPDATE compliance_catalog
            SET display_name = $3,
                description = $4,
                display_order = $5,
                regulator_name = $6,
                is_active = $7,
                is_system = TRUE
            WHERE compliance_type = $1::compliance_type AND mode = $2::compliance_mode
            """,
            ct,
            mode,
            item["display_name"],
            item["description"],
            item["display_order"],
            item["regulator_name"],
            item["is_active"],
        )
        await definitions.set_template_active(conn, ct, mode, item["is_active"])


MIGRATIONS: list[tuple[str, Callable[[asyncpg.Connection], Awaitable[None]]]] = [
    ("2026_11_store_template_definitions", _store_template_definitions),
    ("2026_11_one_application_per_agency", _one_application_per_agency),
]


async def run_migrations(conn: asyncpg.Connection) -> list[str]:
    applied: list[str] = []
    for key, migrate in MIGRATIONS:
        async with conn.transaction():
            # The insert doubles as a lock: a second instance booting at the same
            # time blocks here, then sees the row and skips.
            claimed = await conn.fetchval(
                "INSERT INTO schema_migrations (key) VALUES ($1) ON CONFLICT (key) DO NOTHING RETURNING key",
                key,
            )
            if claimed is None:
                continue
            await migrate(conn)
        applied.append(key)
        logger.info("Applied data migration %s", key)
    return applied
