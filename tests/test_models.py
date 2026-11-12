"""Comprehensive unit tests for PayLater Shield SQLAlchemy models and constraints."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
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


def test_tables_created(test_engine):
    """Verify that all four required database tables exist in metadata."""
    inspector = inspect(test_engine)
    table_names = inspector.get_table_names()

    expected_tables = {"customers", "transactions", "installments", "risk_assessments"}
    for table in expected_tables:
        assert table in table_names, f"Expected table '{table}' not found in database"


def test_customer_creation_and_timezone(db_session: Session):
    """Verify Customer model instantiation, UTC timezone handling, and defaults."""
    now_utc = datetime.now(timezone.utc)
    cust = Customer(
        customer_id="CUST_TZ_001",
        account_created_at=now_utc,
        identity_status=IdentityStatus.PENDING,
        device_risk_signal="TRUSTED_DEVICE",
    )
    db_session.add(cust)
    db_session.commit()

    retrieved = db_session.get(Customer, "CUST_TZ_001")
    assert retrieved is not None
    assert retrieved.customer_id == "CUST_TZ_001"
    assert retrieved.identity_status == IdentityStatus.PENDING
    assert retrieved.account_created_at.tzinfo is not None
    assert retrieved.account_created_at.tzinfo == timezone.utc
    assert repr(retrieved).startswith("<Customer")


def test_transaction_valid_with_decimal_precision(db_session: Session, sample_customer: Customer):
    """Verify Transaction creation, foreign key relationship, and exact Decimal precision."""
    now_utc = datetime.now(timezone.utc)
    exact_amount = Decimal("149.99")

    txn = Transaction(
        transaction_id="TXN_1001",
        customer_id=sample_customer.customer_id,
        amount=exact_amount,
        merchant="Target Electronics",
        timestamp=now_utc,
        transaction_status=TransactionStatus.APPROVED,
    )
    db_session.add(txn)
    db_session.commit()

    retrieved = db_session.get(Transaction, "TXN_1001")
    assert retrieved is not None
    assert retrieved.amount == Decimal("149.99")
    assert isinstance(retrieved.amount, Decimal)
    assert retrieved.merchant == "Target Electronics"
    assert retrieved.customer.customer_id == sample_customer.customer_id
    assert txn in sample_customer.transactions
    assert retrieved.timestamp.tzinfo == timezone.utc


def test_installment_creation_and_relationship(db_session: Session, sample_customer: Customer):
    """Verify Installment model creation, optional transaction link, and status."""
    now_utc = datetime.now(timezone.utc)
    txn = Transaction(
        transaction_id="TXN_BNPL_001",
        customer_id=sample_customer.customer_id,
        amount=Decimal("100.00"),
        merchant="BestBuy",
        timestamp=now_utc,
        transaction_status=TransactionStatus.APPROVED,
    )
    db_session.add(txn)
    db_session.flush()

    due1 = now_utc + timedelta(days=14)
    due2 = now_utc + timedelta(days=28)

    inst1 = Installment(
        installment_id="INST_001_1",
        customer_id=sample_customer.customer_id,
        transaction_id=txn.transaction_id,
        amount=Decimal("50.00"),
        due_date=due1,
        payment_status=PaymentStatus.PAID,
        paid_at=now_utc,
    )
    inst2 = Installment(
        installment_id="INST_001_2",
        customer_id=sample_customer.customer_id,
        transaction_id=txn.transaction_id,
        amount=Decimal("50.00"),
        due_date=due2,
        payment_status=PaymentStatus.PENDING,
        paid_at=None,
    )
    db_session.add_all([inst1, inst2])
    db_session.commit()

    retrieved_txn = db_session.get(Transaction, "TXN_BNPL_001")
    assert retrieved_txn is not None
    assert len(retrieved_txn.installments) == 2
    assert retrieved_txn.installments[0].installment_id in ("INST_001_1", "INST_001_2")
    assert retrieved_txn.installments[0].customer.customer_id == sample_customer.customer_id


def test_risk_assessment_with_structured_json(db_session: Session, sample_customer: Customer):
    """Verify RiskAssessment entity with structured JSON risk reasons and enum actions."""
    now_utc = datetime.now(timezone.utc)
    reasons = {
        "velocity_flag": True,
        "recent_txns_count": 5,
        "unpaid_exposure": 350.00,
        "risk_factors": ["RAPID_BURST_ATTEMPTS", "HIGH_CREDIT_UTILIZATION"],
    }

    assessment = RiskAssessment(
        assessment_id="RSK_90001",
        customer_id=sample_customer.customer_id,
        risk_score=78,
        risk_level=RiskLevel.HIGH,
        risk_reasons=reasons,
        recommended_action=RecommendedAction.MANUAL_REVIEW,
        created_at=now_utc,
    )
    db_session.add(assessment)
    db_session.commit()

    retrieved = db_session.get(RiskAssessment, "RSK_90001")
    assert retrieved is not None
    assert retrieved.risk_score == 78
    assert retrieved.risk_level == RiskLevel.HIGH
    assert retrieved.recommended_action == RecommendedAction.MANUAL_REVIEW
    assert retrieved.risk_reasons["velocity_flag"] is True
    assert "RAPID_BURST_ATTEMPTS" in retrieved.risk_reasons["risk_factors"]
    assert retrieved.created_at.tzinfo == timezone.utc
    assert assessment in sample_customer.risk_assessments


def test_foreign_key_violation_transaction(db_session: Session):
    """Verify that inserting a transaction with an invalid customer_id fails."""
    txn = Transaction(
        transaction_id="TXN_INVALID_FK",
        customer_id="NON_EXISTENT_CUSTOMER",
        amount=Decimal("50.00"),
        merchant="Acme Corp",
        timestamp=datetime.now(timezone.utc),
        transaction_status=TransactionStatus.PENDING,
    )
    db_session.add(txn)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_foreign_key_violation_installment(db_session: Session):
    """Verify that inserting an installment with an invalid customer_id fails."""
    inst = Installment(
        installment_id="INST_INVALID_FK",
        customer_id="NON_EXISTENT_CUSTOMER",
        amount=Decimal("25.00"),
        due_date=datetime.now(timezone.utc),
        payment_status=PaymentStatus.PENDING,
    )
    db_session.add(inst)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_foreign_key_violation_risk_assessment(db_session: Session):
    """Verify that inserting a risk assessment with an invalid customer_id fails."""
    assessment = RiskAssessment(
        assessment_id="RSK_INVALID_FK",
        customer_id="NON_EXISTENT_CUSTOMER",
        risk_score=10,
        risk_level=RiskLevel.LOW,
        risk_reasons={"note": "invalid fk test"},
        recommended_action=RecommendedAction.CONTINUE,
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(assessment)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_cascade_delete_customer(db_session: Session):
    """Verify that deleting a customer cascades and removes transactions, installments, and risk assessments."""
    cust = Customer(
        customer_id="CUST_CASCADE_001",
        account_created_at=datetime.now(timezone.utc),
        identity_status=IdentityStatus.VERIFIED,
    )
    db_session.add(cust)
    db_session.flush()

    txn = Transaction(
        transaction_id="TXN_CASCADE_001",
        customer_id=cust.customer_id,
        amount=Decimal("75.00"),
        merchant="Merchant A",
        timestamp=datetime.now(timezone.utc),
        transaction_status=TransactionStatus.APPROVED,
    )
    inst = Installment(
        installment_id="INST_CASCADE_001",
        customer_id=cust.customer_id,
        transaction_id=txn.transaction_id,
        amount=Decimal("75.00"),
        due_date=datetime.now(timezone.utc) + timedelta(days=14),
        payment_status=PaymentStatus.PENDING,
    )
    assessment = RiskAssessment(
        assessment_id="RSK_CASCADE_001",
        customer_id=cust.customer_id,
        risk_score=20,
        risk_level=RiskLevel.LOW,
        risk_reasons={"initial": True},
        recommended_action=RecommendedAction.CONTINUE,
        created_at=datetime.now(timezone.utc),
    )
    db_session.add_all([txn, inst, assessment])
    db_session.commit()

    # Delete customer
    retrieved_cust = db_session.get(Customer, "CUST_CASCADE_001")
    assert retrieved_cust is not None
    db_session.delete(retrieved_cust)
    db_session.commit()

    # Verify children were deleted
    assert db_session.get(Customer, "CUST_CASCADE_001") is None
    assert db_session.get(Transaction, "TXN_CASCADE_001") is None
    assert db_session.get(Installment, "INST_CASCADE_001") is None
    assert db_session.get(RiskAssessment, "RSK_CASCADE_001") is None


def test_transaction_negative_amount_constraint(db_session: Session, sample_customer: Customer):
    """Verify CheckConstraint rejects zero or negative transaction amount."""
    txn_zero = Transaction(
        transaction_id="TXN_ZERO",
        customer_id=sample_customer.customer_id,
        amount=Decimal("0.00"),
        merchant="Zero Store",
        timestamp=datetime.now(timezone.utc),
        transaction_status=TransactionStatus.PENDING,
    )
    db_session.add(txn_zero)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()

    txn_negative = Transaction(
        transaction_id="TXN_NEG",
        customer_id=sample_customer.customer_id,
        amount=Decimal("-45.50"),
        merchant="Negative Store",
        timestamp=datetime.now(timezone.utc),
        transaction_status=TransactionStatus.PENDING,
    )
    db_session.add(txn_negative)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_installment_negative_amount_constraint(db_session: Session, sample_customer: Customer):
    """Verify CheckConstraint rejects zero or negative installment amount."""
    inst_zero = Installment(
        installment_id="INST_ZERO",
        customer_id=sample_customer.customer_id,
        amount=Decimal("0.00"),
        due_date=datetime.now(timezone.utc),
        payment_status=PaymentStatus.PENDING,
    )
    db_session.add(inst_zero)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_risk_score_range_constraints(db_session: Session, sample_customer: Customer):
    """Verify CheckConstraint rejects risk scores < 0 or > 100."""
    # Negative score
    rsk_under = RiskAssessment(
        assessment_id="RSK_UNDER",
        customer_id=sample_customer.customer_id,
        risk_score=-1,
        risk_level=RiskLevel.LOW,
        risk_reasons={},
        recommended_action=RecommendedAction.CONTINUE,
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(rsk_under)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()

    # Score exceeding 100
    rsk_over = RiskAssessment(
        assessment_id="RSK_OVER",
        customer_id=sample_customer.customer_id,
        risk_score=101,
        risk_level=RiskLevel.HIGH,
        risk_reasons={},
        recommended_action=RecommendedAction.MANUAL_REVIEW,
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(rsk_over)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_installment_without_transaction_id(db_session: Session, sample_customer: Customer):
    """Verify installment can exist without an associated transaction."""
    due = datetime.now(timezone.utc) + timedelta(days=7)
    inst = Installment(
        installment_id="INST_NO_TXN_001",
        customer_id=sample_customer.customer_id,
        transaction_id=None,
        amount=Decimal("35.50"),
        due_date=due,
        payment_status=PaymentStatus.PENDING,
    )
    db_session.add(inst)
    db_session.commit()

    retrieved = db_session.get(Installment, "INST_NO_TXN_001")
    assert retrieved is not None
    assert retrieved.transaction_id is None
    assert retrieved.transaction is None
    assert retrieved.customer.customer_id == sample_customer.customer_id


def test_timezone_conversion_from_naive_and_offsets(db_session: Session, sample_customer: Customer):
    """Verify UTCDateTime type decorator normalizes naive and offset-aware datetimes to UTC."""
    # Test naive datetime
    naive_dt = datetime(2026, 6, 1, 12, 0, 0)  # naive
    txn1 = Transaction(
        transaction_id="TXN_NAIVE_DT",
        customer_id=sample_customer.customer_id,
        amount=Decimal("10.00"),
        merchant="Store Naive",
        timestamp=naive_dt,
        transaction_status=TransactionStatus.COMPLETED,
    )
    db_session.add(txn1)
    db_session.commit()

    retrieved1 = db_session.get(Transaction, "TXN_NAIVE_DT")
    assert retrieved1 is not None
    assert retrieved1.timestamp.tzinfo == timezone.utc
    assert retrieved1.timestamp.year == 2026
    assert retrieved1.timestamp.month == 6

    # Test non-UTC timezone offset (e.g., UTC+5:30)
    ist = timezone(timedelta(hours=5, minutes=30))
    ist_dt = datetime(2026, 6, 1, 15, 30, 0, tzinfo=ist)
    txn2 = Transaction(
        transaction_id="TXN_IST_DT",
        customer_id=sample_customer.customer_id,
        amount=Decimal("20.00"),
        merchant="Store IST",
        timestamp=ist_dt,
        transaction_status=TransactionStatus.COMPLETED,
    )
    db_session.add(txn2)
    db_session.commit()

    retrieved2 = db_session.get(Transaction, "TXN_IST_DT")
    assert retrieved2 is not None
    assert retrieved2.timestamp.tzinfo == timezone.utc
    # 15:30 IST is 10:00 UTC
    assert retrieved2.timestamp.hour == 10
    assert retrieved2.timestamp.minute == 0


def test_indexes_created(test_engine):
    """Verify that expected performance indexes are created on tables."""
    inspector = inspect(test_engine)

    txn_indexes = {idx["name"] for idx in inspector.get_indexes("transactions")}
    assert "ix_transactions_customer_timestamp" in txn_indexes
    assert "ix_transactions_customer_id" in txn_indexes

    inst_indexes = {idx["name"] for idx in inspector.get_indexes("installments")}
    assert "ix_installments_customer_status_due" in inst_indexes

    rsk_indexes = {idx["name"] for idx in inspector.get_indexes("risk_assessments")}
    assert "ix_risk_assessments_customer_id" in rsk_indexes


def test_decimal_monetary_exactness(db_session: Session, sample_customer: Customer):
    """Verify exact decimal arithmetic on monetary values without floating point drift."""
    # Classical float drift: 0.10 + 0.20 == 0.30000000000000004
    # Using Decimal(10, 2): 0.10 + 0.20 == 0.30 exactly
    inst1 = Installment(
        installment_id="INST_DEC_1",
        customer_id=sample_customer.customer_id,
        amount=Decimal("0.10"),
        due_date=datetime.now(timezone.utc),
        payment_status=PaymentStatus.PENDING,
    )
    inst2 = Installment(
        installment_id="INST_DEC_2",
        customer_id=sample_customer.customer_id,
        amount=Decimal("0.20"),
        due_date=datetime.now(timezone.utc),
        payment_status=PaymentStatus.PENDING,
    )
    db_session.add_all([inst1, inst2])
    db_session.commit()

    total = inst1.amount + inst2.amount
    assert total == Decimal("0.30")
    assert str(total) == "0.30"
