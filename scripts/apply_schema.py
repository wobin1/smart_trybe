#!/usr/bin/env python3
"""Apply compliance schema using DATABASE_URL (standalone migration helper)."""

import asyncio
import os
import sys
from pathlib import Path

import asyncpg


async def main() -> None:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL is required", file=sys.stderr)
        sys.exit(1)

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))

    from app.db.bootstrap import run_schema

    conn = await asyncpg.connect(dsn)
    try:
        await run_schema(conn)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
