"""Explainable multi-factor risk-scoring engine for PayLater Shield prototype."""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence, Set
from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.enums import (
    IdentityStatus,
    PaymentStatus,
    RecommendedAction,
    RiskLevel,
    TransactionStatus,
)
from app.models.installment import Installment
from app.models.risk_assessment import RiskAssessment
from app.models.transaction import Transaction
from app.services.exposure import ExposureAnalyzer
from app.services.velocity import VelocityAnalyzer


@dataclass(frozen=True)
class RiskEngineConfig:
    """Configurable scoring weights, evaluation thresholds, and decision tiers."""

    # Signal Weights (Maximum total: 100 points)
    velocity_weight: int = 25
    exposure_weight: int = 20
    identity_weight: int = 20
    device_weight: int = 15
    repayment_weight: int = 20

    # Operational Thresholds
    velocity_window_hours: int = 24
    velocity_count_threshold: int = 3
    exposure_threshold: Decimal = Decimal("300.00")

    # Risk Tier Boundaries
    low_max_score: int = 29      # 0 to 29 -> LOW
    medium_max_score: int = 59   # 30 to 59 -> MEDIUM
                                 # 60 to 100 -> HIGH

    # Set of high-risk synthetic device signals
    suspicious_device_signals: Set[str] = field(
        default_factory=lambda: {
            "SUSPICIOUS_EMULATOR",
            "TOR_EXIT_NODE",
            "RAPID_IP_SWITCH",
            "KNOWN_FRAUD_DEVICE",
            "HIGH_RISK_PROXY",
        }
    )


@dataclass(frozen=True)
class SignalAuditDetail:
    """Detailed audit trail for an individual risk factor evaluation."""

    signal_name: str
    weight: int
    score: int
    triggered: bool
    explanation: Optional[str]
    metrics: Dict[str, Any]


@dataclass(frozen=True)
class RiskAssessmentResult:
    """Complete, explainable result of a PayLater Shield risk evaluation."""

    customer_id: str
    risk_score: int
    risk_level: RiskLevel
    recommended_action: RecommendedAction
    reasons: List[str]
    signals: Dict[str, SignalAuditDetail]
    evaluated_at: datetime
    metadata: Dict[str, Any]

    def to_audit_dict(self) -> Dict[str, Any]:
        """Convert intermediate evaluation state to structured JSON for auditable storage."""
        return {
            "customer_id": self.customer_id,
            "risk_score": self.risk_score,
            "risk_level": self.risk_level.value,
            "recommended_action": self.recommended_action.value,
            "reasons": self.reasons,
            "signals": {k: asdict(v) for k, v in self.signals.items()},
            "evaluated_at": self.evaluated_at.isoformat(),
            "metadata": self.metadata,
        }


class RiskEngine:
    """Deterministic, explainable multi-factor underwriting risk evaluator."""

    def __init__(self, config: Optional[RiskEngineConfig] = None) -> None:
        """Initialize the risk engine with configurable rules and weights."""
        self.config = config or RiskEngineConfig()

        # Dedicated sub-analyzers
        self.velocity_analyzer = VelocityAnalyzer(
            window_hours=self.config.velocity_window_hours,
            count_threshold=self.config.velocity_count_threshold,
            weight=self.config.velocity_weight,
        )
        self.exposure_analyzer = ExposureAnalyzer(
            threshold=self.config.exposure_threshold,
            weight=self.config.exposure_weight,
        )

    def evaluate(
        self,
        customer: Customer,
        transactions: Optional[Sequence[Transaction]] = None,
        installments: Optional[Sequence[Installment]] = None,
        session_device_signal: Optional[str] = None,
        evaluation_time: Optional[datetime] = None,
    ) -> RiskAssessmentResult:
        """Evaluate a customer request and produce a deterministic, explainable risk assessment.

        Args:
            customer: The Customer entity.
            transactions: Historical/recent transactions (falls back to customer.transactions).
            installments: Repayment installment schedules (falls back to customer.installments).
            session_device_signal: Optional override for real-time device telemetry.
            evaluation_time: Anchor evaluation time in UTC (defaults to current UTC time).

        Returns:
            RiskAssessmentResult with score, level, action, reasons, and full signal audit.
        """
        ref_time = evaluation_time or datetime.now(timezone.utc)
        if ref_time.tzinfo is None:
            ref_time = ref_time.replace(tzinfo=timezone.utc)

        # Resolve entity collections
        txns = list(transactions if transactions is not None else getattr(customer, "transactions", []))
        insts = list(installments if installments is not None else getattr(customer, "installments", []))

        # Evaluate individual signals
        signals: Dict[str, SignalAuditDetail] = {}
        reasons: List[str] = []

        # 1. Transaction Velocity Signal
        vel_result = self.velocity_analyzer.analyze(txns, evaluation_time=ref_time)
        signals["velocity"] = SignalAuditDetail(
            signal_name="Transaction Velocity",
            weight=self.config.velocity_weight,
            score=vel_result.signal_score,
            triggered=vel_result.is_velocity_elevated,
            explanation=vel_result.reason,
            metrics={
                "window_hours": vel_result.window_hours,
                "transaction_count": vel_result.transaction_count,
                "total_amount": float(vel_result.total_amount),
                "tx_count_1h": vel_result.tx_count_1h,
                "tx_count_24h": vel_result.tx_count_24h,
                "tx_amount_24h": float(vel_result.tx_amount_24h),
                "tx_count_7d": vel_result.tx_count_7d,
                "is_burst_pattern": vel_result.is_burst_pattern,
            },
        )
        if vel_result.reason:
            reasons.append(vel_result.reason)

        # 2. Outstanding Exposure Signal
        exp_result = self.exposure_analyzer.analyze(
            installments=insts,
            transactions=txns,
            evaluation_time=ref_time,
        )
        signals["exposure"] = SignalAuditDetail(
            signal_name="Outstanding Credit Exposure",
            weight=self.config.exposure_weight,
            score=exp_result.signal_score,
            triggered=exp_result.is_exposure_elevated,
            explanation=exp_result.reason,
            metrics={
                "total_unpaid_amount": float(exp_result.total_unpaid_amount),
                "total_outstanding_amount": float(exp_result.total_outstanding_amount),
                "pending_amount": float(exp_result.pending_amount),
                "overdue_amount": float(exp_result.overdue_amount),
                "due_next_7d_amount": float(exp_result.due_next_7d_amount),
                "active_installment_count": exp_result.active_installment_count,
                "overdue_installment_count": exp_result.overdue_installment_count,
                "failed_repayments_count": exp_result.failed_repayments_count,
            },
        )
        if exp_result.reason:
            reasons.append(exp_result.reason)

        # 3. Identity Verification Signal
        id_score = 0
        id_triggered = False
        id_reason = None
        if customer.identity_status in (IdentityStatus.PENDING, IdentityStatus.UNVERIFIED):
            id_score = self.config.identity_weight
            id_triggered = True
            id_reason = (
                f"Customer identity verification is currently '{customer.identity_status.value}' "
                f"(requires formal verification)."
            )
        elif customer.identity_status == IdentityStatus.SUSPENDED:
            id_score = self.config.identity_weight
            id_triggered = True
            id_reason = "Customer account identity is currently suspended."

        signals["identity"] = SignalAuditDetail(
            signal_name="Identity Verification Status",
            weight=self.config.identity_weight,
            score=id_score,
            triggered=id_triggered,
            explanation=id_reason,
            metrics={"identity_status": customer.identity_status.value},
        )
        if id_reason:
            reasons.append(id_reason)

        # 4. Device / Session Risk Signal
        # Use explicit runtime signal if provided, else customer's persisted device signal
        effective_device_signal = (
            session_device_signal
            if session_device_signal is not None
            else customer.device_risk_signal
        )
        dev_score = 0
        dev_triggered = False
        dev_reason = None

        if effective_device_signal and effective_device_signal.upper() in self.config.suspicious_device_signals:
            dev_score = self.config.device_weight
            dev_triggered = True
            dev_reason = (
                f"Suspicious device/session telemetry detected: '{effective_device_signal}'."
            )

        signals["device"] = SignalAuditDetail(
            signal_name="Device Risk Telemetry",
            weight=self.config.device_weight,
            score=dev_score,
            triggered=dev_triggered,
            explanation=dev_reason,
            metrics={"device_signal": effective_device_signal},
        )
        if dev_reason:
            reasons.append(dev_reason)

        # 5. Repayment Behaviour Signal (Evaluates available history without penalizing missing history)
        repay_score = 0
        repay_triggered = False
        repay_reason = None

        overdue_insts = [i for i in insts if i.payment_status == PaymentStatus.OVERDUE]
        failed_txns = [t for t in txns if t.transaction_status in (TransactionStatus.FAILED, TransactionStatus.DECLINED)]

        if overdue_insts or failed_txns:
            repay_score = self.config.repayment_weight
            repay_triggered = True
            details = []
            if overdue_insts:
                details.append(f"{len(overdue_insts)} overdue installment(s)")
            if failed_txns:
                details.append(f"{len(failed_txns)} failed/declined transaction attempt(s)")
            repay_reason = f"Adverse repayment history detected: {', '.join(details)}."

        signals["repayment"] = SignalAuditDetail(
            signal_name="Repayment Behavior",
            weight=self.config.repayment_weight,
            score=repay_score,
            triggered=repay_triggered,
            explanation=repay_reason,
            metrics={
                "overdue_installment_count": len(overdue_insts),
                "failed_transaction_count": len(failed_txns),
                "total_installments_recorded": len(insts),
            },
        )
        if repay_reason:
            reasons.append(repay_reason)

        # Aggregate total score (clamped 0 to 100)
        total_score = min(
            100,
            max(
                0,
                vel_result.signal_score
                + exp_result.signal_score
                + id_score
                + dev_score
                + repay_score,
            ),
        )

        # Categorize risk level and determine recommended action
        if total_score <= self.config.low_max_score:
            risk_level = RiskLevel.LOW
            recommended_action = RecommendedAction.CONTINUE
            if not reasons:
                reasons.append("Clean customer profile: verified identity, reliable payment history, and low exposure.")
        elif total_score <= self.config.medium_max_score:
            risk_level = RiskLevel.MEDIUM
            recommended_action = RecommendedAction.ADDITIONAL_VERIFICATION
        else:
            risk_level = RiskLevel.HIGH
            recommended_action = RecommendedAction.MANUAL_REVIEW

        return RiskAssessmentResult(
            customer_id=customer.customer_id,
            risk_score=total_score,
            risk_level=risk_level,
            recommended_action=recommended_action,
            reasons=reasons,
            signals=signals,
            evaluated_at=ref_time,
            metadata={
                "transactions_analyzed": len(txns),
                "installments_analyzed": len(insts),
                "model_version": "v1.0.0-prototype",
            },
        )

    def evaluate_and_persist(
        self,
        session: Session,
        customer_id: str,
        assessment_id: Optional[str] = None,
        session_device_signal: Optional[str] = None,
        evaluation_time: Optional[datetime] = None,
    ) -> RiskAssessment:
        """Evaluate a customer and record the auditable result into the database.

        Args:
            session: SQLAlchemy database session.
            customer_id: Target customer identifier.
            assessment_id: Optional custom identifier (auto-generated if omitted).
            session_device_signal: Optional live session telemetry signal.
            evaluation_time: Anchor evaluation time in UTC.

        Returns:
            Persisted RiskAssessment ORM entity.
        """
        customer = session.get(Customer, customer_id)
        if customer is None:
            raise ValueError(f"Customer '{customer_id}' does not exist")

        result = self.evaluate(
            customer=customer,
            session_device_signal=session_device_signal,
            evaluation_time=evaluation_time,
        )

        aid = assessment_id or f"RSK_{customer_id}_{int(result.evaluated_at.timestamp())}"
        assessment = RiskAssessment(
            assessment_id=aid,
            customer_id=customer.customer_id,
            risk_score=result.risk_score,
            risk_level=result.risk_level,
            risk_reasons=result.to_audit_dict(),
            recommended_action=result.recommended_action,
            created_at=result.evaluated_at,
        )
        session.add(assessment)
        session.commit()
        return assessment


