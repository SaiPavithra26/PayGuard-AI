"""Unit and integration tests for PayLater Shield risk scoring services."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest
from sqlalchemy.orm import Session

from backend.app.models.customer import Customer
from backend.app.models.enums import (
    IdentityStatus,
    PaymentStatus,
    RecommendedAction,
    RiskLevel,
    TransactionStatus,
)
from backend.app.models.installment import Installment
from backend.app.models.risk_assessment import RiskAssessment
from backend.app.models.transaction import Transaction
from backend.app.services.exposure import ExposureAnalyzer
from backend.app.services.risk_engine import (
    RiskAssessmentResult,
    RiskEngine,
    RiskEngineConfig,
)
from backend.app.services.velocity import VelocityAnalyzer


# ---------------------------------------------------------------------------
# 1. VelocityAnalyzer Unit Tests
# ---------------------------------------------------------------------------

def test_velocity_analyzer_empty():
    """Verify velocity analyzer returns 0 points for empty transactions."""
    analyzer = VelocityAnalyzer(window_hours=24, count_threshold=3, weight=25)
    result = analyzer.analyze([], evaluation_time=datetime(2026, 11, 12, 0, 0, tzinfo=timezone.utc))

    assert result.transaction_count == 0
    assert result.total_amount == Decimal("0.00")
    assert result.signal_score == 0
    assert not result.is_velocity_elevated
    assert result.reason is None


def test_velocity_analyzer_outside_window():
    """Verify transactions outside the rolling window are excluded from velocity."""
    ref_time = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)
    analyzer = VelocityAnalyzer(window_hours=24, count_threshold=3, weight=25)

    # 4 transactions that occurred 30 to 40 hours ago (outside 24h window)
    txns = [
        Transaction(
            transaction_id=f"TXN_OLD_{i}",
            customer_id="CUST_1",
            amount=Decimal("50.00"),
            merchant="Store A",
            timestamp=ref_time - timedelta(hours=30 + i),
            transaction_status=TransactionStatus.COMPLETED,
        )
        for i in range(4)
    ]

    result = analyzer.analyze(txns, evaluation_time=ref_time)
    assert result.transaction_count == 0
    assert result.signal_score == 0
    assert not result.is_velocity_elevated


def test_velocity_analyzer_elevated():
    """Verify velocity analyzer triggers when transaction count meets or exceeds threshold."""
    ref_time = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)
    analyzer = VelocityAnalyzer(window_hours=24, count_threshold=3, weight=25)

    # 3 transactions within the last 5 hours
    txns = [
        Transaction(
            transaction_id=f"TXN_RECENT_{i}",
            customer_id="CUST_1",
            amount=Decimal("40.00"),
            merchant="Store B",
            timestamp=ref_time - timedelta(hours=i + 1),
            transaction_status=TransactionStatus.APPROVED,
        )
        for i in range(3)
    ]

    result = analyzer.analyze(txns, evaluation_time=ref_time)
    assert result.transaction_count == 3
    assert result.total_amount == Decimal("120.00")
    assert result.signal_score == 25
    assert result.is_velocity_elevated
    assert "High purchase velocity detected" in result.reason


def test_velocity_analyzer_invalid_negative_amount():
    """Verify velocity analyzer rejects invalid negative monetary values."""
    ref_time = datetime.now(timezone.utc)
    analyzer = VelocityAnalyzer()
    invalid_txn = Transaction(
        transaction_id="TXN_INVALID",
        customer_id="CUST_1",
        amount=Decimal("-15.00"),
        merchant="Store Bad",
        timestamp=ref_time,
        transaction_status=TransactionStatus.COMPLETED,
    )
    with pytest.raises(ValueError, match="Invalid transaction amount"):
        analyzer.analyze([invalid_txn], evaluation_time=ref_time)


# ---------------------------------------------------------------------------
# 2. ExposureAnalyzer Unit Tests
# ---------------------------------------------------------------------------

def test_exposure_analyzer_empty():
    """Verify exposure analyzer returns 0 points for zero installments."""
    analyzer = ExposureAnalyzer(threshold=Decimal("300.00"), weight=20)
    result = analyzer.analyze([])

    assert result.total_unpaid_amount == Decimal("0.00")
    assert result.active_installment_count == 0
    assert result.signal_score == 0
    assert not result.is_exposure_elevated


def test_exposure_analyzer_paid_only():
    """Verify exposure analyzer ignores fully paid installments."""
    analyzer = ExposureAnalyzer(threshold=Decimal("300.00"), weight=20)
    insts = [
        Installment(
            installment_id="INST_PAID_1",
            customer_id="CUST_1",
            amount=Decimal("450.00"),
            due_date=datetime.now(timezone.utc) - timedelta(days=5),
            payment_status=PaymentStatus.PAID,
            paid_at=datetime.now(timezone.utc) - timedelta(days=6),
        )
    ]
    result = analyzer.analyze(insts)
    assert result.total_unpaid_amount == Decimal("0.00")
    assert result.signal_score == 0
    assert not result.is_exposure_elevated


def test_exposure_analyzer_elevated():
    """Verify exposure analyzer triggers when cumulative unpaid amount exceeds threshold."""
    analyzer = ExposureAnalyzer(threshold=Decimal("300.00"), weight=20)
    insts = [
        Installment(
            installment_id="INST_PEND_1",
            customer_id="CUST_1",
            amount=Decimal("175.00"),
            due_date=datetime.now(timezone.utc) + timedelta(days=10),
            payment_status=PaymentStatus.PENDING,
        ),
        Installment(
            installment_id="INST_PEND_2",
            customer_id="CUST_1",
            amount=Decimal("150.00"),
            due_date=datetime.now(timezone.utc) + timedelta(days=20),
            payment_status=PaymentStatus.PENDING,
        ),
    ]
    result = analyzer.analyze(insts)
    assert result.total_unpaid_amount == Decimal("325.00")
    assert result.active_installment_count == 2
    assert result.signal_score == 20
    assert result.is_exposure_elevated
    assert "High cumulative outstanding credit exposure" in result.reason


def test_exposure_analyzer_deduplication():
    """Verify exposure analyzer deduplicates identical installment IDs to avoid double counting."""
    analyzer = ExposureAnalyzer(threshold=Decimal("300.00"), weight=20)
    duplicate_inst = Installment(
        installment_id="INST_DUP_1",
        customer_id="CUST_1",
        amount=Decimal("200.00"),
        due_date=datetime.now(timezone.utc) + timedelta(days=10),
        payment_status=PaymentStatus.PENDING,
    )
    # Pass same installment object twice
    result = analyzer.analyze([duplicate_inst, duplicate_inst])
    assert result.total_unpaid_amount == Decimal("200.00")
    assert result.active_installment_count == 1


# ---------------------------------------------------------------------------
# 3. RiskEngine Multi-Factor and Signal Tests
# ---------------------------------------------------------------------------

def test_clean_customer_evaluation():
    """Verify a clean verified customer receives 0 points, LOW risk, and CONTINUE."""
    engine = RiskEngine()
    cust = Customer(
        customer_id="CUST_CLEAN",
        account_created_at=datetime.now(timezone.utc) - timedelta(days=180),
        identity_status=IdentityStatus.VERIFIED,
        device_risk_signal="TRUSTED_DEVICE",
    )
    # Single past transaction and single paid installment
    txn = Transaction(
        transaction_id="TXN_1",
        customer_id=cust.customer_id,
        amount=Decimal("80.00"),
        merchant="Merchant Alpha",
        timestamp=datetime.now(timezone.utc) - timedelta(days=30),
        transaction_status=TransactionStatus.COMPLETED,
    )
    inst = Installment(
        installment_id="INST_1",
        customer_id=cust.customer_id,
        amount=Decimal("40.00"),
        due_date=datetime.now(timezone.utc) - timedelta(days=15),
        payment_status=PaymentStatus.PAID,
        paid_at=datetime.now(timezone.utc) - timedelta(days=16),
    )

    result = engine.evaluate(cust, transactions=[txn], installments=[inst])
    assert result.risk_score == 0
    assert result.risk_level == RiskLevel.LOW
    assert result.recommended_action == RecommendedAction.CONTINUE
    assert "Clean customer profile" in result.reasons[0]


def test_single_risk_signal_velocity():
    """Verify velocity trigger alone scores 25 points -> LOW risk (0-29 range)."""
    engine = RiskEngine()
    cust = Customer(
        customer_id="CUST_VEL",
        account_created_at=datetime.now(timezone.utc) - timedelta(days=60),
        identity_status=IdentityStatus.VERIFIED,
        device_risk_signal="TRUSTED_DEVICE",
    )
    now = datetime.now(timezone.utc)
    txns = [
        Transaction(
            transaction_id=f"TXN_V_{i}",
            customer_id=cust.customer_id,
            amount=Decimal("30.00"),
            merchant="Store Fast",
            timestamp=now - timedelta(hours=i + 1),
            transaction_status=TransactionStatus.APPROVED,
        )
        for i in range(3)
    ]
    result = engine.evaluate(cust, transactions=txns, installments=[], evaluation_time=now)
    assert result.risk_score == 25
    assert result.risk_level == RiskLevel.LOW
    assert result.recommended_action == RecommendedAction.CONTINUE
    assert result.signals["velocity"].triggered


def test_combined_signals_medium_tier():
    """Verify Velocity (25) + High Exposure (20) = 45 points -> MEDIUM, ADDITIONAL_VERIFICATION."""
    engine = RiskEngine()
    cust = Customer(
        customer_id="CUST_MED",
        account_created_at=datetime.now(timezone.utc) - timedelta(days=90),
        identity_status=IdentityStatus.VERIFIED,
        device_risk_signal="TRUSTED_DEVICE",
    )
    now = datetime.now(timezone.utc)
    txns = [
        Transaction(
            transaction_id=f"TXN_M_{i}",
            customer_id=cust.customer_id,
            amount=Decimal("120.00"),
            merchant="Merchant Gamma",
            timestamp=now - timedelta(hours=i + 1),
            transaction_status=TransactionStatus.APPROVED,
        )
        for i in range(3)
    ]
    insts = [
        Installment(
            installment_id="INST_M_1",
            customer_id=cust.customer_id,
            amount=Decimal("350.00"),
            due_date=now + timedelta(days=14),
            payment_status=PaymentStatus.PENDING,
        )
    ]

    result = engine.evaluate(cust, transactions=txns, installments=insts, evaluation_time=now)
    assert result.risk_score == 45
    assert result.risk_level == RiskLevel.MEDIUM
    assert result.recommended_action == RecommendedAction.ADDITIONAL_VERIFICATION
    assert len(result.reasons) == 2


def test_combined_signals_high_tier():
    """Verify Velocity (25) + Exposure (20) + Repayment (20) = 65 points -> HIGH, MANUAL_REVIEW."""
    engine = RiskEngine()
    cust = Customer(
        customer_id="CUST_HIGH",
        account_created_at=datetime.now(timezone.utc) - timedelta(days=90),
        identity_status=IdentityStatus.VERIFIED,
        device_risk_signal="TRUSTED_DEVICE",
    )
    now = datetime.now(timezone.utc)
    # Velocity: 3 txns in window
    txns = [
        Transaction(
            transaction_id=f"TXN_H_{i}",
            customer_id=cust.customer_id,
            amount=Decimal("100.00"),
            merchant="Merchant Delta",
            timestamp=now - timedelta(hours=i + 1),
            transaction_status=TransactionStatus.APPROVED,
        )
        for i in range(3)
    ]
    # Exposure + Overdue repayment
    insts = [
        Installment(
            installment_id="INST_H_1",
            customer_id=cust.customer_id,
            amount=Decimal("200.00"),
            due_date=now + timedelta(days=14),
            payment_status=PaymentStatus.PENDING,
        ),
        Installment(
            installment_id="INST_H_2",
            customer_id=cust.customer_id,
            amount=Decimal("150.00"),
            due_date=now - timedelta(days=5),
            payment_status=PaymentStatus.OVERDUE,
        ),
    ]

    result = engine.evaluate(cust, transactions=txns, installments=insts, evaluation_time=now)
    # Velocity (25) + Exposure (20) + Repayment Overdue (20) = 65
    assert result.risk_score == 65
    assert result.risk_level == RiskLevel.HIGH
    assert result.recommended_action == RecommendedAction.MANUAL_REVIEW
    assert len(result.reasons) == 3


def test_all_five_signals_max_score():
    """Verify customer with all 5 signals triggered receives max score 100."""
    engine = RiskEngine()
    cust = Customer(
        customer_id="CUST_MAX",
        account_created_at=datetime.now(timezone.utc) - timedelta(days=30),
        identity_status=IdentityStatus.PENDING,  # Identity: 20
        device_risk_signal="SUSPICIOUS_EMULATOR",  # Device: 15
    )
    now = datetime.now(timezone.utc)
    # Velocity: 25
    txns = [
        Transaction(
            transaction_id=f"TXN_MAX_{i}",
            customer_id=cust.customer_id,
            amount=Decimal("120.00"),
            merchant="Merchant Omega",
            timestamp=now - timedelta(hours=i + 1),
            transaction_status=TransactionStatus.APPROVED,
        )
        for i in range(3)
    ]
    # Exposure (20) + Repayment (20)
    insts = [
        Installment(
            installment_id="INST_MAX_1",
            customer_id=cust.customer_id,
            amount=Decimal("350.00"),
            due_date=now - timedelta(days=4),
            payment_status=PaymentStatus.OVERDUE,
        )
    ]

    result = engine.evaluate(cust, transactions=txns, installments=insts, evaluation_time=now)
    assert result.risk_score == 100
    assert result.risk_level == RiskLevel.HIGH
    assert result.recommended_action == RecommendedAction.MANUAL_REVIEW
    assert len(result.reasons) == 5


# ---------------------------------------------------------------------------
# 4. Edge Cases Tests
# ---------------------------------------------------------------------------

def test_new_customer_with_no_history_not_penalized():
    """Verify new customer with 0 transactions and 0 installments is NOT penalized."""
    engine = RiskEngine()
    cust = Customer(
        customer_id="CUST_NEW_001",
        account_created_at=datetime.now(timezone.utc) - timedelta(days=2),
        identity_status=IdentityStatus.VERIFIED,
        device_risk_signal="TRUSTED_DEVICE",
    )

    result = engine.evaluate(cust, transactions=[], installments=[])
    assert result.risk_score == 0
    assert result.risk_level == RiskLevel.LOW
    assert result.recommended_action == RecommendedAction.CONTINUE


def test_missing_optional_device_signal_not_penalized():
    """Verify customer with device_risk_signal=None receives 0 penalty for device."""
    engine = RiskEngine()
    cust = Customer(
        customer_id="CUST_NO_DEV",
        account_created_at=datetime.now(timezone.utc) - timedelta(days=45),
        identity_status=IdentityStatus.VERIFIED,
        device_risk_signal=None,  # Missing optional telemetry
    )

    result = engine.evaluate(cust, transactions=[], installments=[])
    assert result.signals["device"].score == 0
    assert not result.signals["device"].triggered


def test_normal_high_value_purchase_not_suspicious():
    """Verify a high-value purchase without velocity or exposure does NOT trigger risk."""
    engine = RiskEngine()
    cust = Customer(
        customer_id="CUST_HIGH_VAL",
        account_created_at=datetime.now(timezone.utc) - timedelta(days=120),
        identity_status=IdentityStatus.VERIFIED,
        device_risk_signal="TRUSTED_DEVICE",
    )
    now = datetime.now(timezone.utc)
    # A single $950.00 transaction (high value, but only 1 purchase)
    txns = [
        Transaction(
            transaction_id="TXN_HV_1",
            customer_id=cust.customer_id,
            amount=Decimal("950.00"),
            merchant="Luxury Tech Store",
            timestamp=now - timedelta(hours=2),
            transaction_status=TransactionStatus.APPROVED,
        )
    ]
    # No unpaid installments
    result = engine.evaluate(cust, transactions=txns, installments=[], evaluation_time=now)
    assert result.risk_score == 0
    assert result.risk_level == RiskLevel.LOW
    assert result.recommended_action == RecommendedAction.CONTINUE


def test_deterministic_scoring_for_identical_inputs():
    """Verify risk evaluation is 100% deterministic given identical inputs."""
    engine = RiskEngine()
    cust = Customer(
        customer_id="CUST_DET",
        account_created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        identity_status=IdentityStatus.PENDING,
        device_risk_signal="TOR_EXIT_NODE",
    )
    eval_time = datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc)

    res1 = engine.evaluate(cust, transactions=[], installments=[], evaluation_time=eval_time)
    res2 = engine.evaluate(cust, transactions=[], installments=[], evaluation_time=eval_time)

    assert res1.risk_score == res2.risk_score == 35
    assert res1.risk_level == res2.risk_level == RiskLevel.MEDIUM
    assert res1.recommended_action == res2.recommended_action == RecommendedAction.ADDITIONAL_VERIFICATION
    assert res1.to_audit_dict() == res2.to_audit_dict()


# ---------------------------------------------------------------------------
# 5. Database Persistence Integration Test
# ---------------------------------------------------------------------------

def test_evaluate_and_persist_to_database(db_session: Session, sample_customer: Customer):
    """Verify evaluate_and_persist stores a complete RiskAssessment record in the database."""
    engine = RiskEngine()
    assessment = engine.evaluate_and_persist(
        session=db_session,
        customer_id=sample_customer.customer_id,
        assessment_id="RSK_INTEG_001",
    )

    retrieved = db_session.get(RiskAssessment, "RSK_INTEG_001")
    assert retrieved is not None
    assert retrieved.customer_id == sample_customer.customer_id
    assert retrieved.risk_score == 0
    assert retrieved.risk_level == RiskLevel.LOW
    assert retrieved.recommended_action == RecommendedAction.CONTINUE
    assert "signals" in retrieved.risk_reasons
    assert retrieved.created_at.tzinfo == timezone.utc

