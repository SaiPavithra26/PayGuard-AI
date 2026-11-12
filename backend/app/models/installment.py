"""Installment ORM model for PayLater Shield."""

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional
from sqlalchemy import (
    CheckConstraint,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UTCDateTime
from app.models.enums import PaymentStatus

if TYPE_CHECKING:
    from app.models.customer import Customer
    from app.models.transaction import Transaction


class Installment(Base):
    """Installment schedule entity tracking individual repayment obligations."""

    __tablename__ = "installments"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_installment_positive_amount"),
        Index("ix_installments_customer_status_due", "customer_id", "payment_status", "due_date"),
    )

    installment_id: Mapped[str] = mapped_column(
        String(50),
        primary_key=True,
        index=True,
        doc="Unique installment identifier (e.g., INST_1001_1)",
    )
    customer_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("customers.customer_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Reference to the customer responsible for repayment",
    )
    transaction_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("transactions.transaction_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="Optional reference to the parent transaction",
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2, asdecimal=True),
        nullable=False,
        doc="Installment amount due",
    )
    due_date: Mapped[datetime] = mapped_column(
        UTCDateTime,
        nullable=False,
        index=True,
        doc="Scheduled payment due date (UTC)",
    )
    payment_status: Mapped[PaymentStatus] = mapped_column(
        SAEnum(PaymentStatus, native_enum=False, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=PaymentStatus.PENDING,
        index=True,
        doc="Repayment status (PENDING, PAID, OVERDUE, CANCELLED)",
    )
    paid_at: Mapped[Optional[datetime]] = mapped_column(
        UTCDateTime,
        nullable=True,
        doc="Timestamp when this installment was marked paid (UTC)",
    )

    # Relationships
    customer: Mapped["Customer"] = relationship(
        "Customer",
        back_populates="installments",
    )
    transaction: Mapped[Optional["Transaction"]] = relationship(
        "Transaction",
        back_populates="installments",
    )

    def __repr__(self) -> str:
        return (
            f"<Installment(installment_id='{self.installment_id}', "
            f"customer_id='{self.customer_id}', "
            f"amount={self.amount}, "
            f"status='{self.payment_status}')>"
        )


