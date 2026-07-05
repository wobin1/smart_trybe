from typing import Any
from uuid import UUID

import asyncpg

from app.domain.enums import UserRole
from app.modules.access.company import require_company_client, require_company_read
from app.modules.cart.propagation import sync_company_profile_from_shared
from app.modules.cart.shared_fields import SHARED_FIELD_LABELS
from app.modules.company_data.repository import (
    extract_shared_values,
    fetch_company_data_map,
    upsert_company_data,
)


def _merge_profile_defaults(company: asyncpg.Record, data: dict[str, Any]) -> dict[str, Any]:
    merged = dict(data)
    if company.get("address") and "company_address" not in merged:
        merged["company_address"] = company["address"]
    if company.get("rc_number") and "rc_number" not in merged:
        merged["rc_number"] = company["rc_number"]
    if company.get("tin") and "tin" not in merged:
        merged["tin"] = company["tin"]
    if company.get("name") and "company_name" not in merged:
        merged["company_name"] = company["name"]
    return merged


def _format_response(company_id: UUID, company: asyncpg.Record, data: dict[str, Any]) -> dict:
    fields = [
        {
            "key": key,
            "label": SHARED_FIELD_LABELS.get(key, key.replace("_", " ").title()),
            "value": value,
        }
        for key, value in sorted(data.items())
        if value not in (None, "", [])
    ]
    return {
        "company_id": str(company_id),
        "data": data,
        "fields": fields,
        "field_count": len(fields),
    }


class CompanyDataService:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def get_company_data(
        self, *, company_id: UUID, user_id: UUID, role: UserRole
    ) -> dict:
        async with self._pool.acquire() as conn:
            company = await require_company_read(conn, company_id, user_id, role)
            stored = await fetch_company_data_map(conn, company_id)
            data = _merge_profile_defaults(company, stored)
            return _format_response(company_id, company, data)

    async def update_company_data(
        self,
        *,
        company_id: UUID,
        user_id: UUID,
        role: UserRole,
        payload: dict[str, Any],
    ) -> dict:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                company = await require_company_client(conn, company_id, user_id, role)
                canonical = extract_shared_values(payload)
                if not canonical:
                    stored = await fetch_company_data_map(conn, company_id)
                    data = _merge_profile_defaults(company, stored)
                    return _format_response(company_id, company, data)

                await upsert_company_data(conn, company_id, canonical)
                await sync_company_profile_from_shared(conn, company_id, payload)

                stored = await fetch_company_data_map(conn, company_id)
                company = await require_company_read(conn, company_id, user_id, role)
                data = _merge_profile_defaults(company, stored)
                return _format_response(company_id, company, data)
