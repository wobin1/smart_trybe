from pathlib import Path
import logging

import asyncpg

from app.core.config import settings
from app.modules.workflow.bootstrap import seed_workflow_templates

logger = logging.getLogger(__name__)


async def run_schema(conn: asyncpg.Connection) -> None:
    schema_path = Path(__file__).resolve().parent / "schema.sql"
    sql = schema_path.read_text(encoding="utf-8")
    await conn.execute(sql)


async def promote_admin_emails(conn: asyncpg.Connection) -> int:
    emails = settings.admin_email_set()
    if not emails:
        return 0
    count = 0
    for email in emails:
        result = await conn.execute(
            """
            UPDATE users
            SET role = 'ADMIN'::user_role, is_admin = TRUE
            WHERE LOWER(TRIM(email)) = LOWER(TRIM($1))
              AND role != 'ADMIN'::user_role
            """,
            email,
        )
        if result.endswith("1"):
            count += 1
    return count


async def bootstrap_database(pool: asyncpg.Pool) -> None:
    logger.info("Bootstrapping database: start")
    async with pool.acquire() as conn:
        logger.info("Bootstrapping database: applying schema")
        await run_schema(conn)
        logger.info("Bootstrapping database: schema applied")
        promoted = await promote_admin_emails(conn)
        if promoted:
            logger.info("Bootstrapping database: promoted %s admin user(s)", promoted)
        logger.info("Bootstrapping database: seeding workflow templates")
        seeded_count = await seed_workflow_templates(conn)
        logger.info("Bootstrapping database: seeded %s workflow templates", seeded_count)
    logger.info("Bootstrapping database: complete")
