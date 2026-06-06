"""UI field hints and light validation for per-step JSON payloads."""

from typing import Any

from app.domain.enums import ComplianceMode, ComplianceType

FieldDef = dict[str, Any]
StepFields = dict[int, list[FieldDef]]

_DEFAULT_FIELDS: list[FieldDef] = [
    {"key": "notes", "label": "Notes", "type": "text", "required": False},
]

WORKFLOW_STEP_FIELDS: dict[tuple[ComplianceType, ComplianceMode], StepFields] = {
    (ComplianceType.CAC, ComplianceMode.NEW): {
        1: [
            {"key": "proposed_name_1", "label": "First proposed company name", "type": "text", "required": True},
            {"key": "proposed_name_2", "label": "Second proposed company name", "type": "text", "required": True},
        ],
        2: [
            {"key": "business_activity", "label": "Business activity", "type": "textarea", "required": True},
        ],
        3: [
            {
                "key": "directors",
                "label": "Directors",
                "type": "json",
                "required": True,
                "description": "Array of {name, email, phone, nin}",
            },
            {
                "key": "shareholders",
                "label": "Shareholders",
                "type": "json",
                "required": True,
                "description": "Array of {name, ownership_percent}",
            },
        ],
        4: [
            {"key": "id_type", "label": "ID type", "type": "select", "required": True, "options": ["NIN", "PASSPORT"]},
            {"key": "id_number", "label": "ID number", "type": "text", "required": True},
        ],
        5: [
            {"key": "address", "label": "Company address", "type": "textarea", "required": True},
            {"key": "city", "label": "City", "type": "text", "required": False},
            {"key": "state", "label": "State", "type": "text", "required": False},
        ],
        6: [
            {"key": "share_capital", "label": "Share capital (NGN)", "type": "number", "required": True},
            {
                "key": "ownership_structure",
                "label": "Ownership structure",
                "type": "json",
                "required": True,
            },
        ],
        7: [
            {"key": "confirmed", "label": "Review confirmed", "type": "boolean", "required": True},
        ],
        8: [
            {"key": "payment_reference", "label": "Payment reference", "type": "text", "required": False},
            {"key": "payment_amount", "label": "Payment amount (NGN)", "type": "number", "required": False},
        ],
    },
    (ComplianceType.CAC, ComplianceMode.RENEWAL): {
        1: [{"key": "still_active", "label": "Company still active", "type": "boolean", "required": True}],
        2: [
            {"key": "has_updates", "label": "Any company updates?", "type": "boolean", "required": True},
            {"key": "updates", "label": "Update details", "type": "textarea", "required": False},
        ],
        3: [
            {"key": "no_activity", "label": "No activity this year", "type": "boolean", "required": False},
            {"key": "financial_summary_notes", "label": "Financial summary notes", "type": "textarea", "required": False},
        ],
        4: [{"key": "filing_approved", "label": "Filing approved", "type": "boolean", "required": True}],
        5: [
            {"key": "payment_reference", "label": "Payment reference", "type": "text", "required": False},
        ],
    },
    (ComplianceType.FIRS, ComplianceMode.NEW): {
        1: [{"key": "cac_rc_number", "label": "CAC RC number", "type": "text", "required": True}],
        2: [{"key": "business_address", "label": "Business address", "type": "textarea", "required": True}],
        3: [
            {"key": "contact_email", "label": "Contact email", "type": "email", "required": True},
            {"key": "contact_phone", "label": "Contact phone", "type": "text", "required": True},
        ],
        4: [{"key": "nature_of_business", "label": "Nature of business", "type": "textarea", "required": True}],
        5: [{"key": "application_notes", "label": "Application notes", "type": "textarea", "required": False}],
    },
    (ComplianceType.FIRS, ComplianceMode.RENEWAL): {
        1: [{"key": "financial_year", "label": "Financial year", "type": "text", "required": True}],
        2: [{"key": "annual_revenue", "label": "Annual revenue (NGN)", "type": "number", "required": True}],
        3: [{"key": "audited_accounts_uploaded", "label": "Audited accounts uploaded", "type": "boolean", "required": False}],
        4: [{"key": "tax_filing_approved", "label": "Tax filing approved", "type": "boolean", "required": True}],
        5: [
            {"key": "tax_paid", "label": "Tax paid", "type": "boolean", "required": False},
            {"key": "tax_amount", "label": "Tax amount (NGN)", "type": "number", "required": False},
        ],
    },
}


def get_step_field_schema(
    compliance_type: ComplianceType,
    mode: ComplianceMode,
    step_number: int,
) -> list[FieldDef]:
    workflow_fields = WORKFLOW_STEP_FIELDS.get((compliance_type, mode), {})
    return workflow_fields.get(step_number, list(_DEFAULT_FIELDS))


def validate_step_data(
    compliance_type: ComplianceType,
    mode: ComplianceMode,
    step_number: int,
    data: dict[str, Any],
    *,
    require_all: bool = False,
) -> None:
    """Raise ValueError with message if required fields missing (on complete)."""
    if not isinstance(data, dict):
        raise ValueError("step data must be a JSON object")

    fields = get_step_field_schema(compliance_type, mode, step_number)
    if not require_all:
        return

    missing: list[str] = []
    for field in fields:
        if not field.get("required"):
            continue
        key = field["key"]
        value = data.get(key)
        if value is None or value == "" or value == []:
            missing.append(key)

    if missing:
        raise ValueError(f"Missing required fields: {', '.join(missing)}")
