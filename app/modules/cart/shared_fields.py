"""Canonical field keys for cross-compliance data reuse."""

from typing import Any

# Maps workflow step field keys to a canonical shared key.
FIELD_ALIASES: dict[str, str] = {
    "address": "company_address",
    "business_address": "company_address",
    "cac_rc_number": "rc_number",
    "contact_email": "contact_email",
    "contact_phone": "contact_phone",
    "directors": "directors",
    "shareholders": "shareholders",
    "id_type": "director_id_type",
    "id_number": "director_id_number",
    "proposed_name_1": "proposed_company_name_1",
    "proposed_name_2": "proposed_company_name_2",
    "proposed_name_3": "proposed_company_name_3",
    "business_activity": "business_activity",
    "nature_of_business": "business_activity",
    "share_capital": "share_capital",
    "ownership_structure": "ownership_structure",
    "employee_count": "employee_count",
    "monthly_payroll_ngn": "monthly_payroll_ngn",
    "annual_payroll_ngn": "annual_payroll_ngn",
    "employees": "employees",
    "pfa_name": "pfa_name",
    "state_of_operation": "state_of_operation",
    "contractor_category": "contractor_category",
}

# Document types that represent the same underlying asset across compliances.
DOCUMENT_ALIASES: dict[str, str] = {
    "CAC_CERTIFICATE": "cac_certificate",
    "CAC_STATUS_REPORT": "cac_status_report",
    "CAC_DETAILS": "cac_certificate",
    "STAFF_LIST": "employee_list",
    "EMPLOYEE_LIST": "employee_list",
    "STAFF_SALARY_LIST": "employee_list",
    "PAYROLL_INFO": "payroll_info",
    "PAYROLL_REPORT": "payroll_info",
    "PAYROLL_SCHEDULE": "payroll_info",
    "UPDATED_PAYROLL": "payroll_info",
    "DIRECTOR_DETAILS": "directors",
    "DIRECTOR_VALID_ID": "director_valid_id",
    "VALID_ID": "director_valid_id",
    "TIN": "tin_document",
}

SHARED_FIELD_LABELS: dict[str, str] = {
    "company_address": "Company address",
    "rc_number": "CAC RC number",
    "tin": "Tax Identification Number (TIN)",
    "contact_email": "Contact email",
    "contact_phone": "Contact phone",
    "directors": "Directors",
    "shareholders": "Shareholders",
    "director_id_type": "Director ID type",
    "director_id_number": "Director ID number",
    "proposed_company_name_1": "First proposed company name",
    "proposed_company_name_2": "Second proposed company name",
    "proposed_company_name_3": "Third proposed company name",
    "business_activity": "Business activity",
    "share_capital": "Share capital (NGN)",
    "ownership_structure": "Ownership structure",
    "employee_count": "Number of employees",
    "monthly_payroll_ngn": "Monthly payroll (NGN)",
    "annual_payroll_ngn": "Annual payroll (NGN)",
    "employees": "Employee details",
    "pfa_name": "Pension Fund Administrator",
    "state_of_operation": "State of operation",
    "contractor_category": "Contractor category",
    "cac_certificate": "CAC certificate",
    "cac_status_report": "CAC status report",
    "employee_list": "Employee / staff list",
    "payroll_info": "Payroll information",
    "director_valid_id": "Director valid ID",
    "tin_document": "TIN document",
}


def _canonical_field_key(field_key: str) -> str:
    return FIELD_ALIASES.get(field_key, field_key)


def _canonical_doc_key(doc_type: str) -> str:
    return DOCUMENT_ALIASES.get(doc_type, doc_type.lower())
