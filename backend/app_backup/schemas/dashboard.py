"""Pydantic schemas for aggregated dashboard metrics."""

from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field


class DashboardMetricsResponse(BaseModel):
    """Aggregated portfolio metrics for PayLater Shield operator dashboard."""

    total_customers: int = Field(..., description="Total registered customers in database")
    total_transactions: int = Field(..., description="Total recorded transactions in database")
    total_assessments: int = Field(..., description="Total risk evaluations performed")

    # Risk level breakdown
    low_risk_assessments: int = Field(..., description="Number of assessments classified as LOW risk")
    medium_risk_assessments: int = Field(..., description="Number of assessments classified as MEDIUM risk")
    high_risk_assessments: int = Field(..., description="Number of assessments classified as HIGH risk")

    # Exposure metrics
    total_outstanding_exposure: Decimal = Field(..., description="Total active unpaid installment exposure")
    total_overdue_exposure: Decimal = Field(..., description="Total delinquent overdue installment balance")
    total_due_next_7d_exposure: Decimal = Field(..., description="Total installment obligations maturing in next 7 days")

    calculated_at: datetime = Field(..., description="UTC timestamp when metrics were aggregated")

    model_config = ConfigDict(from_attributes=True)

