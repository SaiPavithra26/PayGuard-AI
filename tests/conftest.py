"""Pytest configuration, fixtures, and database setup for testing."""

from datetime import datetime, timezone
from typing import AsyncGenerator, Generator
import pytest
import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

# Ensure database listener and models are imported
import backend.app.database  # Registers PRAGMA foreign_keys=ON listener
from backend.app.database import get_db
from backend.app.main import app
from backend.app.models.base import Base
from backend.app.models.customer import Customer
from backend.app.models.enums import IdentityStatus


@pytest.fixture(scope="function")
def test_engine():
    """Create a fresh in-memory SQLite engine for each test function."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture(scope="function")
def db_session(test_engine) -> Generator[Session, None, None]:
    """Yield an isolated database session for each test function."""
    session = Session(bind=test_engine)
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def sample_customer(db_session: Session) -> Customer:
    """Fixture providing a standard active customer."""
    cust = Customer(
        customer_id="CUST_TEST_001",
        account_created_at=datetime.now(timezone.utc),
        identity_status=IdentityStatus.VERIFIED,
        device_risk_signal="LOW_RISK_MOBILE",
    )
    db_session.add(cust)
    db_session.commit()
    return cust


@pytest.fixture(scope="function")
async def client(db_session: Session) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Async test client using httpx ASGITransport (avoids TestClient thread deadlock)."""
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
    app.dependency_overrides.clear()
