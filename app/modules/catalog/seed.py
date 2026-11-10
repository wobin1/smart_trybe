"""Built-in compliances.

This list only *seeds* the catalog: a row is inserted when it is missing and never
overwritten afterwards, so prices, names and on/off switches set by an admin
survive restarts. New compliances are created by admins, not added here.

Each agency has a single application. The second variant some agencies used to
have (e.g. ITF Renewal) is kept as an inactive row so filings and cart lines that
already reference it keep working.
"""

from decimal import Decimal

from app.domain.enums import ComplianceMode, ComplianceType

CATEGORY_SEED: list[dict] = [
    {
        "slug": "corporate_registration",
        "name": "Corporate / Registration",
        "description": "Company incorporation, CAC filings, and registration renewals.",
        "display_order": 1,
    },
    {
        "slug": "tax_finance",
        "name": "Tax / Finance",
        "description": "Tax registration, annual returns, and financial compliance.",
        "display_order": 2,
    },
    {
        "slug": "insurance_labour",
        "name": "Insurance / Labour",
        "description": "Employee insurance, pension, and statutory labour contributions.",
        "display_order": 3,
    },
    {
        "slug": "data_regulatory",
        "name": "Data / Regulatory",
        "description": "Regulatory registrations including procurement and compliance filings.",
        "display_order": 4,
    },
]


def _item(
    compliance_type: ComplianceType,
    mode: ComplianceMode,
    *,
    order: int,
    name: str,
    description: str,
    category: str,
    regulator: str,
    icon: str,
    price: str,
    active: bool = True,
) -> dict:
    return {
        "compliance_type": compliance_type,
        "mode": mode,
        "display_order": order,
        "display_name": name,
        "description": description,
        "category_slug": category,
        "regulator_name": regulator,
        "icon_key": icon,
        "base_price_ngn": Decimal(price),
        "is_active": active,
    }


_CAC = "the Corporate Affairs Commission (CAC)"
_FIRS = "the Federal Inland Revenue Service (FIRS)"
_ITF = "the Industrial Training Fund (ITF)"
_NSITF = "the Nigeria Social Insurance Trust Fund (NSITF)"
_PENCOM = "the National Pension Commission (PenCom)"
_UNDERWRITER = "your appointed group life insurance underwriter"

# Order is the order clients see on the Applications page.
CATALOG_SEED: list[dict] = [
    _item(
        ComplianceType.CAC, ComplianceMode.NEW, order=10,
        name="CAC New Registration",
        description="Register a new company with the Corporate Affairs Commission.",
        category="corporate_registration", regulator=_CAC, icon="cac", price="85000",
    ),
    _item(
        ComplianceType.CAC, ComplianceMode.RENEWAL, order=20,
        name="CAC Annual Return",
        description="File annual returns with the Corporate Affairs Commission for an existing company.",
        category="corporate_registration", regulator=_CAC, icon="cac", price="25000",
    ),
    _item(
        ComplianceType.FIRS, ComplianceMode.RENEWAL, order=30,
        name="FIRS Tax Renewal",
        description="Renew tax compliance and obtain a Tax Clearance Certificate.",
        category="tax_finance", regulator=_FIRS, icon="firs", price="45000",
    ),
    _item(
        ComplianceType.GROUP_LIFE_INSURANCE, ComplianceMode.NEW, order=40,
        name="Group Life Insurance",
        description="Obtain group life insurance coverage for employees.",
        category="insurance_labour", regulator=_UNDERWRITER, icon="group_life", price="40000",
    ),
    _item(
        ComplianceType.ACCOUNT_AUDITING, ComplianceMode.PROCESS, order=50,
        name="Account Auditing",
        description="Prepare audited accounts required for tax and regulatory filings.",
        category="tax_finance", regulator="your appointed external auditor", icon="audit", price="120000",
    ),
    _item(
        ComplianceType.BPP_FEDERAL, ComplianceMode.REGISTRATION, order=60,
        name="BPP Federal",
        description="Federal Bureau of Public Procurement registration.",
        category="data_regulatory", regulator="the Bureau of Public Procurement (Federal)",
        icon="bpp_federal", price="50000",
    ),
    _item(
        ComplianceType.BPP_STATE, ComplianceMode.REGISTRATION, order=70,
        name="BPP State",
        description="State Bureau of Public Procurement registration.",
        category="data_regulatory", regulator="the Bureau of Public Procurement (State)",
        icon="bpp_state", price="40000",
    ),
    _item(
        ComplianceType.ITF, ComplianceMode.NEW, order=80,
        name="ITF",
        description="Industrial Training Fund compliance.",
        category="insurance_labour", regulator=_ITF, icon="itf", price="20000",
    ),
    _item(
        ComplianceType.NSITF, ComplianceMode.NEW, order=90,
        name="NSITF",
        description="Nigeria Social Insurance Trust Fund compliance.",
        category="insurance_labour", regulator=_NSITF, icon="nsitf", price="20000",
    ),
    _item(
        ComplianceType.PENCOM, ComplianceMode.NEW, order=100,
        name="PENCOM",
        description="Pension compliance for employees with the National Pension Commission.",
        category="insurance_labour", regulator=_PENCOM, icon="pencom", price="25000",
    ),
    _item(
        ComplianceType.SCUML, ComplianceMode.REGISTRATION, order=110,
        name="AML/SCUML",
        description="Anti-money laundering registration with the Special Control Unit Against Money Laundering.",
        category="data_regulatory",
        regulator="the Special Control Unit against Money Laundering (SCUML)",
        icon="scuml", price="30000",
    ),
    # NITDA, CPN and NCS have no agreed price or process yet. They are seeded
    # switched off with a generic form so an admin can set the price, adjust the
    # steps and documents, and switch them on from the admin dashboard.
    _item(
        ComplianceType.NITDA, ComplianceMode.REGISTRATION, order=120,
        name="NITDA",
        description="National Information Technology Development Agency registration.",
        category="data_regulatory",
        regulator="the National Information Technology Development Agency (NITDA)",
        icon="nitda", price="0", active=False,
    ),
    _item(
        ComplianceType.CPN, ComplianceMode.REGISTRATION, order=130,
        name="CPN (Corporate)",
        description="Corporate registration with the Computer Professionals Registration Council of Nigeria.",
        category="data_regulatory",
        regulator="the Computer Professionals Registration Council of Nigeria (CPN)",
        icon="cpn", price="0", active=False,
    ),
    _item(
        ComplianceType.NCS, ComplianceMode.REGISTRATION, order=140,
        name="NCS (Corporate)",
        description="Corporate membership of the Nigeria Computer Society.",
        category="data_regulatory", regulator="the Nigeria Computer Society (NCS)",
        icon="ncs", price="0", active=False,
    ),
    # ── Retired variants: kept inactive for filings and carts that reference them ──
    _item(
        ComplianceType.FIRS, ComplianceMode.NEW, order=900,
        name="FIRS Tax Registration",
        description="Register your company for tax with the Federal Inland Revenue Service.",
        category="tax_finance", regulator=_FIRS, icon="firs", price="35000", active=False,
    ),
    _item(
        ComplianceType.ITF, ComplianceMode.RENEWAL, order=910,
        name="ITF Renewal",
        description="Renew ITF compliance and submit updated payroll.",
        category="insurance_labour", regulator=_ITF, icon="itf", price="15000", active=False,
    ),
    _item(
        ComplianceType.NSITF, ComplianceMode.RENEWAL, order=920,
        name="NSITF Renewal",
        description="Renew NSITF compliance and employee contribution records.",
        category="insurance_labour", regulator=_NSITF, icon="nsitf", price="15000", active=False,
    ),
    _item(
        ComplianceType.PENCOM, ComplianceMode.RENEWAL, order=930,
        name="PENCOM Pension Renewal",
        description="Renew pension remittance compliance.",
        category="insurance_labour", regulator=_PENCOM, icon="pencom", price="18000", active=False,
    ),
    _item(
        ComplianceType.GROUP_LIFE_INSURANCE, ComplianceMode.RENEWAL, order=940,
        name="Group Life Insurance Renewal",
        description="Renew group life insurance for staff.",
        category="insurance_labour", regulator=_UNDERWRITER, icon="group_life", price="30000",
        active=False,
    ),
]
