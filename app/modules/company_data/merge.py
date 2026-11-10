from typing import Any

from app.domain.enums import ComplianceMode, ComplianceType
from app.modules.cart.shared_fields import _canonical_field_key
from app.modules.workflow.step_schemas import get_step_field_schema


def merge_step_data(
    *,
    step_data: dict[str, Any],
    company_data: dict[str, Any],
    compliance_type: ComplianceType,
    mode: ComplianceMode,
    step_number: int,
    fields: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Overlay canonical company data onto step fields when the step value is empty.

    `fields` is the step's stored definition; without it the code default is used.
    """
    merged = dict(step_data) if step_data else {}
    if not company_data:
        return merged

    if fields is None:
        fields = get_step_field_schema(compliance_type, mode, step_number)
    for field in fields:
        field_key = field["key"]
        if merged.get(field_key) not in (None, "", []):
            continue
        canonical = _canonical_field_key(field_key)
        shared_value = company_data.get(canonical)
        if shared_value not in (None, "", []):
            merged[field_key] = shared_value
    return merged
