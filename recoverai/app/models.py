from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class RecoveryCase(BaseModel):
    """Represents a customer overdue payment situation."""

    case_id: str = Field(..., example="RC-1001")
    customer_id: str = Field(..., example="CUST-001")
    customer_name: Optional[str] = Field(default=None, example="Avery Smith")
    invoice_id: str = Field(..., example="INV-2024-001")
    amount_due: float = Field(..., gt=0, example=149.99)
    currency: str = Field(default="USD", min_length=3, max_length=3, example="USD")
    due_date: datetime = Field(..., example="2024-10-15T00:00:00")
    recovery_status: Literal["open", "in_progress", "resolved", "escalated"] = Field(
        default="open",
        example="open",
    )
    failure_reason: Optional[str] = Field(default=None, example="Card expired")
    previous_payment_attempts: list[str] = Field(default_factory=list)
    previous_customer_interactions: list[str] = Field(default_factory=list)
    payment_status: Optional[str] = Field(default="pending", example="failed")

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        return value.upper()


class RecoveryPlan(BaseModel):
    """A suggested plan for recovering a payment."""

    plan_id: str = Field(..., example="PLAN-001")
    case_id: str = Field(..., example="RC-1001")
    strategy: str = Field(..., example="Send a friendly reminder and offer a retry option.")
    priority: Literal["low", "medium", "high"] = Field(default="medium", example="high")
    estimated_recovery_rate: float = Field(..., ge=0, le=100, example=78.5)
    next_action: str = Field(..., example="Send customer email and prepare secure retry flow.")


class PaymentStatus(BaseModel):
    """Simple payment-related status model."""

    payment_id: str = Field(..., example="PAY-12345")
    status: Literal["pending", "approved", "failed", "refunded"] = Field(..., example="failed")
    amount: float = Field(..., gt=0, example=149.99)
    currency: str = Field(default="USD", min_length=3, max_length=3, example="USD")
    last_updated: datetime = Field(default_factory=datetime.utcnow, example="2024-10-15T09:20:00")


class RecoveryClassificationResult(BaseModel):
    """Structured classification output from the recovery model."""

    category: Literal[
        "PAYMENT_METHOD_FAILURE",
        "FORGOT_PAYMENT",
        "FINANCIAL_HARDSHIP",
        "PAYMENT_DISPUTE",
        "SUSPICIOUS_ACTIVITY",
        "UNKNOWN",
    ] = Field(..., example="PAYMENT_METHOD_FAILURE")
    confidence: float = Field(..., ge=0, le=1, example=0.95)
    explanation: str = Field(..., example="The payment method was declined.")
    recommended_action: str = Field(..., example="REQUEST_PAYMENT_METHOD_UPDATE")
    requires_human_review: bool = Field(default=False, example=False)


class RecoveryPlanResult(BaseModel):
    """Structured recovery plan output for a case."""

    strategy: str = Field(..., example="Offer a secure retry option or updated payment method flow.")
    recommended_next_action: str = Field(..., example="Ask customer to confirm a preferred payment method.")
    customer_message: str = Field(..., example="We can help you update your payment details and continue securely.")
    reason: str = Field(..., example="The issue appears to be a declined payment method.")
    human_review_required: bool = Field(default=False, example=False)


class RecoveryChatRequest(BaseModel):
    message: str = Field(..., min_length=1, example="My card does not have sufficient balance right now.")


class RecoveryChatResponse(BaseModel):
    reply: str = Field(..., example="I understand. You can update your payment method or explore assistance options.")
    category: str = Field(..., example="FINANCIAL_HARDSHIP")
    suggested_action: str = Field(..., example="OFFER_ASSISTANCE")
    requires_approval: bool = Field(default=False, example=False)


class RecoveryActionRequest(BaseModel):
    action: Literal["create_payment_order", "request_human_review"] = Field(..., example="create_payment_order")
    approved: bool = Field(default=False, example=False)
    amount: Optional[float] = Field(default=None, gt=0, example=5.0)
    currency: Optional[str] = Field(default="USD", example="USD")
    reason: Optional[str] = Field(default=None, example="Customer explicitly approved the payment action.")


class RecoveryHistoryEntry(BaseModel):
    role: Literal["assistant", "customer", "system"] = Field(..., example="assistant")
    message: str = Field(..., example="I understand your payment issue.")
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class RecoveryHistoryResponse(BaseModel):
    case_id: str = Field(..., example="RC-1001")
    conversation: list[RecoveryHistoryEntry] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
