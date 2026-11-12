"""Credit exposure and installment burden analysis service for PayLater Shield."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, Optional, Sequence

from backend.app.models.enums import PaymentStatus, TransactionStatus
from backend.app.models.installment import Installment
from backend.app.models.transaction import Transaction


@dataclass(frozen=True)
class ExposureConfig:
    """Configurable parameters for credit exposure analysis."""

    exposure_threshold: Decimal = Decimal("300.00")
    due_window_days: int = 7
    weight: int = 20


@dataclass(frozen=True)
class ExposureAnalysisResult:
    """Detailed measurements and exposure metrics for a customer."""

    total_outstanding_amount: Decimal
    total_overdue_amount: Decimal
    due_next_7d_amount: Decimal
    active_installment_count: int
    overdue_installment_count: int
    failed_repayments_count: int
    is_exposure_elevated: bool
    signal_score: int
    max_weight: int
    threshold: Decimal
    reason: Optional[str] = None

    @property
    def total_unpaid_amount(self) -> Decimal:
        """Alias for total outstanding amount for engine compatibility."""
        return self.total_outstanding_amount

    @property
    def overdue_amount(self) -> Decimal:
        """Alias for total overdue amount for engine compatibility."""
        return self.total_overdue_amount

    @property
    def pending_amount(self) -> Decimal:
        """Portion of outstanding debt that is current (not yet overdue)."""
        return max(Decimal("0.00"), self.total_outstanding_amount - self.total_overdue_amount)


class ExposureAnalyzer:
    """Calculates granular installment exposure, overdue balances, and upcoming repayment schedules."""

    def __init__(
        self,
        config: Optional[ExposureConfig] = None,
        # Optional backward-compatible constructor arguments
        threshold: Optional[Decimal] = None,
        weight: Optional[int] = None,
    ) -> None:
        """Initialize ExposureAnalyzer with custom or default configuration."""
        if config:
            self.config = config
        else:
            thresh = threshold if threshold is not None else Decimal("300.00")
            wt = weight if weight is not None else 20
            self.config = ExposureConfig(
                exposure_threshold=thresh,
                weight=wt,
            )

    @property
    def threshold(self) -> Decimal:
        """Expose threshold for backward compatibility."""
        return self.config.exposure_threshold

    @property
    def weight(self) -> int:
        """Expose weight for backward compatibility."""
        return self.config.weight

    def analyze(
        self,
        installments: Sequence[Installment],
        transactions: Optional[Sequence[Transaction]] = None,
        evaluation_time: Optional[datetime] = None,
    ) -> ExposureAnalysisResult:
        """Evaluate customer credit exposure, upcoming payments, and repayment delinquency.

        Args:
            installments: Repayment installment records.
            transactions: Optional historical transactions to detect failed payment attempts.
            evaluation_time: Anchor evaluation time in UTC (defaults to current UTC time).

        Returns:
            ExposureAnalysisResult with exact Decimal metrics and triggered flags.
        """
        ref_time = evaluation_time or datetime.now(timezone.utc)
        if ref_time.tzinfo is None:
            ref_time = ref_time.replace(tzinfo=timezone.utc)

        # 1. Deduplicate installments by unique installment_id
        unique_installments: Dict[str, Installment] = {}
        for inst in installments:
            if inst.amount is None or inst.amount < 0:
                raise ValueError(f"Invalid installment amount: {inst.amount}")
            unique_installments[inst.installment_id] = inst

        # 2. Deduplicate transactions if provided
        unique_txns: Dict[str, Transaction] = {}
        if transactions:
            for txn in transactions:
                if txn.amount is None or txn.amount < 0:
                    raise ValueError(f"Invalid transaction amount: {txn.amount}")
                unique_txns[txn.transaction_id] = txn

        due_7d_cutoff = ref_time + timedelta(days=self.config.due_window_days)

        total_outstanding = Decimal("0.00")
        total_overdue = Decimal("0.00")
        due_next_7d = Decimal("0.00")
        active_count = 0
        overdue_count = 0
        failed_repayments = 0

        # Evaluate each unique installment
        for inst in unique_installments.values():
            inst_due = inst.due_date
            if inst_due.tzinfo is None:
                inst_due = inst_due.replace(tzinfo=timezone.utc)

            # Rule: Paid installments must not be included in outstanding exposure
            if inst.payment_status == PaymentStatus.PAID:
                continue

            # Rule: Cancelled plans are not active debt, but count as failed/cancelled arrangements
            if inst.payment_status == PaymentStatus.CANCELLED:
                failed_repayments += 1
                continue

            # Unpaid active installment (PENDING or OVERDUE)
            total_outstanding += inst.amount
            active_count += 1

            # Rule: Overdue installments must be identified using due dates and unpaid status
            is_overdue = (inst.payment_status == PaymentStatus.OVERDUE) or (
                inst.payment_status == PaymentStatus.PENDING and inst_due < ref_time
            )

            if is_overdue:
                total_overdue += inst.amount
                overdue_count += 1
                failed_repayments += 1
            else:
                # Rule: An installment due within the next 7 days must not be counted as paid
                if ref_time <= inst_due <= due_7d_cutoff:
                    due_next_7d += inst.amount

        # Count failed/declined transactions if transaction history was supplied
        for txn in unique_txns.values():
            if txn.transaction_status in (TransactionStatus.FAILED, TransactionStatus.DECLINED):
                failed_repayments += 1

        is_elevated = total_outstanding >= self.config.exposure_threshold

        reason = None
        if is_elevated:
            reason = (
                f"High cumulative outstanding credit exposure: ${total_outstanding:.2f} unpaid "
                f"across {active_count} active installments (threshold: >= ${self.config.exposure_threshold:.2f})."
            )

        signal_score = self.config.weight if is_elevated else 0

        return ExposureAnalysisResult(
            total_outstanding_amount=total_outstanding,
            total_overdue_amount=total_overdue,
            due_next_7d_amount=due_next_7d,
            active_installment_count=active_count,
            overdue_installment_count=overdue_count,
            failed_repayments_count=failed_repayments,
            is_exposure_elevated=is_elevated,
            signal_score=signal_score,
            max_weight=self.config.weight,
            threshold=self.config.exposure_threshold,
            reason=reason,
        )


def analyze_exposure(
    installments: Sequence[Installment],
    transactions: Optional[Sequence[Transaction]] = None,
    evaluation_time: Optional[datetime] = None,
    config: Optional[ExposureConfig] = None,
) -> ExposureAnalysisResult:
    """Convenience function to evaluate credit exposure."""
    analyzer = ExposureAnalyzer(config=config)
    return analyzer.analyze(
        installments=installments,
        transactions=transactions,
        evaluation_time=evaluation_time,
    )
