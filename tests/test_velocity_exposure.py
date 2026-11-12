"""Comprehensive test suite for Phase 4: Velocity detector and Exposure analyzer."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest

from backend.app.models.enums import PaymentStatus, TransactionStatus
from backend.app.models.installment import Installment
from backend.app.models.transaction import Transaction
from backend.app.services.exposure import (
    ExposureAnalysisResult,
    ExposureAnalyzer,
    ExposureConfig,
    analyze_exposure,
)
from backend.app.services.velocity import (
    VelocityAnalysisResult,
    VelocityAnalyzer,
    VelocityConfig,
    detect_velocity,
)

# Reference anchor time for all relative calculations
REF_TIME = datetime(2026, 11, 12, 12, 0, 0, tzinfo=timezone.utc)


# ===========================================================================
# Part A: Transaction Velocity Detector Tests
# ===========================================================================

def test_velocity_no_transactions():
    """Verify velocity detector handles customers with zero transactions."""
    analyzer = VelocityAnalyzer()
    result = analyzer.analyze([], evaluation_time=REF_TIME)

    assert result.tx_count_1h == 0
    assert result.tx_count_24h == 0
    assert result.tx_amount_24h == Decimal("0.00")
    assert result.tx_count_7d == 0
    assert not result.is_velocity_elevated
    assert not result.is_burst_pattern
    assert result.signals_triggered == []
    assert result.signal_score == 0
    assert result.reason is None


def test_velocity_one_transaction():
    """Verify velocity detector with single normal purchase does not trigger risk."""
    analyzer = VelocityAnalyzer()
    txn = Transaction(
        transaction_id="TXN_SINGLE_1",
        customer_id="CUST_1",
        amount=Decimal("75.50"),
        merchant="Retail Mart",
        timestamp=REF_TIME - timedelta(minutes=30),
        transaction_status=TransactionStatus.COMPLETED,
    )

    result = analyzer.analyze([txn], evaluation_time=REF_TIME)

    assert result.tx_count_1h == 1
    assert result.tx_count_24h == 1
    assert result.tx_amount_24h == Decimal("75.50")
    assert result.tx_count_7d == 1
    assert not result.is_velocity_elevated
    assert not result.is_burst_pattern
    assert result.signals_triggered == []
    assert result.signal_score == 0


def test_velocity_many_transactions_short_period():
    """Verify rapid checkout burst within 1 hour triggers burst pattern and elevated velocity."""
    analyzer = VelocityAnalyzer()
    # 3 purchases within the last 25 minutes
    txns = [
        Transaction(
            transaction_id=f"TXN_BURST_{i}",
            customer_id="CUST_BURST",
            amount=Decimal("45.00"),
            merchant="Digital Games Store",
            timestamp=REF_TIME - timedelta(minutes=5 * (i + 1)),
            transaction_status=TransactionStatus.APPROVED,
        )
        for i in range(3)
    ]

    result = analyzer.analyze(txns, evaluation_time=REF_TIME)

    assert result.tx_count_1h == 3
    assert result.tx_count_24h == 3
    assert result.tx_amount_24h == Decimal("135.00")
    assert result.tx_count_7d == 3
    assert result.is_burst_pattern
    assert result.is_velocity_elevated
    assert any("RAPID_BURST_1H" in s for s in result.signals_triggered)
    assert result.signal_score == 25
    assert "High purchase velocity detected" in result.reason


def test_velocity_distinguish_high_count_from_suspicious_pattern():
    """Verify detector distinguishes high regular transaction count from suspicious velocity bursts."""
    analyzer = VelocityAnalyzer()

    # Normal active shopper: 6 transactions spaced 1 per day over the past 6 days
    normal_shopper_txns = [
        Transaction(
            transaction_id=f"TXN_NORMAL_{i}",
            customer_id="CUST_NORMAL",
            amount=Decimal("30.00"),
            merchant="Grocery Direct",
            timestamp=REF_TIME - timedelta(days=i + 1),
            transaction_status=TransactionStatus.COMPLETED,
        )
        for i in range(6)
    ]

    normal_result = analyzer.analyze(normal_shopper_txns, evaluation_time=REF_TIME)
    # 0 in 1h, 1 in 24h (on 24h boundary), 6 in 7d
    assert normal_result.tx_count_1h == 0
    assert normal_result.tx_count_24h == 1
    assert normal_result.tx_count_7d == 6
    assert not normal_result.is_velocity_elevated
    assert not normal_result.is_burst_pattern

    # Suspicious pattern: 4 transactions in 3 hours
    suspicious_txns = [
        Transaction(
            transaction_id=f"TXN_SUSP_{i}",
            customer_id="CUST_SUSP",
            amount=Decimal("120.00"),
            merchant="Electronics Outlet",
            timestamp=REF_TIME - timedelta(hours=i + 1),
            transaction_status=TransactionStatus.APPROVED,
        )
        for i in range(4)
    ]

    susp_result = analyzer.analyze(suspicious_txns, evaluation_time=REF_TIME)
    assert susp_result.tx_count_24h == 4
    assert susp_result.is_velocity_elevated
    assert any("HIGH_VELOCITY_24H" in s for s in susp_result.signals_triggered)


def test_velocity_boundary_dates_and_windows():
    """Verify exact edge boundary handling for 1h, 24h, and 7d rolling windows."""
    analyzer = VelocityAnalyzer()

    t_1h_exact = REF_TIME - timedelta(hours=1)
    t_1h_outside = REF_TIME - timedelta(hours=1, seconds=1)
    t_24h_exact = REF_TIME - timedelta(hours=24)
    t_24h_outside = REF_TIME - timedelta(hours=24, seconds=1)
    t_7d_exact = REF_TIME - timedelta(days=7)
    t_7d_outside = REF_TIME - timedelta(days=7, seconds=1)
    t_future = REF_TIME + timedelta(minutes=10)

    txns = [
        Transaction(transaction_id="TXN_1H_EDGE", customer_id="C1", amount=Decimal("10.00"), merchant="M", timestamp=t_1h_exact, transaction_status=TransactionStatus.COMPLETED),
        Transaction(transaction_id="TXN_1H_OUT", customer_id="C1", amount=Decimal("10.00"), merchant="M", timestamp=t_1h_outside, transaction_status=TransactionStatus.COMPLETED),
        Transaction(transaction_id="TXN_24H_EDGE", customer_id="C1", amount=Decimal("10.00"), merchant="M", timestamp=t_24h_exact, transaction_status=TransactionStatus.COMPLETED),
        Transaction(transaction_id="TXN_24H_OUT", customer_id="C1", amount=Decimal("10.00"), merchant="M", timestamp=t_24h_outside, transaction_status=TransactionStatus.COMPLETED),
        Transaction(transaction_id="TXN_7D_EDGE", customer_id="C1", amount=Decimal("10.00"), merchant="M", timestamp=t_7d_exact, transaction_status=TransactionStatus.COMPLETED),
        Transaction(transaction_id="TXN_7D_OUT", customer_id="C1", amount=Decimal("10.00"), merchant="M", timestamp=t_7d_outside, transaction_status=TransactionStatus.COMPLETED),
        Transaction(transaction_id="TXN_FUTURE", customer_id="C1", amount=Decimal("10.00"), merchant="M", timestamp=t_future, transaction_status=TransactionStatus.COMPLETED),
    ]

    result = analyzer.analyze(txns, evaluation_time=REF_TIME)

    # 1h window: only TXN_1H_EDGE
    assert result.tx_count_1h == 1

    # 24h window: TXN_1H_EDGE, TXN_1H_OUT, TXN_24H_EDGE
    assert result.tx_count_24h == 3
    assert result.tx_amount_24h == Decimal("30.00")

    # 7d window: TXN_1H_EDGE, TXN_1H_OUT, TXN_24H_EDGE, TXN_24H_OUT, TXN_7D_EDGE (TXN_7D_OUT & FUTURE excluded)
    assert result.tx_count_7d == 5


def test_velocity_convenience_function():
    """Verify top-level detect_velocity function works equivalently."""
    txns = [
        Transaction(
            transaction_id="TXN_CONV_1",
            customer_id="C1",
            amount=Decimal("20.00"),
            merchant="Shop",
            timestamp=REF_TIME - timedelta(minutes=10),
            transaction_status=TransactionStatus.APPROVED,
        )
    ]
    res = detect_velocity(txns, evaluation_time=REF_TIME)
    assert isinstance(res, VelocityAnalysisResult)
    assert res.tx_count_1h == 1


# ===========================================================================
# Part B: Exposure Analyzer Tests
# ===========================================================================

def test_exposure_no_active_installments():
    """Verify exposure analyzer handles customer with no installments."""
    analyzer = ExposureAnalyzer()
    result = analyzer.analyze([], evaluation_time=REF_TIME)

    assert result.total_outstanding_amount == Decimal("0.00")
    assert result.total_overdue_amount == Decimal("0.00")
    assert result.due_next_7d_amount == Decimal("0.00")
    assert result.active_installment_count == 0
    assert result.overdue_installment_count == 0
    assert result.failed_repayments_count == 0
    assert not result.is_exposure_elevated
    assert result.signal_score == 0
    assert result.reason is None


def test_exposure_paid_installments_excluded():
    """Verify paid installments are strictly excluded from outstanding exposure."""
    analyzer = ExposureAnalyzer()
    insts = [
        Installment(
            installment_id="INST_P_1",
            customer_id="CUST_PAID",
            amount=Decimal("150.00"),
            due_date=REF_TIME - timedelta(days=10),
            payment_status=PaymentStatus.PAID,
            paid_at=REF_TIME - timedelta(days=12),
        ),
        Installment(
            installment_id="INST_P_2",
            customer_id="CUST_PAID",
            amount=Decimal("200.00"),
            due_date=REF_TIME - timedelta(days=5),
            payment_status=PaymentStatus.PAID,
            paid_at=REF_TIME - timedelta(days=6),
        ),
    ]

    result = analyzer.analyze(insts, evaluation_time=REF_TIME)

    assert result.total_outstanding_amount == Decimal("0.00")
    assert result.total_overdue_amount == Decimal("0.00")
    assert result.due_next_7d_amount == Decimal("0.00")
    assert result.active_installment_count == 0
    assert result.overdue_installment_count == 0
    assert result.failed_repayments_count == 0


def test_exposure_overdue_installments():
    """Verify overdue installments are correctly identified by status and due date."""
    analyzer = ExposureAnalyzer()

    # Installment 1: explicitly marked OVERDUE
    inst1 = Installment(
        installment_id="INST_OD_1",
        customer_id="C1",
        amount=Decimal("110.00"),
        due_date=REF_TIME - timedelta(days=15),
        payment_status=PaymentStatus.OVERDUE,
    )
    # Installment 2: marked PENDING but due_date is in the past (overdue by calendar)
    inst2 = Installment(
        installment_id="INST_OD_2",
        customer_id="C1",
        amount=Decimal("90.00"),
        due_date=REF_TIME - timedelta(days=2),
        payment_status=PaymentStatus.PENDING,
    )
    # Installment 3: normal future pending
    inst3 = Installment(
        installment_id="INST_OK_3",
        customer_id="C1",
        amount=Decimal("100.00"),
        due_date=REF_TIME + timedelta(days=20),
        payment_status=PaymentStatus.PENDING,
    )

    result = analyzer.analyze([inst1, inst2, inst3], evaluation_time=REF_TIME)

    assert result.total_outstanding_amount == Decimal("300.00")
    assert result.total_overdue_amount == Decimal("200.00")
    assert result.overdue_installment_count == 2
    assert result.active_installment_count == 3
    assert result.failed_repayments_count == 2


def test_exposure_installments_due_within_7_days():
    """Verify installments due within next 7 days are tracked and not counted as paid."""
    analyzer = ExposureAnalyzer()

    # Due in 3 days ($75.00)
    inst_soon = Installment(
        installment_id="INST_7D_1",
        customer_id="C1",
        amount=Decimal("75.00"),
        due_date=REF_TIME + timedelta(days=3),
        payment_status=PaymentStatus.PENDING,
    )
    # Due in 14 days ($125.00)
    inst_later = Installment(
        installment_id="INST_7D_2",
        customer_id="C1",
        amount=Decimal("125.00"),
        due_date=REF_TIME + timedelta(days=14),
        payment_status=PaymentStatus.PENDING,
    )

    result = analyzer.analyze([inst_soon, inst_later], evaluation_time=REF_TIME)

    # 7-day upcoming due amount
    assert result.due_next_7d_amount == Decimal("75.00")
    # Total outstanding must include upcoming installments (must not be treated as paid)
    assert result.total_outstanding_amount == Decimal("200.00")
    assert result.active_installment_count == 2
    assert result.overdue_installment_count == 0


def test_exposure_multiple_failed_repayments():
    """Verify failed repayments count aggregates overdue installments, cancellations, and failed txns."""
    analyzer = ExposureAnalyzer()

    insts = [
        # Overdue installment
        Installment(
            installment_id="INST_F_1",
            customer_id="C1",
            amount=Decimal("60.00"),
            due_date=REF_TIME - timedelta(days=10),
            payment_status=PaymentStatus.OVERDUE,
        ),
        # Cancelled repayment plan
        Installment(
            installment_id="INST_F_2",
            customer_id="C1",
            amount=Decimal("80.00"),
            due_date=REF_TIME - timedelta(days=20),
            payment_status=PaymentStatus.CANCELLED,
        ),
    ]

    txns = [
        # Failed transaction attempt
        Transaction(
            transaction_id="TXN_FAIL_1",
            customer_id="C1",
            amount=Decimal("60.00"),
            merchant="Store A",
            timestamp=REF_TIME - timedelta(days=5),
            transaction_status=TransactionStatus.FAILED,
        ),
        # Declined transaction attempt
        Transaction(
            transaction_id="TXN_FAIL_2",
            customer_id="C1",
            amount=Decimal("80.00"),
            merchant="Store B",
            timestamp=REF_TIME - timedelta(days=3),
            transaction_status=TransactionStatus.DECLINED,
        ),
    ]

    result = analyzer.analyze(insts, transactions=txns, evaluation_time=REF_TIME)

    # 1 overdue + 1 cancelled + 2 failed/declined = 4 failed repayments
    assert result.failed_repayments_count == 4
    # Cancelled installment is not active debt
    assert result.total_outstanding_amount == Decimal("60.00")
    assert result.active_installment_count == 1


def test_exposure_boundary_dates():
    """Verify boundary conditions for due date calculations."""
    analyzer = ExposureAnalyzer()

    # Exact boundary 1: due right now at ref_time (included in next 7d, not overdue)
    inst_now = Installment(
        installment_id="INST_B_NOW",
        customer_id="C1",
        amount=Decimal("50.00"),
        due_date=REF_TIME,
        payment_status=PaymentStatus.PENDING,
    )
    # Exact boundary 2: due exactly at 7d mark (included in next 7d)
    inst_7d_edge = Installment(
        installment_id="INST_B_7D",
        customer_id="C1",
        amount=Decimal("70.00"),
        due_date=REF_TIME + timedelta(days=7),
        payment_status=PaymentStatus.PENDING,
    )
    # Just outside 7d mark (7 days + 1 second)
    inst_7d_out = Installment(
        installment_id="INST_B_7D_OUT",
        customer_id="C1",
        amount=Decimal("90.00"),
        due_date=REF_TIME + timedelta(days=7, seconds=1),
        payment_status=PaymentStatus.PENDING,
    )
    # Just past due (1 second ago)
    inst_overdue_edge = Installment(
        installment_id="INST_B_OD",
        customer_id="C1",
        amount=Decimal("40.00"),
        due_date=REF_TIME - timedelta(seconds=1),
        payment_status=PaymentStatus.PENDING,
    )

    result = analyzer.analyze([inst_now, inst_7d_edge, inst_7d_out, inst_overdue_edge], evaluation_time=REF_TIME)

    # 50 (now) + 70 (7d edge) = 120.00
    assert result.due_next_7d_amount == Decimal("120.00")
    # 40 (overdue edge)
    assert result.total_overdue_amount == Decimal("40.00")
    assert result.overdue_installment_count == 1
    # Total outstanding = 50 + 70 + 90 + 40 = 250.00
    assert result.total_outstanding_amount == Decimal("250.00")


def test_exposure_deduplication():
    """Verify duplicate installment records are counted only once."""
    analyzer = ExposureAnalyzer()
    inst = Installment(
        installment_id="INST_DUP",
        customer_id="C1",
        amount=Decimal("120.00"),
        due_date=REF_TIME + timedelta(days=2),
        payment_status=PaymentStatus.PENDING,
    )

    result = analyzer.analyze([inst, inst, inst], evaluation_time=REF_TIME)
    assert result.total_outstanding_amount == Decimal("120.00")
    assert result.due_next_7d_amount == Decimal("120.00")
    assert result.active_installment_count == 1


def test_exposure_convenience_function():
    """Verify top-level analyze_exposure function works equivalently."""
    inst = Installment(
        installment_id="INST_CONV_1",
        customer_id="C1",
        amount=Decimal("80.00"),
        due_date=REF_TIME + timedelta(days=4),
        payment_status=PaymentStatus.PENDING,
    )
    res = analyze_exposure([inst], evaluation_time=REF_TIME)
    assert isinstance(res, ExposureAnalysisResult)
    assert res.total_outstanding_amount == Decimal("80.00")
    assert res.due_next_7d_amount == Decimal("80.00")
