"""Deterministic synthetic data generator for PayLater Shield testing and risk modeling."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import random
from typing import Dict, List, Optional, Tuple
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.customer import Customer
from backend.app.models.enums import IdentityStatus, PaymentStatus, TransactionStatus
from backend.app.models.installment import Installment
from backend.app.models.transaction import Transaction

# Clearly synthetic merchant identifiers
SYNTHETIC_MERCHANTS = [
    "SYNTH_ELECTRONICS_DEPOT",
    "SYNTH_TECH_MART",
    "SYNTH_FASHION_HUB",
    "SYNTH_HOME_GOODS",
    "SYNTH_OUTDOOR_GEAR",
    "SYNTH_STREAMING_SERVICES",
    "SYNTH_TRAVEL_BOOKINGS",
    "SYNTH_BEAUTY_SUPPLY",
    "SYNTH_OFFICE_STORE",
    "SYNTH_SPORTING_WORLD",
]

# Scenario labels for synthetic dataset profiling
SCENARIO_NORMAL = "NORMAL_ESTABLISHED"
SCENARIO_HIGH_VELOCITY = "HIGH_VELOCITY_BURST"
SCENARIO_HIGH_EXPOSURE = "HIGH_CREDIT_EXPOSURE"
SCENARIO_PENDING_IDENTITY = "PENDING_IDENTITY"
SCENARIO_OVERDUE = "OVERDUE_REPAYMENTS"
SCENARIO_FAILED_PAYMENTS = "FAILED_REPAYMENTS"
SCENARIO_NEW_NORMAL = "NEW_NORMAL_CUSTOMER"
SCENARIO_MULTI_RISK = "MULTI_RISK_COMPOSITE"


class SyntheticDataGenerator:
    """Generates realistic, reproducible synthetic data for PayLater Shield."""

    def __init__(
        self,
        seed: int = 42,
        num_customers: int = 100,
        reference_time: Optional[datetime] = None,
    ) -> None:
        """Initialize the synthetic data generator.

        Args:
            seed: Fixed random seed for complete reproducibility.
            num_customers: Total number of synthetic customer profiles to generate.
            reference_time: Anchor datetime for all relative timestamps (defaults to 2026-11-12 00:00 UTC).
        """
        self.seed = seed
        self.num_customers = num_customers
        self.rng = random.Random(seed)
        self.reference_time = reference_time or datetime(2026, 11, 12, 0, 0, 0, tzinfo=timezone.utc)

        # Monotonically increasing counters for deterministic synthetic IDs
        self._cust_counter = 0
        self._txn_counter = 0
        self._inst_counter = 0

    def _next_cust_id(self) -> str:
        self._cust_counter += 1
        return f"CUST_SYNTH_{self._cust_counter:04d}"

    def _next_txn_id(self) -> str:
        self._txn_counter += 1
        return f"TXN_SYNTH_{self._txn_counter:05d}"

    def _next_inst_id(self) -> str:
        self._inst_counter += 1
        return f"INST_SYNTH_{self._inst_counter:05d}"

    def _random_amount(self, min_cents: int, max_cents: int) -> Decimal:
        """Generate a random monetary amount as Decimal avoiding floating-point inaccuracies."""
        cents = self.rng.randint(min_cents, max_cents)
        return Decimal(f"{cents / 100:.2f}")

    def generate(self) -> Tuple[List[Customer], List[Transaction], List[Installment]]:
        """Generate all customer, transaction, and installment entities in memory.

        Returns:
            Tuple of (customers, transactions, installments).
        """
        # Reset counters for consistent generator reuse
        self.rng = random.Random(self.seed)
        self._cust_counter = 0
        self._txn_counter = 0
        self._inst_counter = 0

        customers: List[Customer] = []
        transactions: List[Transaction] = []
        installments: List[Installment] = []

        # Scenario distribution across 100 customers:
        # 1. Normal established: ~40%
        # 2. High velocity burst: ~12%
        # 3. High credit exposure: ~12%
        # 4. Pending identity: ~10%
        # 5. Overdue installments: ~10%
        # 6. Failed repayments: ~6%
        # 7. New normal customer: ~6%
        # 8. Multi-risk composite: ~4%
        count_normal = int(round(self.num_customers * 0.40))
        count_velocity = int(round(self.num_customers * 0.12))
        count_exposure = int(round(self.num_customers * 0.12))
        count_pending_id = int(round(self.num_customers * 0.10))
        count_overdue = int(round(self.num_customers * 0.10))
        count_failed = int(round(self.num_customers * 0.06))
        count_new_normal = int(round(self.num_customers * 0.06))
        count_multi_risk = self.num_customers - (
            count_normal
            + count_velocity
            + count_exposure
            + count_pending_id
            + count_overdue
            + count_failed
            + count_new_normal
        )

        scenarios = (
            [SCENARIO_NORMAL] * count_normal
            + [SCENARIO_HIGH_VELOCITY] * count_velocity
            + [SCENARIO_HIGH_EXPOSURE] * count_exposure
            + [SCENARIO_PENDING_IDENTITY] * count_pending_id
            + [SCENARIO_OVERDUE] * count_overdue
            + [SCENARIO_FAILED_PAYMENTS] * count_failed
            + [SCENARIO_NEW_NORMAL] * count_new_normal
            + [SCENARIO_MULTI_RISK] * count_multi_risk
        )

        for scenario in scenarios:
            cust, txns, insts = self._build_customer_scenario(scenario)
            customers.append(cust)
            transactions.extend(txns)
            installments.extend(insts)

        return customers, transactions, installments

    def _build_customer_scenario(
        self, scenario: str
    ) -> Tuple[Customer, List[Transaction], List[Installment]]:
        """Construct a customer and their linked transactions/installments for a specific scenario."""
        cust_id = self._next_cust_id()
        txns: List[Transaction] = []
        insts: List[Installment] = []

        if scenario == SCENARIO_NORMAL:
            # Established customer with regular shopping and reliable repayment
            created_days_ago = self.rng.randint(90, 365)
            created_at = self.reference_time - timedelta(days=created_days_ago)
            cust = Customer(
                customer_id=cust_id,
                account_created_at=created_at,
                identity_status=IdentityStatus.VERIFIED,
                device_risk_signal="TRUSTED_DEVICE",
            )
            # 2 to 4 transactions spaced across the account history
            num_txns = self.rng.randint(2, 4)
            for i in range(num_txns):
                offset_days = self.rng.randint(20, created_days_ago - 2)
                txn_time = self.reference_time - timedelta(days=offset_days)
                amount = self._random_amount(2500, 18000)
                txn = Transaction(
                    transaction_id=self._next_txn_id(),
                    customer_id=cust_id,
                    amount=amount,
                    merchant=self.rng.choice(SYNTHETIC_MERCHANTS),
                    timestamp=txn_time,
                    transaction_status=TransactionStatus.COMPLETED,
                )
                txns.append(txn)

                # Generate Pay-in-4 installment schedule for first transaction
                if i == 0:
                    inst_amount = Decimal(f"{amount / 4:.2f}")
                    # Past paid installment (paid before due date and safely before reference_time)
                    paid_time = min(txn_time + timedelta(days=12), self.reference_time - timedelta(days=1))
                    insts.append(
                        Installment(
                            installment_id=self._next_inst_id(),
                            customer_id=cust_id,
                            transaction_id=txn.transaction_id,
                            amount=inst_amount,
                            due_date=txn_time + timedelta(days=14),
                            payment_status=PaymentStatus.PAID,
                            paid_at=paid_time,
                        )
                    )
                    # 60% chance of an ongoing future pending installment
                    if self.rng.random() < 0.6:
                        insts.append(
                            Installment(
                                installment_id=self._next_inst_id(),
                                customer_id=cust_id,
                                transaction_id=txn.transaction_id,
                                amount=inst_amount,
                                due_date=self.reference_time + timedelta(days=self.rng.randint(7, 21)),
                                payment_status=PaymentStatus.PENDING,
                                paid_at=None,
                            )
                        )

        elif scenario == SCENARIO_HIGH_VELOCITY:
            # Customer exhibiting a burst of multiple rapid transactions in a short window
            created_days_ago = self.rng.randint(14, 60)
            created_at = self.reference_time - timedelta(days=created_days_ago)
            cust = Customer(
                customer_id=cust_id,
                account_created_at=created_at,
                identity_status=IdentityStatus.VERIFIED,
                device_risk_signal="RAPID_IP_SWITCH",
            )
            # 6 to 9 transactions, mostly clustered within the last 24 to 48 hours
            num_txns = self.rng.randint(6, 9)
            for _ in range(num_txns):
                hours_ago = self.rng.randint(1, 48)
                txn_time = self.reference_time - timedelta(hours=hours_ago)
                amount = self._random_amount(3000, 22000)
                txn = Transaction(
                    transaction_id=self._next_txn_id(),
                    customer_id=cust_id,
                    amount=amount,
                    merchant=self.rng.choice(SYNTHETIC_MERCHANTS),
                    timestamp=txn_time,
                    transaction_status=self.rng.choice(
                        [TransactionStatus.APPROVED, TransactionStatus.PENDING]
                    ),
                )
                txns.append(txn)

            # Single active installment
            insts.append(
                Installment(
                    installment_id=self._next_inst_id(),
                    customer_id=cust_id,
                    transaction_id=txns[0].transaction_id,
                    amount=Decimal("45.00"),
                    due_date=self.reference_time + timedelta(days=14),
                    payment_status=PaymentStatus.PENDING,
                    paid_at=None,
                )
            )

        elif scenario == SCENARIO_HIGH_EXPOSURE:
            # Customer with high cumulative outstanding installments across multiple orders
            created_days_ago = self.rng.randint(60, 200)
            created_at = self.reference_time - timedelta(days=created_days_ago)
            cust = Customer(
                customer_id=cust_id,
                account_created_at=created_at,
                identity_status=IdentityStatus.VERIFIED,
                device_risk_signal="TRUSTED_DEVICE",
            )
            # 4 to 6 transactions
            num_txns = self.rng.randint(4, 6)
            for _ in range(num_txns):
                offset_days = self.rng.randint(5, 30)
                txn_time = self.reference_time - timedelta(days=offset_days)
                amount = self._random_amount(15000, 35000)
                txn = Transaction(
                    transaction_id=self._next_txn_id(),
                    customer_id=cust_id,
                    amount=amount,
                    merchant=self.rng.choice(SYNTHETIC_MERCHANTS),
                    timestamp=txn_time,
                    transaction_status=TransactionStatus.APPROVED,
                )
                txns.append(txn)

                # Substantial outstanding installments due in future
                inst_amount = Decimal(f"{amount / 2:.2f}")
                insts.append(
                    Installment(
                        installment_id=self._next_inst_id(),
                        customer_id=cust_id,
                        transaction_id=txn.transaction_id,
                        amount=inst_amount,
                        due_date=self.reference_time + timedelta(days=self.rng.randint(5, 45)),
                        payment_status=PaymentStatus.PENDING,
                        paid_at=None,
                    )
                )

        elif scenario == SCENARIO_PENDING_IDENTITY:
            # Customer whose identity verification is still pending review
            created_days_ago = self.rng.randint(2, 14)
            created_at = self.reference_time - timedelta(days=created_days_ago)
            cust = Customer(
                customer_id=cust_id,
                account_created_at=created_at,
                identity_status=IdentityStatus.PENDING,
                device_risk_signal="NEW_DEVICE",
            )
            # 1 to 2 initial transactions
            num_txns = self.rng.randint(1, 2)
            for _ in range(num_txns):
                offset_days = self.rng.randint(0, created_days_ago - 1)
                txn_time = self.reference_time - timedelta(days=offset_days, hours=self.rng.randint(1, 12))
                amount = self._random_amount(2000, 9000)
                txn = Transaction(
                    transaction_id=self._next_txn_id(),
                    customer_id=cust_id,
                    amount=amount,
                    merchant=self.rng.choice(SYNTHETIC_MERCHANTS),
                    timestamp=txn_time,
                    transaction_status=TransactionStatus.PENDING,
                )
                txns.append(txn)

        elif scenario == SCENARIO_OVERDUE:
            # Customer with active overdue installments (delinquency signal)
            created_days_ago = self.rng.randint(60, 240)
            created_at = self.reference_time - timedelta(days=created_days_ago)
            cust = Customer(
                customer_id=cust_id,
                account_created_at=created_at,
                identity_status=IdentityStatus.VERIFIED,
                device_risk_signal="TRUSTED_DEVICE",
            )
            num_txns = self.rng.randint(2, 3)
            for idx in range(num_txns):
                offset_days = self.rng.randint(35, 60)
                txn_time = self.reference_time - timedelta(days=offset_days)
                amount = self._random_amount(4000, 15000)
                txn = Transaction(
                    transaction_id=self._next_txn_id(),
                    customer_id=cust_id,
                    amount=amount,
                    merchant=self.rng.choice(SYNTHETIC_MERCHANTS),
                    timestamp=txn_time,
                    transaction_status=TransactionStatus.APPROVED,
                )
                txns.append(txn)

                if idx == 0:
                    # Overdue installment (past due date, unpaid)
                    overdue_days = self.rng.randint(5, 30)
                    insts.append(
                        Installment(
                            installment_id=self._next_inst_id(),
                            customer_id=cust_id,
                            transaction_id=txn.transaction_id,
                            amount=Decimal(f"{amount / 2:.2f}"),
                            due_date=self.reference_time - timedelta(days=overdue_days),
                            payment_status=PaymentStatus.OVERDUE,
                            paid_at=None,
                        )
                    )
                else:
                    # Normal past paid installment
                    insts.append(
                        Installment(
                            installment_id=self._next_inst_id(),
                            customer_id=cust_id,
                            transaction_id=txn.transaction_id,
                            amount=Decimal(f"{amount / 2:.2f}"),
                            due_date=txn_time + timedelta(days=14),
                            payment_status=PaymentStatus.PAID,
                            paid_at=txn_time + timedelta(days=13),
                        )
                    )

        elif scenario == SCENARIO_FAILED_PAYMENTS:
            # Customer with failed transactions and cancelled repayment plans
            created_days_ago = self.rng.randint(45, 180)
            created_at = self.reference_time - timedelta(days=created_days_ago)
            cust = Customer(
                customer_id=cust_id,
                account_created_at=created_at,
                identity_status=IdentityStatus.VERIFIED,
                device_risk_signal="UNRECOGNIZED_BROWSER",
            )
            num_txns = self.rng.randint(2, 4)
            for idx in range(num_txns):
                offset_days = self.rng.randint(10, 40)
                txn_time = self.reference_time - timedelta(days=offset_days)
                amount = self._random_amount(5000, 20000)
                status = (
                    TransactionStatus.FAILED
                    if idx == 0
                    else self.rng.choice([TransactionStatus.COMPLETED, TransactionStatus.DECLINED])
                )
                txn = Transaction(
                    transaction_id=self._next_txn_id(),
                    customer_id=cust_id,
                    amount=amount,
                    merchant=self.rng.choice(SYNTHETIC_MERCHANTS),
                    timestamp=txn_time,
                    transaction_status=status,
                )
                txns.append(txn)

                if idx == 0:
                    insts.append(
                        Installment(
                            installment_id=self._next_inst_id(),
                            customer_id=cust_id,
                            transaction_id=txn.transaction_id,
                            amount=Decimal(f"{amount / 2:.2f}"),
                            due_date=txn_time + timedelta(days=14),
                            payment_status=PaymentStatus.CANCELLED,
                            paid_at=None,
                        )
                    )

        elif scenario == SCENARIO_NEW_NORMAL:
            # Recently created account with legitimate, normal low-volume activity
            # Not fraudulent despite having short history
            created_days_ago = self.rng.randint(3, 10)
            created_at = self.reference_time - timedelta(days=created_days_ago)
            cust = Customer(
                customer_id=cust_id,
                account_created_at=created_at,
                identity_status=IdentityStatus.VERIFIED,
                device_risk_signal="NEW_DEVICE",
            )
            # 1 to 2 small, ordinary transactions
            num_txns = self.rng.randint(1, 2)
            for _ in range(num_txns):
                offset_days = self.rng.randint(0, created_days_ago - 1)
                txn_time = self.reference_time - timedelta(days=offset_days)
                amount = self._random_amount(1500, 6500)
                txn = Transaction(
                    transaction_id=self._next_txn_id(),
                    customer_id=cust_id,
                    amount=amount,
                    merchant=self.rng.choice(SYNTHETIC_MERCHANTS),
                    timestamp=txn_time,
                    transaction_status=TransactionStatus.APPROVED,
                )
                txns.append(txn)

            # Single pending installment with regular future due date
            insts.append(
                Installment(
                    installment_id=self._next_inst_id(),
                    customer_id=cust_id,
                    transaction_id=txns[0].transaction_id,
                    amount=Decimal(f"{txns[0].amount / 2:.2f}"),
                    due_date=self.reference_time + timedelta(days=14),
                    payment_status=PaymentStatus.PENDING,
                    paid_at=None,
                )
            )

        elif scenario == SCENARIO_MULTI_RISK:
            # Complex profile combining multiple warning signals:
            # High velocity + overdue installment + suspicious device signal + unverified identity
            created_days_ago = self.rng.randint(15, 45)
            created_at = self.reference_time - timedelta(days=created_days_ago)
            cust = Customer(
                customer_id=cust_id,
                account_created_at=created_at,
                identity_status=IdentityStatus.UNVERIFIED,
                device_risk_signal="SUSPICIOUS_EMULATOR",
            )
            # Rapid burst of transactions in past 24 hours
            num_txns = self.rng.randint(6, 8)
            for idx in range(num_txns):
                hours_ago = self.rng.randint(1, 24)
                txn_time = self.reference_time - timedelta(hours=hours_ago)
                amount = self._random_amount(8000, 30000)
                txn = Transaction(
                    transaction_id=self._next_txn_id(),
                    customer_id=cust_id,
                    amount=amount,
                    merchant=self.rng.choice(SYNTHETIC_MERCHANTS),
                    timestamp=txn_time,
                    transaction_status=(
                        TransactionStatus.DECLINED if idx == 0 else TransactionStatus.PENDING
                    ),
                )
                txns.append(txn)

            # Past overdue installment
            insts.append(
                Installment(
                    installment_id=self._next_inst_id(),
                    customer_id=cust_id,
                    transaction_id=txns[0].transaction_id,
                    amount=Decimal("120.00"),
                    due_date=self.reference_time - timedelta(days=10),
                    payment_status=PaymentStatus.OVERDUE,
                    paid_at=None,
                )
            )
            # Substantial pending installment
            insts.append(
                Installment(
                    installment_id=self._next_inst_id(),
                    customer_id=cust_id,
                    transaction_id=txns[1].transaction_id,
                    amount=Decimal("150.00"),
                    due_date=self.reference_time + timedelta(days=7),
                    payment_status=PaymentStatus.PENDING,
                    paid_at=None,
                )
            )

        else:
            raise ValueError(f"Unknown scenario archetype: {scenario}")

        return cust, txns, insts

    def clear_synthetic_data(self, session: Session) -> Dict[str, int]:
        """Safely remove existing synthetic records from the database.

        Deletes customers matching 'CUST_SYNTH_%' (cascading to their transactions and installments).

        Returns:
            Dictionary with counts of deleted records.
        """
        # Count existing synthetic entities before deletion
        synthetic_custs = session.scalars(
            select(Customer).where(Customer.customer_id.like("CUST_SYNTH_%"))
        ).all()
        count_custs = len(synthetic_custs)

        for cust in synthetic_custs:
            session.delete(cust)
        session.commit()

        return {"deleted_customers": count_custs}

    def generate_and_save(
        self, session: Session, reset: bool = False
    ) -> Dict[str, int]:
        """Generate synthetic dataset and persist into the database.

        Args:
            session: SQLAlchemy database session.
            reset: If True, purges previously generated synthetic records before inserting.

        Returns:
            Dictionary with generation summary counts.
        """
        existing_count = session.scalar(
            select(Customer.customer_id)
            .where(Customer.customer_id.like("CUST_SYNTH_%"))
            .limit(1)
        )

        if existing_count is not None:
            if not reset:
                # Idempotency guard: avoid duplicating existing synthetic records
                total_custs = session.query(Customer).filter(Customer.customer_id.like("CUST_SYNTH_%")).count()
                total_txns = session.query(Transaction).filter(Transaction.transaction_id.like("TXN_SYNTH_%")).count()
                total_insts = session.query(Installment).filter(Installment.installment_id.like("INST_SYNTH_%")).count()
                return {
                    "status": "skipped_existing",
                    "customers": total_custs,
                    "transactions": total_txns,
                    "installments": total_insts,
                }
            # Explicit reset requested
            self.clear_synthetic_data(session)

        customers, transactions, installments = self.generate()

        # Batch insert entities in dependency order
        session.add_all(customers)
        session.flush()

        session.add_all(transactions)
        session.flush()

        session.add_all(installments)
        session.commit()

        return {
            "status": "created",
            "customers": len(customers),
            "transactions": len(transactions),
            "installments": len(installments),
        }
