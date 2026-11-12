"""Command-line interface to generate synthetic data for PayLater Shield."""

import argparse
import sys
from collections import Counter
from decimal import Decimal
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import engine, get_db, init_db
from app.models.customer import Customer
from app.models.installment import Installment
from app.models.transaction import Transaction
from app.services.synthetic_data import SyntheticDataGenerator


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Generate reproducible synthetic data for PayLater Shield risk modeling."
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducible generation (default: 42)",
    )
    parser.add_argument(
        "--num-customers",
        type=int,
        default=100,
        help="Number of synthetic customers to generate (default: 100)",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        default=False,
        help="Purge previously generated synthetic records before generating new ones",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Generate entities in memory and print metrics without saving to database",
    )
    return parser.parse_args()


def display_summary(session: Session) -> None:
    """Display statistical summary of synthetic entities currently in the database."""
    total_custs = session.scalar(
        select(func.count(Customer.customer_id)).where(Customer.customer_id.like("CUST_SYNTH_%"))
    )
    total_txns = session.scalar(
        select(func.count(Transaction.transaction_id)).where(
            Transaction.transaction_id.like("TXN_SYNTH_%")
        )
    )
    total_insts = session.scalar(
        select(func.count(Installment.installment_id)).where(
            Installment.installment_id.like("INST_SYNTH_%")
        )
    )

    print("\n" + "=" * 55)
    print(" PAYLATER SHIELD SYNTHETIC DATASET SUMMARY")
    print("=" * 55)
    print(f"  Synthetic Customers:    {total_custs}")
    print(f"  Synthetic Transactions: {total_txns}")
    print(f"  Synthetic Installments: {total_insts}")

    # Installment breakdown
    inst_statuses = session.execute(
        select(Installment.payment_status, func.count(Installment.installment_id))
        .where(Installment.installment_id.like("INST_SYNTH_%"))
        .group_by(Installment.payment_status)
    ).all()

    print("\n  Installment Status Breakdown:")
    for status, count in sorted(inst_statuses, key=lambda x: str(x[0])):
        print(f"    - {str(status):<12}: {count}")

    # Identity status breakdown
    id_statuses = session.execute(
        select(Customer.identity_status, func.count(Customer.customer_id))
        .where(Customer.customer_id.like("CUST_SYNTH_%"))
        .group_by(Customer.identity_status)
    ).all()

    print("\n  Customer Identity Status Breakdown:")
    for status, count in sorted(id_statuses, key=lambda x: str(x[0])):
        print(f"    - {str(status):<12}: {count}")

    # Sample records
    sample_cust = session.scalars(
        select(Customer).where(Customer.customer_id.like("CUST_SYNTH_%")).limit(2)
    ).all()
    sample_txns = session.scalars(
        select(Transaction).where(Transaction.transaction_id.like("TXN_SYNTH_%")).limit(2)
    ).all()
    sample_insts = session.scalars(
        select(Installment).where(Installment.installment_id.like("INST_SYNTH_%")).limit(2)
    ).all()

    print("\n  Sample Synthetic Customer Profiles:")
    for c in sample_cust:
        print(f"    [Customer] ID={c.customer_id} | Created={c.account_created_at.strftime('%Y-%m-%d')} | Identity={c.identity_status} | Signal={c.device_risk_signal}")

    print("\n  Sample Synthetic Transactions:")
    for t in sample_txns:
        print(f"    [Transaction] ID={t.transaction_id} | Cust={t.customer_id} | Amount=${t.amount} | Merchant={t.merchant} | Status={t.transaction_status}")

    print("\n  Sample Synthetic Installments:")
    for i in sample_insts:
        paid_str = i.paid_at.strftime('%Y-%m-%d') if i.paid_at else "None"
        print(f"    [Installment] ID={i.installment_id} | Cust={i.customer_id} | Amount=${i.amount} | Due={i.due_date.strftime('%Y-%m-%d')} | Status={i.payment_status} | PaidAt={paid_str}")

    print("=" * 55 + "\n")


def main() -> None:
    """CLI execution entrypoint."""
    args = parse_args()
    print(f"Generating synthetic data (seed={args.seed}, num_customers={args.num_customers}, reset={args.reset})...")

    generator = SyntheticDataGenerator(seed=args.seed, num_customers=args.num_customers)

    if args.dry_run:
        custs, txns, insts = generator.generate()
        print("\n[DRY RUN] Generated in-memory dataset successfully:")
        print(f"  Customers:    {len(custs)}")
        print(f"  Transactions: {len(txns)}")
        print(f"  Installments: {len(insts)}")
        return

    # Ensure schema is initialized
    init_db(engine)

    with Session(bind=engine) as session:
        result = generator.generate_and_save(session=session, reset=args.reset)
        if result["status"] == "skipped_existing":
            print(f"[NOTICE] Synthetic records already exist in database ({result['customers']} customers).")
            print("         Skipped generation to prevent duplicates. Use --reset to re-generate.")
        else:
            print(f"[SUCCESS] Created {result['customers']} customers, {result['transactions']} transactions, {result['installments']} installments.")

        display_summary(session)


if __name__ == "__main__":
    main()


