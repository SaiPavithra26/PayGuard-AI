"""Transaction ORM model for PayLater Shield."""

from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, List
from sqlalchemy import (
    CheckConstraint,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.models.base import Base, UTCDateTime
from backend.app.models.enums import TransactionStatus

if TYPE_CHECKING:
    from backend.app.models.customer import Customer
    from backend.app.models.installment import Installment


class Transaction(Base):
    """Transaction record representing an attempted or completed purchase."""

    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_transaction_positive_amount"),
        Index("ix_transactions_customer_timestamp", "customer_id", "timestamp"),
    )

    transaction_id: Mapped[str] = mapped_column(
        String(50),
        primary_key=True,
        index=True,
        doc="Unique transaction identifier (e.g., TXN_98765)",
    )
    customer_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("customers.customer_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Reference to the customer who initiated the transaction",
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2, asdecimal=True),
        nullable=False,
        doc="Transaction amount in major currency units (e.g. 149.99)",
    )
    merchant: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        doc="Merchant or seller identifier",
    )
    timestamp: Mapped[datetime] = mapped_column(
        UTCDateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
        doc="Timestamp of the transaction (UTC)",
    )
    transaction_status: Mapped[TransactionStatus] = mapped_column(
        SAEnum(TransactionStatus, native_enum=False, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=TransactionStatus.PENDING,
        index=True,
        doc="Status of the transaction (PENDING, APPROVED, DECLINED, COMPLETED, FAILED)",
    )

    # Relationships
    customer: Mapped["Customer"] = relationship(
        "Customer",
        back_populates="transactions",
    )
    installments: Mapped[List["Installment"]] = relationship(
        "Installment",
        back_populates="transaction",
    )

    def __repr__(self) -> str:
        return (
            f"<Transaction(transaction_id='{self.transaction_id}', "
            f"customer_id='{self.customer_id}', "
            f"amount={self.amount}, "
            f"status='{self.transaction_status}')>"
        )

