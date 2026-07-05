from enum import Enum


class ComplianceStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    PENDING = "PENDING"
    IN_REVIEW = "IN_REVIEW"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"


class UserRole(str, Enum):
    CLIENT = "CLIENT"
    AGENT = "AGENT"
    ADMIN = "ADMIN"


class OAuthProvider(str, Enum):
    GOOGLE = "google"


class ComplianceType(str, Enum):
    CAC = "CAC"
    FIRS = "FIRS"
    ITF = "ITF"
    NSITF = "NSITF"
    PENCOM = "PENCOM"
    GROUP_LIFE_INSURANCE = "GROUP_LIFE_INSURANCE"
    ACCOUNT_AUDITING = "ACCOUNT_AUDITING"
    SCUML = "SCUML"
    BPP_FEDERAL = "BPP_FEDERAL"
    BPP_STATE = "BPP_STATE"


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
