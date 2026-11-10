from typing import Any

from app.domain.enums import ComplianceMode, ComplianceType
from app.modules.cart.shared_fields import _canonical_field_key
from app.modules.company_data.merge import merge_step_data
from app.modules.company_data.repository import is_shared_data_key
from app.modules.workflow.step_schemas import get_step_field_schema


def _is_empty(value: Any) -> bool:
    return value in (None, "", [])


def build_step_form_fields(
    *,
    compliance_type: ComplianceType,
    mode: ComplianceMode,
    step_number: int,
    step_data: dict[str, Any],
    company_data: dict[str, Any],
    fields: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    """Return field definitions with merged values and list of missing required keys."""
    merged = merge_step_data(
        step_data=step_data,
        company_data=company_data,
        compliance_type=compliance_type,
        mode=mode,
        step_number=step_number,
        fields=fields,
    )
    schema = fields if fields is not None else get_step_field_schema(compliance_type, mode, step_number)
    form_fields: list[dict[str, Any]] = []
    missing_required: list[str] = []

    for field in schema:
        key = field["key"]
        value = merged.get(key)
        filled = not _is_empty(value)
        shared = is_shared_data_key(key)
        canonical = _canonical_field_key(key) if shared else None

        if field.get("required") and not filled:
            missing_required.append(key)

        form_fields.append(
            {
                "key": key,
                "label": field.get("label", key),
                "type": field.get("type", "text"),
                "required": bool(field.get("required")),
                "options": field.get("options"),
                "description": field.get("description"),
                "shared": shared,
                "canonical_key": canonical,
                "value": value if filled else None,
                "filled": filled,
            }
        )

    return form_fields, missing_required, merged
