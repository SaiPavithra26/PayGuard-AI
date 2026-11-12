"""End-to-end integration tests for PayLater Shield FastAPI endpoints."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest
import httpx
from sqlalchemy.orm import Session

from backend.app.models.customer import Customer
from backend.app.models.enums import (
    IdentityStatus,
    PaymentStatus,
    RecommendedAction,
    RiskLevel,
    TransactionStatus,
)
from backend.app.models.installment import Installment
from backend.app.models.risk_assessment import RiskAssessment
from backend.app.models.transaction import Transaction


@pytest.mark.asyncio
async def test_health_check(client: httpx.AsyncClient):
    """Verify health endpoint reports healthy service status."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "PayLater Shield"


# ===========================================================================
# Endpoint 1: POST /api/risk/assess
# ===========================================================================

@pytest.mark.asyncio
async def test_assess_risk_success_clean_customer(client: httpx.AsyncClient, db_session: Session, sample_customer: Customer):
    """Verify successful risk assessment creation for a clean customer."""
    payload = {
        "customer_id": sample_customer.customer_id,
        "amount": "129.99",
        "merchant": "Tech Superstore",
        "device_risk_signal": "TRUSTED_DEVICE",
    }

    response = await client.post("/api/risk/assess", json=payload)
    assert response.status_code == 201

    data = response.json()
    assert data["customer_id"] == sample_customer.customer_id
    assert Decimal(str(data["proposed_amount"])) == Decimal("129.99")
    assert data["merchant"] == "Tech Superstore"
    assert data["risk_score"] == 0
    assert data["risk_level"] == RiskLevel.LOW
    assert data["recommended_action"] == RecommendedAction.CONTINUE
    assert len(data["reasons"]) >= 1

    # Verify signals and summaries are present
    assert "velocity" in data["signals"]
    assert "exposure" in data["signals"]
    assert "velocity_summary" in data
    assert "exposure_summary" in data

    # Verify persistence in database
    assessment_id = data["assessment_id"]
    db_record = db_session.get(RiskAssessment, assessment_id)
    assert db_record is not None
    assert db_record.customer_id == sample_customer.customer_id
    assert db_record.risk_score == 0


@pytest.mark.asyncio
async def test_assess_risk_high_risk_customer(client: httpx.AsyncClient, db_session: Session):
    """Verify assessment properly detects high risk and returns MANUAL_REVIEW."""
    now = datetime.now(timezone.utc)

    # Setup high risk customer: unverified identity + emulator signal
    cust = Customer(
        customer_id="CUST_API_HIGH",
        account_created_at=now - timedelta(days=20),
        identity_status=IdentityStatus.UNVERIFIED,
        device_risk_signal="SUSPICIOUS_EMULATOR",
    )
    db_session.add(cust)
    db_session.flush()

    # Add 4 rapid transactions
    txns = [
        Transaction(
            transaction_id=f"TXN_API_H_{i}",
            customer_id=cust.customer_id,
            amount=Decimal("150.00"),
            merchant="Electronics Mall",
            timestamp=now - timedelta(hours=i + 1),
            transaction_status=TransactionStatus.APPROVED,
        )
        for i in range(4)
    ]
    # Add overdue installment
    inst = Installment(
        installment_id="INST_API_OD",
        customer_id=cust.customer_id,
        amount=Decimal("100.00"),
        due_date=now - timedelta(days=5),
        payment_status=PaymentStatus.OVERDUE,
    )
    db_session.add_all(txns + [inst])
    db_session.commit()

    payload = {
        "customer_id": "CUST_API_HIGH",
        "amount": "250.00",
        "merchant": "Luxury Boutique",
    }

    response = await client.post("/api/risk/assess", json=payload)
    assert response.status_code == 201

    data = response.json()
    assert data["risk_score"] >= 60
    assert data["risk_level"] == RiskLevel.HIGH
    assert data["recommended_action"] == RecommendedAction.MANUAL_REVIEW
    assert data["velocity_summary"]["is_velocity_elevated"] is True
    assert data["exposure_summary"]["overdue_installment_count"] == 1


@pytest.mark.asyncio
async def test_assess_risk_customer_not_found(client: httpx.AsyncClient):
    """Verify 404 response when assessing non-existent customer."""
    payload = {
        "customer_id": "CUST_DOES_NOT_EXIST",
        "amount": "50.00",
        "merchant": "Store",
    }
    response = await client.post("/api/risk/assess", json=payload)
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_assess_risk_validation_errors(client: httpx.AsyncClient):
    """Verify 422 Unprocessable Entity on invalid input data."""
    # Negative amount
    res1 = await client.post(
        "/api/risk/assess",
        json={"customer_id": "CUST_1", "amount": "-25.00", "merchant": "Store"},
    )
    assert res1.status_code == 422

    # Zero amount
    res2 = await client.post(
        "/api/risk/assess",
        json={"customer_id": "CUST_1", "amount": "0.00", "merchant": "Store"},
    )
    assert res2.status_code == 422

    # Empty customer_id
    res3 = await client.post(
        "/api/risk/assess",
        json={"customer_id": "", "amount": "50.00", "merchant": "Store"},
    )
    assert res3.status_code == 422

    # Extra unknown field (extra='forbid')
    res4 = await client.post(
        "/api/risk/assess",
        json={
            "customer_id": "CUST_1",
            "amount": "50.00",
            "merchant": "Store",
            "illegal_field": "hack",
        },
    )
    assert res4.status_code == 422


# ===========================================================================
# Endpoint 2: GET /api/dashboard
# ===========================================================================

@pytest.mark.asyncio
async def test_dashboard_endpoint_aggregation(client: httpx.AsyncClient, db_session: Session):
    """Verify /api/dashboard returns correct aggregates computed from live database."""
    now = datetime.now(timezone.utc)

    # 1. Customer
    cust = Customer(
        customer_id="CUST_DASH_1",
        account_created_at=now - timedelta(days=60),
        identity_status=IdentityStatus.VERIFIED,
    )
    db_session.add(cust)
    db_session.flush()

    # 2. Transactions
    t1 = Transaction(
        transaction_id="TXN_DASH_1",
        customer_id=cust.customer_id,
        amount=Decimal("100.00"),
        merchant="Store 1",
        timestamp=now - timedelta(days=2),
        transaction_status=TransactionStatus.COMPLETED,
    )
    t2 = Transaction(
        transaction_id="TXN_DASH_2",
        customer_id=cust.customer_id,
        amount=Decimal("200.00"),
        merchant="Store 2",
        timestamp=now - timedelta(days=1),
        transaction_status=TransactionStatus.APPROVED,
    )
    db_session.add_all([t1, t2])

    # 3. Installments
    # Paid installment ($50) -> excluded
    i_paid = Installment(
        installment_id="INST_D_PAID",
        customer_id=cust.customer_id,
        amount=Decimal("50.00"),
        due_date=now - timedelta(days=10),
        payment_status=PaymentStatus.PAID,
        paid_at=now - timedelta(days=11),
    )
    # Overdue installment ($75)
    i_overdue = Installment(
        installment_id="INST_D_OVERDUE",
        customer_id=cust.customer_id,
        amount=Decimal("75.00"),
        due_date=now - timedelta(days=3),
        payment_status=PaymentStatus.OVERDUE,
    )
    # Upcoming installment due in 4 days ($125)
    i_next7 = Installment(
        installment_id="INST_D_NEXT7",
        customer_id=cust.customer_id,
        amount=Decimal("125.00"),
        due_date=now + timedelta(days=4),
        payment_status=PaymentStatus.PENDING,
    )
    db_session.add_all([i_paid, i_overdue, i_next7])

    # 4. Assessment
    assessment = RiskAssessment(
        assessment_id="RSK_DASH_1",
        customer_id=cust.customer_id,
        risk_score=15,
        risk_level=RiskLevel.LOW,
        risk_reasons={"note": "clean"},
        recommended_action=RecommendedAction.CONTINUE,
        created_at=now,
    )
    db_session.add(assessment)
    db_session.commit()

    # Call dashboard endpoint
    response = await client.get("/api/dashboard")
    assert response.status_code == 200

    data = response.json()
    assert data["total_customers"] == 1
    assert data["total_transactions"] == 2
    assert data["total_assessments"] == 1
    assert data["low_risk_assessments"] == 1
    assert data["medium_risk_assessments"] == 0
    assert data["high_risk_assessments"] == 0

    # Total outstanding = 75 (overdue) + 125 (next 7d) = 200.00
    assert Decimal(str(data["total_outstanding_exposure"])) == Decimal("200.00")
    # Total overdue = 75.00
    assert Decimal(str(data["total_overdue_exposure"])) == Decimal("75.00")
    # Total due next 7d = 125.00
    assert Decimal(str(data["total_due_next_7d_exposure"])) == Decimal("125.00")


# ===========================================================================
# Endpoint 3: GET /api/risk/{customer_id}
# ===========================================================================

@pytest.mark.asyncio
async def test_get_customer_risk_profile_no_previous_assessment(
    client: httpx.AsyncClient, sample_customer: Customer
):
    """Verify endpoint handles existing customer with no prior assessments gracefully."""
    response = await client.get(f"/api/risk/{sample_customer.customer_id}")
    assert response.status_code == 200

    data = response.json()
    assert data["customer_id"] == sample_customer.customer_id
    assert data["identity_status"] == sample_customer.identity_status.value
    assert data["latest_assessment"] is None
    assert "exposure_summary" in data
    assert "velocity_summary" in data


@pytest.mark.asyncio
async def test_get_customer_risk_profile_with_assessment(
    client: httpx.AsyncClient, sample_customer: Customer
):
    """Verify endpoint returns customer profile with latest risk assessment."""
    # First, evaluate customer via POST
    post_res = await client.post(
        "/api/risk/assess",
        json={
            "customer_id": sample_customer.customer_id,
            "amount": "100.00",
            "merchant": "Gadget World",
        },
    )
    assert post_res.status_code == 201

    # Then retrieve profile via GET
    get_res = await client.get(f"/api/risk/{sample_customer.customer_id}")
    assert get_res.status_code == 200

    data = get_res.json()
    assert data["customer_id"] == sample_customer.customer_id
    assert data["latest_assessment"] is not None
    assert data["latest_assessment"]["risk_score"] == 0
    assert data["latest_assessment"]["recommended_action"] == RecommendedAction.CONTINUE


@pytest.mark.asyncio
async def test_get_customer_risk_profile_not_found(client: httpx.AsyncClient):
    """Verify 404 response when looking up non-existent customer profile."""
    response = await client.get("/api/risk/CUST_NON_EXISTENT")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


# ===========================================================================
# Additional edge-case endpoint tests
# ===========================================================================

@pytest.mark.asyncio
async def test_dashboard_empty_database(client: httpx.AsyncClient):
    """Verify /api/dashboard returns zeros for completely empty database."""
    response = await client.get("/api/dashboard")
    assert response.status_code == 200

    data = response.json()
    assert data["total_customers"] == 0
    assert data["total_transactions"] == 0
    assert data["total_assessments"] == 0
    assert data["low_risk_assessments"] == 0
    assert data["medium_risk_assessments"] == 0
    assert data["high_risk_assessments"] == 0
    assert Decimal(str(data["total_outstanding_exposure"])) == Decimal("0.00")
    assert Decimal(str(data["total_overdue_exposure"])) == Decimal("0.00")
    assert Decimal(str(data["total_due_next_7d_exposure"])) == Decimal("0.00")


@pytest.mark.asyncio
async def test_assess_risk_persists_to_database(client: httpx.AsyncClient, db_session: Session, sample_customer: Customer):
    """Verify risk assessment is persisted and retrievable from the database after POST."""
    payload = {
        "customer_id": sample_customer.customer_id,
        "amount": "200.00",
        "merchant": "Persistence Test Store",
    }

    response = await client.post("/api/risk/assess", json=payload)
    assert response.status_code == 201

    data = response.json()
    assessment_id = data["assessment_id"]

    # Check database directly
    record = db_session.get(RiskAssessment, assessment_id)
    assert record is not None
    assert record.customer_id == sample_customer.customer_id
    assert record.risk_score == data["risk_score"]
    assert record.risk_level.value == data["risk_level"]
    assert record.recommended_action.value == data["recommended_action"]
