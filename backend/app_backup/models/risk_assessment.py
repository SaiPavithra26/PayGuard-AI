"""RiskAssessment ORM model for PayLater Shield."""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict
from sqlalchemy import (
    CheckConstraint,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    JSON,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.models.base import Base, UTCDateTime
from backend.app.models.enums import RecommendedAction, RiskLevel

if TYPE_CHECKING:
    from backend.app.models.customer import Customer


class RiskAssessment(Base):
    """Evaluation record capturing risk scores, factor explanations, and decision actions."""

    __tablename__ = "risk_assessments"
    __table_args__ = (
        CheckConstraint(
            "risk_score >= 0 AND risk_score <= 100",
            name="ck_risk_assessment_score_range",
        ),
    )

    assessment_id: Mapped[str] = mapped_column(
        String(50),
        primary_key=True,
        index=True,
        doc="Unique assessment identifier (e.g., RSK_55501)",
    )
    customer_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("customers.customer_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Reference to the assessed customer",
    )
    risk_score: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        doc="Overall normalized risk score between 0 (lowest risk) and 100 (highest risk)",
    )
    risk_level: Mapped[RiskLevel] = mapped_column(
        SAEnum(RiskLevel, native_enum=False, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        index=True,
        doc="Risk tier classification (LOW, MEDIUM, HIGH)",
    )
    risk_reasons: Mapped[Dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        doc="Structured breakdown of contributing risk signals, factor scores, and rationale",
    )
    recommended_action: Mapped[RecommendedAction] = mapped_column(
        SAEnum(RecommendedAction, native_enum=False, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        index=True,
        doc="Automated underwriting recommendation (APPROVE, REVIEW, DECLINE)",
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
        doc="Timestamp when the risk assessment was evaluated (UTC)",
    )

    # Relationships
    customer: Mapped["Customer"] = relationship(
        "Customer",
        back_populates="risk_assessments",
    )

    def __repr__(self) -> str:
        return (
            f"<RiskAssessment(assessment_id='{self.assessment_id}', "
            f"customer_id='{self.customer_id}', "
            f"risk_score={self.risk_score}, "
            f"risk_level='{self.risk_level}', "
            f"recommended_action='{self.recommended_action}')>"
        )

