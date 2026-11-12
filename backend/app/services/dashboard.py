"""Aggregated metrics service for PayLater Shield operator dashboard."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.enums import PaymentStatus, RiskLevel
from app.models.installment import Installment
from app.models.risk_assessment import RiskAssessment
from app.models.transaction import Transaction
from app.schemas.dashboard import DashboardMetricsResponse


def get_dashboard_metrics(
    session: Session,
    evaluation_time: Optional[datetime] = None,
) -> DashboardMetricsResponse:
    """Calculate live aggregated metrics directly from database records.

    Args:
        session: Active database session.
        evaluation_time: Anchor evaluation time in UTC (defaults to current UTC time).

    Returns:
        DashboardMetricsResponse populated with exact counts and Decimal sums.
    """
    ref_time = evaluation_time or datetime.now(timezone.utc)
    if ref_time.tzinfo is None:
        ref_time = ref_time.replace(tzinfo=timezone.utc)

    due_7d_cutoff = ref_time + timedelta(days=7)

    # 1. Total entity counts
    total_customers = session.scalar(select(func.count(Customer.customer_id))) or 0
    total_transactions = session.scalar(select(func.count(Transaction.transaction_id))) or 0
    total_assessments = session.scalar(select(func.count(RiskAssessment.assessment_id))) or 0

    # 2. Risk level breakdown
    low_risk = session.scalar(
        select(func.count(RiskAssessment.assessment_id)).where(RiskAssessment.risk_level == RiskLevel.LOW)
    ) or 0
    medium_risk = session.scalar(
        select(func.count(RiskAssessment.assessment_id)).where(RiskAssessment.risk_level == RiskLevel.MEDIUM)
    ) or 0
    high_risk = session.scalar(
        select(func.count(RiskAssessment.assessment_id)).where(RiskAssessment.risk_level == RiskLevel.HIGH)
    ) or 0

    # 3. Exposure aggregations
    # Total outstanding: all active unpaid installments (PENDING or OVERDUE)
    outstanding_raw = session.scalar(
        select(func.sum(Installment.amount)).where(
            Installment.payment_status.in_([PaymentStatus.PENDING, PaymentStatus.OVERDUE])
        )
    )
    total_outstanding = Decimal(f"{outstanding_raw:.2f}") if outstanding_raw is not None else Decimal("0.00")

    # Total overdue: explicitly OVERDUE or PENDING past due_date
    overdue_raw = session.scalar(
        select(func.sum(Installment.amount)).where(
            (Installment.payment_status == PaymentStatus.OVERDUE)
            | ((Installment.payment_status == PaymentStatus.PENDING) & (Installment.due_date < ref_time))
        )
    )
    total_overdue = Decimal(f"{overdue_raw:.2f}") if overdue_raw is not None else Decimal("0.00")

    # Total due in next 7 days: PENDING with ref_time <= due_date <= due_7d_cutoff
    next_7d_raw = session.scalar(
        select(func.sum(Installment.amount)).where(
            (Installment.payment_status == PaymentStatus.PENDING)
            & (Installment.due_date >= ref_time)
            & (Installment.due_date <= due_7d_cutoff)
        )
    )
    total_next_7d = Decimal(f"{next_7d_raw:.2f}") if next_7d_raw is not None else Decimal("0.00")

    return DashboardMetricsResponse(
        total_customers=total_customers,
        total_transactions=total_transactions,
        total_assessments=total_assessments,
        low_risk_assessments=low_risk,
        medium_risk_assessments=medium_risk,
        high_risk_assessments=high_risk,
        total_outstanding_exposure=total_outstanding,
        total_overdue_exposure=total_overdue,
        total_due_next_7d_exposure=total_next_7d,
        calculated_at=ref_time,
    )


