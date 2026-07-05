"""Sync shared field values into the central company data store."""

from typing import Any
from uuid import UUID

import asyncpg

from app.modules.cart.shared_fields import _canonical_field_key
from app.modules.company_data.repository import upsert_company_data


def extract_canonical_values(step_data: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for key, value in step_data.items():
        if value in (None, "", []):
            continue
        canonical = _canonical_field_key(key)
        values[canonical] = value
    return values


async def propagate_shared_step_data(
    conn: asyncpg.Connection,
    *,
    company_id: UUID,
    source_compliance_type: object,
    source_mode: object,
    step_data: dict[str, Any],
) -> list[dict[str, Any]]:
    """Persist shared values from a workflow step into company_data."""
    del source_compliance_type, source_mode
    canonical_values = extract_canonical_values(step_data)
    if not canonical_values:
        return []

    await upsert_company_data(conn, company_id, canonical_values)
    return [{"keys_updated": sorted(canonical_values.keys())}]


async def sync_company_profile_from_shared(
    conn: asyncpg.Connection,
    company_id: UUID,
    shared_data: dict[str, Any],
) -> dict[str, Any]:
    """Update company record when shared address / RC / TIN values are provided."""
    canonical = {
        _canonical_field_key(k): v for k, v in shared_data.items() if v not in (None, "", [])
    }
    await upsert_company_data(conn, company_id, canonical)
    updates: dict[str, str] = {}

    if canonical.get("company_address"):
        updates["address"] = str(canonical["company_address"])
    if canonical.get("rc_number"):
        updates["rc_number"] = str(canonical["rc_number"])
    if canonical.get("tin"):
        updates["tin"] = str(canonical["tin"])

    if not updates:
        return {}

    from app.modules.cac.repository import fetch_company_by_id

    company = await fetch_company_by_id(conn, company_id)
    if company is None:
        return {}

    set_parts = []
    values: list[object] = [company_id]
    idx = 2
    for field, value in updates.items():
        set_parts.append(f"{field} = ${idx}")
        values.append(value)
        idx += 1

    await conn.execute(
        f"UPDATE companies SET {', '.join(set_parts)} WHERE id = $1",
        *values,
    )
    return updates
