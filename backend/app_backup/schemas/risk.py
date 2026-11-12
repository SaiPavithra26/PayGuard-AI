"""Pydantic schemas for risk assessment requests and responses."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

from backend.app.models.enums import IdentityStatus, RecommendedAction, RiskLevel


class RiskAssessmentRequest(BaseModel):
    """Payload for requesting a PayLater pre-purchase risk evaluation."""

    customer_id: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Unique customer identifier",
        examples=["CUST_SYNTH_0001"],
    )
    amount: Decimal = Field(
        ...,
        gt=0,
        description="Proposed transaction amount in major currency units",
        examples=[Decimal("129.99")],
    )
    merchant: str = Field(
        default="General Merchant",
        min_length=1,
        max_length=100,
        description="Merchant identifier or store name",
        examples=["SYNTH_TECH_MART"],
    )
    device_risk_signal: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Optional real-time device telemetry signal for the session",
        examples=["TRUSTED_DEVICE"],
    )

    model_config = ConfigDict(extra="forbid")


class SignalDetailSchema(BaseModel):
    """Audit detail for an individual risk factor."""

    signal_name: str
    weight: int
    score: int
    triggered: bool
    explanation: Optional[str] = None
    metrics: Dict[str, Any] = Field(default_factory=dict)


class VelocitySummarySchema(BaseModel):
    """Summary of transaction velocity across rolling windows."""

    tx_count_1h: int
    tx_count_24h: int
    tx_amount_24h: Decimal
    tx_count_7d: int
    is_burst_pattern: bool
    is_velocity_elevated: bool
    signals_triggered: List[str] = Field(default_factory=list)


class ExposureSummarySchema(BaseModel):
    """Summary of customer credit exposure and installment burden."""

    total_outstanding_amount: Decimal
    total_overdue_amount: Decimal
    due_next_7d_amount: Decimal
    active_installment_count: int
    overdue_installment_count: int
    failed_repayments_count: int
    is_exposure_elevated: bool


class RiskAssessmentResponse(BaseModel):
    """Evaluation result returned by the risk assessment endpoint."""

    assessment_id: str
    customer_id: str
    proposed_amount: Decimal
    merchant: str
    risk_score: int
    risk_level: RiskLevel
    recommended_action: RecommendedAction
    reasons: List[str]
    evaluated_at: datetime
    signals: Dict[str, SignalDetailSchema]
    velocity_summary: VelocitySummarySchema
    exposure_summary: ExposureSummarySchema

    model_config = ConfigDict(from_attributes=True)


class CustomerRiskProfileResponse(BaseModel):
    """Customer profile including latest risk assessment and exposure metrics."""

    customer_id: str
    identity_status: IdentityStatus
    device_risk_signal: Optional[str] = None
    account_created_at: datetime
    latest_assessment: Optional[RiskAssessmentResponse] = None
    exposure_summary: ExposureSummarySchema
    velocity_summary: VelocitySummarySchema

    model_config = ConfigDict(from_attributes=True)

