import json
from typing import Any
from uuid import UUID

import asyncpg

from app.modules.cart.shared_fields import SHARED_FIELD_LABELS, _canonical_field_key


def _parse_json_value(raw: Any) -> Any:
    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw
    return raw


def is_shared_data_key(field_key: str) -> bool:
    canonical = _canonical_field_key(field_key)
    return canonical in SHARED_FIELD_LABELS


def extract_shared_values(data: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for key, value in data.items():
        if value in (None, "", []):
            continue
        if not is_shared_data_key(key):
            continue
        canonical = _canonical_field_key(key)
        values[canonical] = value
    return values


async def fetch_company_data_map(
    conn: asyncpg.Connection, company_id: UUID
) -> dict[str, Any]:
    rows = await conn.fetch(
        """
        SELECT data_key, value
        FROM company_data
        WHERE company_id = $1
        """,
        company_id,
    )
    return {row["data_key"]: _parse_json_value(row["value"]) for row in rows}


async def upsert_company_data(
    conn: asyncpg.Connection,
    company_id: UUID,
    values: dict[str, Any],
) -> int:
    if not values:
        return 0

    count = 0
    for key, value in values.items():
        if value in (None, "", []):
            continue
        await conn.execute(
            """
            INSERT INTO company_data (company_id, data_key, value)
            VALUES ($1, $2, $3::jsonb)
            ON CONFLICT (company_id, data_key) DO UPDATE SET
                value = EXCLUDED.value,
                updated_at = NOW()
            """,
            company_id,
            key,
            json.dumps(value),
        )
        count += 1
    return count
