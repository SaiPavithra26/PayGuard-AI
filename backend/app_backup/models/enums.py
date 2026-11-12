"""Enumerations for PayLater Shield domain entities."""

from enum import StrEnum


class IdentityStatus(StrEnum):
    """Customer identity verification status."""

    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    PENDING = "PENDING"
    SUSPENDED = "SUSPENDED"


class TransactionStatus(StrEnum):
    """Status of an attempted or completed transaction."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class PaymentStatus(StrEnum):
    """Status of an installment obligation."""

    PENDING = "PENDING"
    PAID = "PAID"
    OVERDUE = "OVERDUE"
    CANCELLED = "CANCELLED"


class RiskLevel(StrEnum):
    """Categorical risk assessment level."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class RecommendedAction(StrEnum):
    """Decision action recommended by PayLater Shield."""

    CONTINUE = "CONTINUE"
    ADDITIONAL_VERIFICATION = "ADDITIONAL_VERIFICATION"
    MANUAL_REVIEW = "MANUAL_REVIEW"

