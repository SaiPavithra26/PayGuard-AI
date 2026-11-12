"""Customer ORM model for PayLater Shield."""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional
from sqlalchemy import Enum as SAEnum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UTCDateTime
from app.models.enums import IdentityStatus

if TYPE_CHECKING:
    from app.models.installment import Installment
    from app.models.risk_assessment import RiskAssessment
    from app.models.transaction import Transaction


class Customer(Base):
    """Customer entity holding account status and credit activity."""

    __tablename__ = "customers"

    customer_id: Mapped[str] = mapped_column(
        String(50),
        primary_key=True,
        index=True,
        doc="Unique identifier for the customer (e.g., CUST_1001)",
    )
    account_created_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        doc="Timestamp when the customer account was created (UTC)",
    )
    identity_status: Mapped[IdentityStatus] = mapped_column(
        SAEnum(IdentityStatus, native_enum=False, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=IdentityStatus.PENDING,
        index=True,
        doc="Identity verification status",
    )
    device_risk_signal: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        doc="Optional device or network risk signal for development/testing",
    )

    # Relationships
    transactions: Mapped[List["Transaction"]] = relationship(
        "Transaction",
        back_populates="customer",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    installments: Mapped[List["Installment"]] = relationship(
        "Installment",
        back_populates="customer",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    risk_assessments: Mapped[List["RiskAssessment"]] = relationship(
        "RiskAssessment",
        back_populates="customer",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return (
            f"<Customer(customer_id='{self.customer_id}', "
            f"identity_status='{self.identity_status}', "
            f"device_risk_signal='{self.device_risk_signal}')>"
        )


