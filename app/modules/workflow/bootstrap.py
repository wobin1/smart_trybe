import asyncpg

from app.modules.compliance import repository as compliance_repo
from app.modules.workflow.catalog import WORKFLOW_STEP_DEFINITIONS


async def seed_workflow_templates(conn: asyncpg.Connection) -> int:
    seeded = 0
    for (compliance_type, mode), steps in WORKFLOW_STEP_DEFINITIONS.items():
        template = await compliance_repo.upsert_workflow_template(
            conn,
            compliance_type.value,
            mode.value,
            len(steps),
        )
        assert template is not None
        await compliance_repo.replace_template_steps(conn, template["id"], steps)
        seeded += 1
    return seeded
