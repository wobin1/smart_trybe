import asyncpg

from app.modules.catalog.seed import CATALOG_SEED
from app.modules.workflow import definitions
from app.modules.workflow.catalog import WORKFLOW_STEP_DEFINITIONS


async def seed_workflow_templates(conn: asyncpg.Connection) -> int:
    """Create the template of each built-in compliance that does not have one yet.

    Existing templates are never touched: once a compliance is in the database its
    steps, fields, documents and dependencies belong to the admin dashboard.
    """
    active = {
        (item["compliance_type"].value, item["mode"].value): item["is_active"]
        for item in CATALOG_SEED
    }
    seeded = 0
    for compliance_type, mode in WORKFLOW_STEP_DEFINITIONS:
        ct, md = compliance_type.value, mode.value
        exists = await conn.fetchval(
            """
            SELECT 1 FROM workflow_templates
            WHERE compliance_type = $1::compliance_type AND mode = $2::compliance_mode
            """,
            ct,
            md,
        )
        if exists:
            continue
        steps = definitions.default_steps(ct, md)
        assert steps is not None
        await definitions.save_template_definition(
            conn,
            ct,
            md,
            steps=steps,
            required_documents=definitions.default_required_documents(ct, md),
            depends_on=definitions.default_depends_on(ct, md),
            is_active=active.get((ct, md), True),
        )
        seeded += 1
    return seeded
