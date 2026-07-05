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
    (ComplianceType.ITF, ComplianceMode.NEW): {
        1: [{"key": "employee_count", "label": "Number of employees", "type": "number", "required": True}],
        2: [{"key": "staff_list_notes", "label": "Staff list notes", "type": "textarea", "required": False}],
        3: [
            {"key": "monthly_payroll_ngn", "label": "Estimated monthly payroll (NGN)", "type": "number", "required": True},
            {"key": "annual_payroll_ngn", "label": "Estimated annual payroll (NGN)", "type": "number", "required": True},
        ],
        4: [{"key": "application_confirmed", "label": "Application confirmed", "type": "boolean", "required": True}],
    },
    (ComplianceType.ITF, ComplianceMode.RENEWAL): {
        1: [{"key": "annual_payroll_ngn", "label": "Updated annual payroll (NGN)", "type": "number", "required": True}],
        2: [{"key": "total_staff_salaries_ngn", "label": "Total staff salaries (NGN)", "type": "number", "required": True}],
        3: [
            {"key": "contribution_1_percent_ngn", "label": "1% ITF contribution (NGN)", "type": "number", "required": True},
            {"key": "contribution_approved", "label": "Contribution approved", "type": "boolean", "required": True},
        ],
        4: [{"key": "payment_reference", "label": "Payment reference", "type": "text", "required": False}],
    },
    (ComplianceType.NSITF, ComplianceMode.NEW): {
        1: [{"key": "employee_count", "label": "Number of employees", "type": "number", "required": True}],
        2: [{"key": "monthly_payroll_ngn", "label": "Monthly payroll (NGN)", "type": "number", "required": True}],
        3: [{"key": "salary_structure_notes", "label": "Salary structure notes", "type": "textarea", "required": False}],
        4: [{"key": "application_confirmed", "label": "Application confirmed", "type": "boolean", "required": True}],
    },
    (ComplianceType.NSITF, ComplianceMode.RENEWAL): {
        1: [
            {"key": "employee_count", "label": "Updated employee count", "type": "number", "required": True},
            {"key": "annual_payroll_ngn", "label": "Updated annual payroll (NGN)", "type": "number", "required": True},
        ],
        2: [
            {"key": "contribution_1_percent_ngn", "label": "1% NSITF contribution (NGN)", "type": "number", "required": True},
            {"key": "contribution_approved", "label": "Contribution approved", "type": "boolean", "required": True},
        ],
        3: [{"key": "payment_reference", "label": "Payment reference", "type": "text", "required": False}],
    },
    (ComplianceType.PENCOM, ComplianceMode.NEW): {
        1: [{"key": "employee_count", "label": "Number of employees", "type": "number", "required": True}],
        2: [
            {
                "key": "employees",
                "label": "Employee details",
                "type": "json",
                "required": True,
                "description": "Array of {name, rsa_pin, pfa}",
            }
        ],
        3: [
            {"key": "pfa_name", "label": "Pension Fund Administrator", "type": "text", "required": True},
            {"key": "auto_assign_pfa", "label": "Allow system to assign PFA", "type": "boolean", "required": False},
        ],
        4: [{"key": "pension_setup_approved", "label": "Pension setup approved", "type": "boolean", "required": True}],
    },
    (ComplianceType.PENCOM, ComplianceMode.RENEWAL): {
        1: [{"key": "monthly_remittance_confirmed", "label": "Monthly remittance confirmed", "type": "boolean", "required": True}],
        2: [{"key": "payment_records_notes", "label": "Payment records notes", "type": "textarea", "required": False}],
        3: [{"key": "compliance_approved", "label": "Compliance application approved", "type": "boolean", "required": True}],
    },
    (ComplianceType.GROUP_LIFE_INSURANCE, ComplianceMode.NEW): {
        1: [{"key": "employee_count", "label": "Number of employees", "type": "number", "required": True}],
        2: [{"key": "annual_payroll_ngn", "label": "Annual payroll (NGN)", "type": "number", "required": True}],
        3: [
            {"key": "insurance_quote_ngn", "label": "Insurance quote (NGN)", "type": "number", "required": True},
            {"key": "quote_approved", "label": "Quote approved", "type": "boolean", "required": True},
        ],
        4: [{"key": "payment_reference", "label": "Payment reference", "type": "text", "required": False}],
    },
    (ComplianceType.GROUP_LIFE_INSURANCE, ComplianceMode.RENEWAL): {
        1: [{"key": "employee_count", "label": "Updated employee count", "type": "number", "required": True}],
        2: [{"key": "annual_payroll_ngn", "label": "Updated annual payroll (NGN)", "type": "number", "required": True}],
        3: [
            {"key": "new_premium_ngn", "label": "New premium (NGN)", "type": "number", "required": True},
            {"key": "premium_approved", "label": "Premium approved", "type": "boolean", "required": True},
        ],
        4: [{"key": "payment_reference", "label": "Payment reference", "type": "text", "required": False}],
    },
    (ComplianceType.ACCOUNT_AUDITING, ComplianceMode.PROCESS): {
        1: [
            {"key": "financial_year", "label": "Financial year", "type": "text", "required": True},
            {"key": "records_uploaded", "label": "Income/expense/bank records uploaded", "type": "boolean", "required": True},
        ],
        2: [
            {"key": "total_revenue_ngn", "label": "Total revenue (NGN)", "type": "number", "required": True},
            {"key": "total_expenses_ngn", "label": "Total expenses (NGN)", "type": "number", "required": True},
            {"key": "financial_notes", "label": "Additional financial notes", "type": "textarea", "required": False},
        ],
        3: [{"key": "draft_accounts_approved", "label": "Draft accounts approved", "type": "boolean", "required": True}],
    },
    (ComplianceType.SCUML, ComplianceMode.REGISTRATION): {
        1: [
            {"key": "business_type", "label": "Business type (DNFB)", "type": "text", "required": True},
            {"key": "is_designated_non_financial", "label": "Is designated non-financial business", "type": "boolean", "required": True},
        ],
        2: [
            {"key": "cac_rc_number", "label": "CAC RC number", "type": "text", "required": True},
            {"key": "business_address", "label": "Business address", "type": "textarea", "required": True},
            {"key": "contact_email", "label": "Contact email", "type": "email", "required": True},
        ],
        3: [{"key": "documents_uploaded", "label": "Required documents uploaded", "type": "boolean", "required": True}],
        4: [
            {"key": "transaction_volume", "label": "Typical transaction volume", "type": "text", "required": True},
            {"key": "client_types", "label": "Client types served", "type": "textarea", "required": True},
            {"key": "compliance_questionnaire_notes", "label": "Questionnaire notes", "type": "textarea", "required": False},
        ],
        5: [{"key": "application_confirmed", "label": "Application confirmed", "type": "boolean", "required": True}],
    },
    (ComplianceType.BPP_FEDERAL, ComplianceMode.REGISTRATION): {
        1: [{"key": "prerequisites_confirmed", "label": "Prerequisites confirmed", "type": "boolean", "required": True}],
        2: [
            {"key": "cac_rc_number", "label": "CAC RC number", "type": "text", "required": True},
            {"key": "contractor_category", "label": "Contractor category", "type": "text", "required": True},
            {"key": "business_address", "label": "Business address", "type": "textarea", "required": True},
            {"key": "contact_email", "label": "Contact email", "type": "email", "required": True},
            {"key": "contact_phone", "label": "Contact phone", "type": "text", "required": True},
        ],
        3: [{"key": "documents_uploaded", "label": "Required documents uploaded", "type": "boolean", "required": True}],
        4: [{"key": "application_reviewed", "label": "Application reviewed", "type": "boolean", "required": True}],
        5: [{"key": "application_confirmed", "label": "Application confirmed", "type": "boolean", "required": True}],
    },
    (ComplianceType.BPP_STATE, ComplianceMode.REGISTRATION): {
        1: [{"key": "prerequisites_confirmed", "label": "Prerequisites confirmed", "type": "boolean", "required": True}],
        2: [
            {"key": "cac_rc_number", "label": "CAC RC number", "type": "text", "required": True},
            {"key": "state_of_operation", "label": "State of operation", "type": "text", "required": True},
            {"key": "contractor_category", "label": "Contractor category", "type": "text", "required": True},
            {"key": "business_address", "label": "Business address", "type": "textarea", "required": True},
            {"key": "contact_email", "label": "Contact email", "type": "email", "required": True},
        ],
        3: [{"key": "documents_uploaded", "label": "Required documents uploaded", "type": "boolean", "required": True}],
        4: [{"key": "application_reviewed", "label": "Application reviewed", "type": "boolean", "required": True}],
        5: [{"key": "application_confirmed", "label": "Application confirmed", "type": "boolean", "required": True}],
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
