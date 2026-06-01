from pathlib import Path
import logging

import asyncpg
from app.modules.workflow.bootstrap import seed_workflow_templates

logger = logging.getLogger(__name__)


async def run_schema(conn: asyncpg.Connection) -> None:
    schema_path = Path(__file__).resolve().parent / "schema.sql"
    sql = schema_path.read_text(encoding="utf-8")
    await conn.execute(sql)


async def bootstrap_database(pool: asyncpg.Pool) -> None:
    logger.info("Bootstrapping database: start")
    async with pool.acquire() as conn:
        logger.info("Bootstrapping database: applying schema")
        await run_schema(conn)
        logger.info("Bootstrapping database: schema applied")
        logger.info("Bootstrapping database: seeding workflow templates")
        seeded_count = await seed_workflow_templates(conn)
        logger.info("Bootstrapping database: seeded %s workflow templates", seeded_count)
    logger.info("Bootstrapping database: complete")
