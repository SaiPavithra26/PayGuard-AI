"""Routes package initialization and router exports."""

from backend.app.routes.dashboard import router as dashboard_router
from backend.app.routes.risk import router as risk_router

__all__ = ["risk_router", "dashboard_router"]

