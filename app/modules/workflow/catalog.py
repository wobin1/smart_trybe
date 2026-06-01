from app.domain.enums import ComplianceMode, ComplianceType

WORKFLOW_STEP_DEFINITIONS: dict[tuple[ComplianceType, ComplianceMode], list[str]] = {
    (ComplianceType.CAC, ComplianceMode.NEW): [
        "Choose 2 proposed company names",
        "Provide business activity (what the company does)",
        "Provide directors and shareholders details",
        "Upload valid ID (NIN or passport)",
        "Provide company address",
        "Approve company structure (share capital, ownership %)",
        "Review and confirm all details",
        "Make payment",
    ],
    (ComplianceType.CAC, ComplianceMode.RENEWAL): [
        "Confirm company is still active",
        "Provide basic company updates (if any)",
        "Upload financial summary (or approve no activity)",
        "Approve filing",
        "Make payment",
    ],
    (ComplianceType.FIRS, ComplianceMode.NEW): [
        "Provide CAC details",
        "Provide business address",
        "Provide contact details",
        "Confirm nature of business",
        "Submit application",
    ],
    (ComplianceType.FIRS, ComplianceMode.RENEWAL): [
        "Provide yearly financial records",
        "Confirm revenue for the year",
        "Upload audited accounts (if required)",
        "Approve tax filing",
        "Pay tax (if applicable)",
    ],
    (ComplianceType.ITF, ComplianceMode.NEW): [
        "Confirm number of employees",
        "Upload staff list",
        "Provide payroll estimate",
        "Submit application",
    ],
    (ComplianceType.ITF, ComplianceMode.RENEWAL): [
        "Upload updated payroll",
        "Confirm total staff salaries",
        "Approve 1% contribution calculation",
        "Make payment",
    ],
    (ComplianceType.NSITF, ComplianceMode.NEW): [
        "Provide employee list",
        "Provide payroll details",
        "Confirm total salary structure",
        "Submit application",
    ],
    (ComplianceType.NSITF, ComplianceMode.RENEWAL): [
        "Update employee and payroll info",
        "Approve contribution (1% of payroll)",
        "Make payment",
    ],
    (ComplianceType.PENCOM, ComplianceMode.NEW): [
        "Confirm number of employees",
        "Provide employee details",
        "Select Pension Fund Administrator (or allow system assign)",
        "Approve pension setup",
    ],
    (ComplianceType.PENCOM, ComplianceMode.RENEWAL): [
        "Confirm monthly pension remittance",
        "Upload payment records",
        "Approve compliance application",
    ],
    (ComplianceType.GROUP_LIFE_INSURANCE, ComplianceMode.NEW): [
        "Upload employee list",
        "Provide salary structure",
        "Approve insurance quote",
        "Make payment",
    ],
    (ComplianceType.GROUP_LIFE_INSURANCE, ComplianceMode.RENEWAL): [
        "Update staff list",
        "Confirm salary changes",
        "Approve new premium",
        "Make payment",
    ],
    (ComplianceType.ACCOUNT_AUDITING, ComplianceMode.PROCESS): [
        "Upload income records, expenses, and bank statements",
        "Answer basic financial questions",
        "Approve draft accounts",
    ],
    (ComplianceType.SCUML, ComplianceMode.REGISTRATION): [
        "Confirm business type (Designated Non-Financial Business)",
        "Provide company details",
        "Upload required documents",
        "Fill compliance questionnaire (transactions, clients, etc.)",
        "Submit application",
    ],
}

REQUIRED_DOCS: dict[tuple[ComplianceType, ComplianceMode], set[str]] = {
    (ComplianceType.CAC, ComplianceMode.NEW): {
        "VALID_ID",
        "PASSPORT_PHOTO",
        "ADDRESS_PROOF",
        "SIGNATURE",
    },
    (ComplianceType.CAC, ComplianceMode.RENEWAL): {"FINANCIAL_SUMMARY"},
    (ComplianceType.FIRS, ComplianceMode.NEW): {"CAC_CERTIFICATE", "CAC_STATUS_REPORT", "DIRECTOR_DETAILS"},
    (ComplianceType.FIRS, ComplianceMode.RENEWAL): {"AUDITED_FINANCIAL_STATEMENTS"},
    (ComplianceType.ITF, ComplianceMode.NEW): {"CAC_CERTIFICATE", "EMPLOYEE_LIST", "PAYROLL_INFO"},
    (ComplianceType.ITF, ComplianceMode.RENEWAL): {"PAYROLL_REPORT", "PAYMENT_PROOF"},
    (ComplianceType.NSITF, ComplianceMode.NEW): {"CAC_CERTIFICATE", "STAFF_LIST", "PAYROLL_SCHEDULE"},
    (ComplianceType.NSITF, ComplianceMode.RENEWAL): {"UPDATED_PAYROLL", "PAYMENT_RECEIPT"},
    (ComplianceType.PENCOM, ComplianceMode.NEW): {"STAFF_LIST", "EMPLOYMENT_DETAILS"},
    (ComplianceType.PENCOM, ComplianceMode.RENEWAL): {"PENSION_REMITTANCE_RECORDS", "EMPLOYEE_PENSION_DETAILS"},
    (ComplianceType.GROUP_LIFE_INSURANCE, ComplianceMode.NEW): {"STAFF_SALARY_LIST", "CAC_DETAILS"},
    (ComplianceType.GROUP_LIFE_INSURANCE, ComplianceMode.RENEWAL): {
        "UPDATED_PAYROLL",
        "PREVIOUS_CERTIFICATE",
    },
    (ComplianceType.ACCOUNT_AUDITING, ComplianceMode.PROCESS): {
        "BANK_STATEMENTS",
        "TRANSACTION_RECORDS",
    },
    (ComplianceType.SCUML, ComplianceMode.REGISTRATION): {
        "CAC_CERTIFICATE",
        "CAC_STATUS_REPORT",
        "DIRECTOR_VALID_ID",
        "UTILITY_BILL",
        "TIN",
    },
}
