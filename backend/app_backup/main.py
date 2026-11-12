"""FastAPI application entrypoint for PayLater Shield module."""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from backend.app.database import engine, init_db
from backend.app.routes import dashboard_router, risk_router

logger = logging.getLogger("payshield")
logging.basicConfig(level=logging.INFO)


# Initialize database schema on startup
init_db(engine)

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description=(
        "PayGuard AI - PayLater Shield: Pre-purchase risk evaluation, transaction velocity "
        "detection, outstanding installment exposure analysis, and risk monitoring."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# Configure CORS for authorized frontend clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Global Exception Handlers ensuring no internal stack traces leak to API clients
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Format request validation errors into a clean, actionable message."""
    errors = []
    for err in exc.errors():
        loc = " -> ".join(str(l) for l in err.get("loc", []))
        msg = err.get("msg", "Invalid value")
        errors.append(f"{loc}: {msg}")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": "Request validation failed", "errors": errors},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Pass through structured HTTP exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all handler guarding against database and internal runtime leakages."""
    logger.error("Unhandled internal server exception: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An internal error occurred while processing the request."},
    )


# Root health endpoint
@app.get("/health", tags=["Health"])
def health_check() -> dict:
    """Service health and readiness check."""
    return {
        "status": "healthy",
        "service": "PayLater Shield",
        "version": settings.VERSION,
    }


# Register domain routes under /api
app.include_router(risk_router, prefix=settings.API_PREFIX)
app.include_router(dashboard_router, prefix=settings.API_PREFIX)
