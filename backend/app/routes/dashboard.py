"""FastAPI router for PayLater Shield operator dashboard metrics."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.dashboard import DashboardMetricsResponse
from app.services.dashboard import get_dashboard_metrics

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get(
    "",
    response_model=DashboardMetricsResponse,
    summary="Get aggregated dashboard metrics",
    description=(
        "Returns live portfolio statistics including total customers, total transactions, "
        "risk category distribution, and total outstanding/overdue installment exposure."
    ),
)
def get_dashboard(
    db: Session = Depends(get_db),
) -> DashboardMetricsResponse:
    """Retrieve live portfolio statistics and risk distribution."""
    return get_dashboard_metrics(session=db)


