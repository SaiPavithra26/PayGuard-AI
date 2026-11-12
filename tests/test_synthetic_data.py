"""Comprehensive test suite for synthetic data generation in PayLater Shield."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.customer import Customer
from backend.app.models.enums import IdentityStatus, PaymentStatus, TransactionStatus
from backend.app.models.installment import Installment
from backend.app.models.transaction import Transaction
from backend.app.services.synthetic_data import (
    SCENARIO_HIGH_EXPOSURE,
    SCENARIO_HIGH_VELOCITY,
    SCENARIO_MULTI_RISK,
    SCENARIO_NEW_NORMAL,
    SCENARIO_NORMAL,
    SCENARIO_OVERDUE,
    SCENARIO_PENDING_IDENTITY,
    SyntheticDataGenerator,
)


def test_generation_target_counts():
    """Verify generator produces target counts matching requirements (100 custs, 300-500 txns, 100-200 insts)."""
    generator = SyntheticDataGenerator(seed=42, num_customers=100)
    customers, transactions, installments = generator.generate()

    assert len(customers) == 100
    assert 300 <= len(transactions) <= 500, f"Expected 300-500 transactions, got {len(transactions)}"
    assert 100 <= len(installments) <= 200, f"Expected 100-200 installments, got {len(installments)}"


def test_generation_reproducibility_with_same_seed():
    """Verify that using the same seed produces byte-for-byte identical datasets."""
    gen1 = SyntheticDataGenerator(seed=12345, num_customers=50)
    custs1, txns1, insts1 = gen1.generate()

    gen2 = SyntheticDataGenerator(seed=12345, num_customers=50)
    custs2, txns2, insts2 = gen2.generate()

    assert len(custs1) == len(custs2)
    assert len(txns1) == len(txns2)
    assert len(insts1) == len(insts2)

    for c1, c2 in zip(custs1, custs2):
        assert c1.customer_id == c2.customer_id
        assert c1.identity_status == c2.identity_status
        assert c1.account_created_at == c2.account_created_at

    for t1, t2 in zip(txns1, txns2):
        assert t1.transaction_id == t2.transaction_id
        assert t1.amount == t2.amount
        assert t1.timestamp == t2.timestamp
        assert t1.transaction_status == t2.transaction_status

    for i1, i2 in zip(insts1, insts2):
        assert i1.installment_id == i2.installment_id
        assert i1.amount == i2.amount
        assert i1.due_date == i2.due_date
        assert i1.payment_status == i2.payment_status
        assert i1.paid_at == i2.paid_at


def test_different_seeds_produce_different_data():
    """Verify that changing seeds creates different deterministic datasets."""
    gen1 = SyntheticDataGenerator(seed=42, num_customers=30)
    _, txns1, _ = gen1.generate()

    gen2 = SyntheticDataGenerator(seed=999, num_customers=30)
    _, txns2, _ = gen2.generate()

    # Compare first transaction amounts
    assert txns1[0].amount != txns2[0].amount or txns1[0].timestamp != txns2[0].timestamp


def test_valid_foreign_key_references():
    """Verify that all generated transactions and installments have valid foreign key targets."""
    generator = SyntheticDataGenerator(seed=42, num_customers=100)
    customers, transactions, installments = generator.generate()

    valid_customer_ids = {c.customer_id for c in customers}
    valid_transaction_ids = {t.transaction_id for t in transactions}

    for txn in transactions:
        assert txn.customer_id in valid_customer_ids, f"Invalid customer FK in transaction {txn.transaction_id}"

    for inst in installments:
        assert inst.customer_id in valid_customer_ids, f"Invalid customer FK in installment {inst.installment_id}"
        if inst.transaction_id is not None:
            assert inst.transaction_id in valid_transaction_ids, f"Invalid txn FK in installment {inst.installment_id}"


def test_payment_status_and_date_consistency():
    """Verify that installment dates and payment statuses are logically coherent."""
    ref_time = datetime(2026, 11, 12, 0, 0, 0, tzinfo=timezone.utc)
    generator = SyntheticDataGenerator(seed=42, num_customers=100, reference_time=ref_time)
    _, _, installments = generator.generate()

    for inst in installments:
        if inst.payment_status == PaymentStatus.PAID:
            assert inst.paid_at is not None, f"Paid installment {inst.installment_id} has paid_at=None"
            assert inst.paid_at <= ref_time, f"Paid timestamp {inst.paid_at} cannot be in the future"

        elif inst.payment_status == PaymentStatus.PENDING:
            assert inst.paid_at is None, f"Pending installment {inst.installment_id} cannot have paid_at set"
            assert inst.due_date >= ref_time, f"Pending installment {inst.installment_id} must have future due date"

        elif inst.payment_status == PaymentStatus.OVERDUE:
            assert inst.paid_at is None, f"Overdue installment {inst.installment_id} cannot have paid_at set"
            assert inst.due_date < ref_time, f"Overdue installment {inst.installment_id} must have past due date"

        elif inst.payment_status == PaymentStatus.CANCELLED:
            assert inst.paid_at is None, f"Cancelled installment {inst.installment_id} cannot have paid_at set"


def test_monetary_decimal_and_positive_constraints():
    """Verify monetary amounts are strictly positive Decimals."""
    generator = SyntheticDataGenerator(seed=42, num_customers=100)
    _, transactions, installments = generator.generate()

    for txn in transactions:
        assert isinstance(txn.amount, Decimal)
        assert txn.amount > 0, f"Transaction {txn.transaction_id} amount must be > 0"
        # Validate decimal places (2 decimal places)
        assert txn.amount.as_tuple().exponent == -2

    for inst in installments:
        assert isinstance(inst.amount, Decimal)
        assert inst.amount > 0, f"Installment {inst.installment_id} amount must be > 0"
        assert inst.amount.as_tuple().exponent == -2


def test_timezone_aware_timestamps():
    """Verify that all generated timestamps are strictly timezone-aware UTC."""
    generator = SyntheticDataGenerator(seed=42, num_customers=50)
    customers, transactions, installments = generator.generate()

    for cust in customers:
        assert cust.account_created_at.tzinfo == timezone.utc

    for txn in transactions:
        assert txn.timestamp.tzinfo == timezone.utc

    for inst in installments:
        assert inst.due_date.tzinfo == timezone.utc
        if inst.paid_at is not None:
            assert inst.paid_at.tzinfo == timezone.utc


def test_scenario_archetypes_represented():
    """Verify all requested scenario archetypes are present in the dataset."""
    ref_time = datetime(2026, 11, 12, 0, 0, 0, tzinfo=timezone.utc)
    generator = SyntheticDataGenerator(seed=42, num_customers=100, reference_time=ref_time)
    customers, transactions, installments = generator.generate()

    # 1. Pending identity verification present
    pending_id_custs = [c for c in customers if c.identity_status == IdentityStatus.PENDING]
    assert len(pending_id_custs) >= 8

    # 2. Overdue installments present
    overdue_insts = [i for i in installments if i.payment_status == PaymentStatus.OVERDUE]
    assert len(overdue_insts) >= 8

    # 3. Failed transactions present
    failed_txns = [t for t in transactions if t.transaction_status == TransactionStatus.FAILED]
    assert len(failed_txns) >= 4

    # 4. Multi-risk customers with suspicious emulator signal
    multi_risk_custs = [c for c in customers if c.device_risk_signal == "SUSPICIOUS_EMULATOR"]
    assert len(multi_risk_custs) >= 3

    # 5. Normal established customers with paid history
    paid_insts = [i for i in installments if i.payment_status == PaymentStatus.PAID]
    assert len(paid_insts) >= 30

    # 6. High velocity: find a customer with >= 5 transactions within 48h
    customer_txns_map = {}
    for t in transactions:
        customer_txns_map.setdefault(t.customer_id, []).append(t)

    high_velocity_found = False
    for cust_id, txns in customer_txns_map.items():
        recent_txns = [t for t in txns if (ref_time - t.timestamp) <= timedelta(hours=48)]
        if len(recent_txns) >= 5:
            high_velocity_found = True
            break
    assert high_velocity_found, "High velocity customer scenario must be represented"


def test_database_persistence_and_idempotency(db_session: Session):
    """Verify saving to SQLite, checking duplicate prevention, and verifying reset."""
    generator = SyntheticDataGenerator(seed=42, num_customers=20)

    # Initial save
    result1 = generator.generate_and_save(session=db_session, reset=False)
    assert result1["status"] == "created"
    assert result1["customers"] == 20

    # Re-run without reset should skip to avoid duplicate records
    result2 = generator.generate_and_save(session=db_session, reset=False)
    assert result2["status"] == "skipped_existing"
    assert result2["customers"] == 20

    # Re-run with reset should clear and regenerate
    result3 = generator.generate_and_save(session=db_session, reset=True)
    assert result3["status"] == "created"
    assert result3["customers"] == 20

