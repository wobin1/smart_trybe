import re
from enum import Enum
from typing import Any, ClassVar

COMPLIANCE_CODE_RE = re.compile(r"[A-Z][A-Z0-9_]{1,39}")


class ComplianceStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    PENDING = "PENDING"
    IN_REVIEW = "IN_REVIEW"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"
    INFO_REQUIRED = "INFO_REQUIRED"


class UserRole(str, Enum):
    CLIENT = "CLIENT"
    AGENT = "AGENT"
    ADMIN = "ADMIN"


class OAuthProvider(str, Enum):
    GOOGLE = "google"


class ComplianceType(str):
    """A compliance code such as ``CAC`` or ``NITDA``.

    This is deliberately *not* an Enum: admins create new compliances at runtime,
    so the set of valid codes lives in the ``compliance_catalog`` table. The class
    attributes below only name the built-in compliances that have bespoke logic
    (CAC registry, BPP modules, dependency rules). ``.value`` is kept so existing
    call sites written against the old Enum continue to work.
    """

    __slots__ = ()

    CAC: ClassVar["ComplianceType"]
    FIRS: ClassVar["ComplianceType"]
    ITF: ClassVar["ComplianceType"]
    NSITF: ClassVar["ComplianceType"]
    PENCOM: ClassVar["ComplianceType"]
    GROUP_LIFE_INSURANCE: ClassVar["ComplianceType"]
    ACCOUNT_AUDITING: ClassVar["ComplianceType"]
    SCUML: ClassVar["ComplianceType"]
    BPP_FEDERAL: ClassVar["ComplianceType"]
    BPP_STATE: ClassVar["ComplianceType"]
    NITDA: ClassVar["ComplianceType"]
    CPN: ClassVar["ComplianceType"]
    NCS: ClassVar["ComplianceType"]

    def __new__(cls, value: object) -> "ComplianceType":
        code = str(value).strip().upper()
        if not COMPLIANCE_CODE_RE.fullmatch(code):
            raise ValueError(
                "Compliance code must be 2-40 characters: capital letters, digits and underscores, "
                "starting with a letter"
            )
        return super().__new__(cls, code)

    @property
    def value(self) -> str:
        return str(self)

    def __repr__(self) -> str:
        return f"ComplianceType({str(self)!r})"

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type: Any, handler: Any) -> Any:
        from pydantic_core import core_schema

        return core_schema.no_info_after_validator_function(
            cls,
            core_schema.str_schema(),
            serialization=core_schema.plain_serializer_function_ser_schema(str),
        )


BUILTIN_COMPLIANCE_CODES: tuple[str, ...] = (
    "CAC",
    "FIRS",
    "ITF",
    "NSITF",
    "PENCOM",
    "GROUP_LIFE_INSURANCE",
    "ACCOUNT_AUDITING",
    "SCUML",
    "BPP_FEDERAL",
    "BPP_STATE",
    "NITDA",
    "CPN",
    "NCS",
)
for _code in BUILTIN_COMPLIANCE_CODES:
    setattr(ComplianceType, _code, ComplianceType(_code))
del _code


class ComplianceMode(str, Enum):
    NEW = "NEW"
    RENEWAL = "RENEWAL"
    PROCESS = "PROCESS"
    REGISTRATION = "REGISTRATION"


class CompanyRegistrationType(str, Enum):
    EXISTING = "EXISTING"
    NEW = "NEW"


class CartStatus(str, Enum):
    OPEN = "OPEN"
    CHECKOUT = "CHECKOUT"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
