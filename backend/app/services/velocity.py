"""Transaction velocity analysis and pattern detection service for PayLater Shield."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Sequence

from app.models.enums import TransactionStatus
from app.models.transaction import Transaction


@dataclass(frozen=True)
class VelocityConfig:
    """Configurable thresholds and lookback windows for velocity analysis."""

    window_1h_hours: int = 1
    window_24h_hours: int = 24
    window_7d_days: int = 7

    # Thresholds for triggering velocity patterns
    threshold_1h_count: int = 2          # >= 2 transactions in 1 hour indicates rapid burst
    threshold_24h_count: int = 3         # >= 3 transactions in 24 hours indicates elevated velocity
    threshold_24h_amount: Decimal = Decimal("500.00")  # >= $500 in 24 hours indicates large volume surge
    threshold_7d_count: int = 8          # >= 8 transactions in 7 days indicates sustained high frequency

    # Risk scoring weight for engine integration
    weight: int = 25


@dataclass(frozen=True)
class VelocityAnalysisResult:
    """Comprehensive measurements and triggered signals from velocity analysis."""

    tx_count_1h: int
    tx_count_24h: int
    tx_amount_24h: Decimal
    tx_count_7d: int
    is_velocity_elevated: bool
    is_burst_pattern: bool
    signals_triggered: List[str]
    signal_score: int
    max_weight: int
    reason: Optional[str] = None
    window_hours: int = 24  # For backwards-compatibility with RiskEngine

    @property
    def transaction_count(self) -> int:
        """Alias for 24-hour transaction count for engine compatibility."""
        return self.tx_count_24h

    @property
    def total_amount(self) -> Decimal:
        """Alias for 24-hour transaction total amount for engine compatibility."""
        return self.tx_amount_24h


class VelocityAnalyzer:
    """Detects multi-window transaction velocity and distinguishes normal shopping from suspicious bursts."""

    def __init__(
        self,
        config: Optional[VelocityConfig] = None,
        # Optional backward-compatible constructor arguments
        window_hours: Optional[int] = None,
        count_threshold: Optional[int] = None,
        weight: Optional[int] = None,
    ) -> None:
        """Initialize VelocityAnalyzer with custom or default configuration."""
        if config:
            self.config = config
        else:
            w_24h = window_hours if window_hours is not None else 24
            c_thresh = count_threshold if count_threshold is not None else 3
            wt = weight if weight is not None else 25
            self.config = VelocityConfig(
                window_24h_hours=w_24h,
                threshold_24h_count=c_thresh,
                weight=wt,
            )

    def analyze(
        self,
        transactions: Sequence[Transaction],
        evaluation_time: Optional[datetime] = None,
    ) -> VelocityAnalysisResult:
        """Calculate transaction velocity metrics across 1h, 24h, and 7d rolling windows.

        Args:
            transactions: List of historical and recent customer transactions.
            evaluation_time: Anchor evaluation time in UTC (defaults to current UTC time).

        Returns:
            VelocityAnalysisResult with granular metrics, triggered signals, score, and explanation.
        """
        ref_time = evaluation_time or datetime.now(timezone.utc)
        if ref_time.tzinfo is None:
            ref_time = ref_time.replace(tzinfo=timezone.utc)

        # Deduplicate transactions by transaction_id to avoid counting duplicates
        unique_txns: Dict[str, Transaction] = {}
        for txn in transactions:
            if txn.amount is None or txn.amount < 0:
                raise ValueError(f"Invalid transaction amount: {txn.amount}")
            unique_txns[txn.transaction_id] = txn

        window_1h_start = ref_time - timedelta(hours=self.config.window_1h_hours)
        window_24h_start = ref_time - timedelta(hours=self.config.window_24h_hours)
        window_7d_start = ref_time - timedelta(days=self.config.window_7d_days)

        count_1h = 0
        count_24h = 0
        amount_24h = Decimal("0.00")
        count_7d = 0

        for txn in unique_txns.values():
            txn_time = txn.timestamp
            if txn_time.tzinfo is None:
                txn_time = txn_time.replace(tzinfo=timezone.utc)

            # Exclude future-dated transactions relative to evaluation anchor
            if txn_time > ref_time:
                continue

            # Exclude explicitly failed technical transactions from valid purchase velocity
            if txn.transaction_status == TransactionStatus.FAILED:
                continue

            # Check 7-day window
            if window_7d_start <= txn_time <= ref_time:
                count_7d += 1

                # Check 24-hour window
                if window_24h_start <= txn_time <= ref_time:
                    count_24h += 1
                    amount_24h += txn.amount

                    # Check 1-hour window
                    if window_1h_start <= txn_time <= ref_time:
                        count_1h += 1

        # Evaluate distinct velocity patterns
        signals_triggered: List[str] = []

        is_burst = count_1h >= self.config.threshold_1h_count
        if is_burst:
            signals_triggered.append(f"RAPID_BURST_1H ({count_1h} txns in 1h)")

        is_high_count_24h = count_24h >= self.config.threshold_24h_count
        if is_high_count_24h:
            signals_triggered.append(f"HIGH_VELOCITY_24H ({count_24h} txns in 24h)")

        # High amount is only considered suspicious velocity when accompanied by multiple transactions
        is_high_amount_burst = (count_24h >= 2) and (amount_24h >= self.config.threshold_24h_amount)
        if is_high_amount_burst:
            signals_triggered.append(f"HIGH_AMOUNT_BURST_24H (${amount_24h:.2f} across {count_24h} txns)")

        is_sustained_7d = count_7d >= self.config.threshold_7d_count
        if is_sustained_7d:
            signals_triggered.append(f"HIGH_FREQUENCY_7D ({count_7d} txns in 7d)")

        # Velocity is elevated if rapid burst in 1h or high count in 24h or rapid multi-txn spending surge
        is_elevated = is_burst or is_high_count_24h or is_high_amount_burst

        reason = None
        if is_elevated:
            details = []
            if is_burst:
                details.append(f"{count_1h} transaction(s) in the last hour")
            if is_high_count_24h:
                details.append(f"{count_24h} transactions in the last 24 hours")
            if is_high_amount_burst:
                details.append(f"${amount_24h:.2f} total spend across {count_24h} transactions in 24 hours")
            reason = f"High purchase velocity detected: {', '.join(details)}."

        signal_score = self.config.weight if is_elevated else 0

        return VelocityAnalysisResult(
            tx_count_1h=count_1h,
            tx_count_24h=count_24h,
            tx_amount_24h=amount_24h,
            tx_count_7d=count_7d,
            is_velocity_elevated=is_elevated,
            is_burst_pattern=is_burst,
            signals_triggered=signals_triggered,
            signal_score=signal_score,
            max_weight=self.config.weight,
            reason=reason,
            window_hours=self.config.window_24h_hours,
        )


def detect_velocity(
    transactions: Sequence[Transaction],
    evaluation_time: Optional[datetime] = None,
    config: Optional[VelocityConfig] = None,
) -> VelocityAnalysisResult:
    """Convenience function to evaluate transaction velocity."""
    analyzer = VelocityAnalyzer(config=config)
    return analyzer.analyze(transactions=transactions, evaluation_time=evaluation_time)

