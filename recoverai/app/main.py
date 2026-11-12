from typing import Literal

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field

from app.models import (
    PaymentStatus,
    RecoveryActionRequest,
    RecoveryCase,
    RecoveryChatRequest,
    RecoveryChatResponse,
    RecoveryClassificationResult,
    RecoveryHistoryResponse,
    RecoveryPlan,
    RecoveryPlanResult,
)
from app.paypal_service import (  # type: ignore
    InvalidCredentialsError,
    PayPalAPIError,
    PayPalService,
)
from app.recovery_agent import RecoveryAgent

app = FastAPI(
    title="RecoverAI",
    description="PayGuard AI recovery backend for overdue payment workflows.",
    version="0.3.0",
)

paypal_service = PayPalService()
recovery_agent = RecoveryAgent()


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str = "RecoverAI"


class RecoveryStatusResponse(BaseModel):
    module: str = "RecoverAI"
    status: Literal["ready"] = "ready"
    paypal_configured: bool = Field(default=False, example=False)


class CreateOrderRequest(BaseModel):
    recovery_case_id: str = Field(..., min_length=1, example="RC-1001")


class CreateOrderResponse(BaseModel):
    order_id: str = Field(..., example="PAYPAL_ORDER_123")
    approval_url: str = Field(..., example="https://www.sandbox.paypal.com/checkoutnow?token=123")
    status: str = Field(..., example="CREATED")
    recovery_case_id: str = Field(..., example="RC-1001")


class CaptureOrderRequest(BaseModel):
    order_id: str = Field(..., min_length=1, example="PAYPAL_ORDER_123")
    recovery_case_id: str = Field(..., min_length=1, example="RC-1001")


class CaptureOrderResponse(BaseModel):
    order_id: str = Field(..., example="PAYPAL_ORDER_123")
    capture_status: str = Field(..., example="COMPLETED")
    amount: float = Field(..., gt=0, example=5.0)
    currency: str = Field(..., example="USD")
    recovery_status: Literal["completed", "failed", "pending"] = "completed"


class PayPalHealthResponse(BaseModel):
    status: Literal["ok", "error"] = "ok"
    message: str = "Sandbox authentication is working."


class RecoveryClassificationRequest(BaseModel):
    overdue_amount: float = Field(..., gt=0, example=149.99)
    due_date: str = Field(..., example="2024-10-15T00:00:00")
    payment_failure_reason: str = Field(..., example="Card declined")
    previous_payment_attempts: list[str] = Field(default_factory=list)
    previous_customer_interactions: list[str] = Field(default_factory=list)


class RecoveryPlanRequest(BaseModel):
    classification: str = Field(..., example="PAYMENT_METHOD_FAILURE")
    notes: str = Field(default="", example="Customer asked to retry with a different method.")


@app.get("/", summary="Welcome message")
def read_root() -> dict:
    return {
        "message": "Welcome to RecoverAI",
        "description": "AI-powered payment recovery backend for PayGuard AI.",
    }


@app.get("/health", response_model=HealthResponse, summary="Health check")
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="RecoverAI")


@app.get("/api/recovery/status", response_model=RecoveryStatusResponse, summary="Module status")
def recovery_status() -> RecoveryStatusResponse:
    return RecoveryStatusResponse(
        module="RecoverAI",
        status="ready",
        paypal_configured=paypal_service.is_configured(),
    )


@app.get("/api/recovery/example-case", response_model=RecoveryCase, summary="Example case")
def example_case() -> RecoveryCase:
    return RecoveryCase(
        case_id="RC-1001",
        customer_id="CUST-001",
        customer_name="Avery Smith",
        invoice_id="INV-2024-001",
        amount_due=149.99,
        currency="USD",
        due_date="2024-10-15T00:00:00",
        recovery_status="open",
        failure_reason="Card expired",
        previous_payment_attempts=["Card declined", "Retry scheduled"],
        previous_customer_interactions=["Customer reported insufficient funds."],
        payment_status="failed",
    )


@app.get("/api/recovery/example-plan", response_model=RecoveryPlan, summary="Example recovery plan")
def example_plan() -> RecoveryPlan:
    return RecoveryPlan(
        plan_id="PLAN-001",
        case_id="RC-1001",
        strategy="Send a friendly reminder and offer a secure retry option.",
        priority="high",
        estimated_recovery_rate=78.5,
        next_action="Prepare a retry email and review payment failure details.",
    )


@app.get("/api/recovery/example-payment-status", response_model=PaymentStatus, summary="Example payment status")
def example_payment_status() -> PaymentStatus:
    return PaymentStatus(
        payment_id="PAY-12345",
        status="failed",
        amount=149.99,
        currency="USD",
    )


@app.get("/api/recovery/agent", summary="Recovery agent placeholder")
def recovery_agent_endpoint() -> dict:
    return recovery_agent.analyze_case({"case_id": "RC-1001", "customer_id": "CUST-001"})


@app.get("/api/paypal/health", response_model=PayPalHealthResponse, summary="PayPal Sandbox auth health check")
def paypal_health() -> PayPalHealthResponse:
    try:
        paypal_service.get_access_token()
        return PayPalHealthResponse(status="ok", message="Sandbox authentication is working.")
    except InvalidCredentialsError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except PayPalAPIError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@app.post("/api/payments/create-order", response_model=CreateOrderResponse, summary="Create a demo PayPal Sandbox order")
def create_order(payload: CreateOrderRequest) -> CreateOrderResponse:
    try:
        result = paypal_service.create_demo_order(payload.recovery_case_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except InvalidCredentialsError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except PayPalAPIError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    return CreateOrderResponse(
        order_id=result["order_id"],
        approval_url=result["approval_url"],
        status=result["status"],
        recovery_case_id=result["recovery_case_id"],
    )


@app.post("/api/payments/capture-order", response_model=CaptureOrderResponse, summary="Capture a PayPal order after buyer approval")
def capture_order(payload: CaptureOrderRequest) -> CaptureOrderResponse:
    try:
        result = paypal_service.capture_order(payload.order_id, payload.recovery_case_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except InvalidCredentialsError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except PayPalAPIError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return CaptureOrderResponse(
        order_id=result["order_id"],
        capture_status=result["capture_status"],
        amount=result["amount"],
        currency=result["currency"],
        recovery_status=result["recovery_status"],
    )


@app.post("/api/recovery/{case_id}/classify", response_model=RecoveryClassificationResult, summary="Classify a payment failure")
def classify_case(case_id: str, payload: RecoveryClassificationRequest) -> RecoveryClassificationResult:
    try:
        result = recovery_agent.classify_failure(
            case_id,
            {
                "case_id": case_id,
                "amount_due": payload.overdue_amount,
                "due_date": payload.due_date,
                "failure_reason": payload.payment_failure_reason,
                "previous_payment_attempts": payload.previous_payment_attempts,
                "previous_customer_interactions": payload.previous_customer_interactions,
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return result


@app.post("/api/recovery/{case_id}/plan", response_model=RecoveryPlanResult, summary="Generate a recovery strategy")
def plan_case(case_id: str, payload: RecoveryPlanRequest) -> RecoveryPlanResult:
    try:
        result = recovery_agent.plan_recovery(case_id, payload.classification)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return result


@app.post("/api/recovery/{case_id}/chat", response_model=RecoveryChatResponse, summary="Chat with the RecoverAI assistant")
def chat_case(case_id: str, payload: RecoveryChatRequest) -> RecoveryChatResponse:
    try:
        return recovery_agent.chat(case_id, payload.message)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@app.post("/api/recovery/{case_id}/action", summary="Validate and execute an explicitly approved recovery action")
def execute_recovery_action(case_id: str, payload: RecoveryActionRequest) -> dict:
    try:
        result = recovery_agent.execute_action(
            case_id,
            payload.action,
            approved=payload.approved,
            amount=payload.amount,
            currency=payload.currency,
            reason=payload.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return {"status": "ok", "result": result}


@app.get("/api/recovery/{case_id}/history", response_model=RecoveryHistoryResponse, summary="Return a case conversation and action history")
def get_case_history(case_id: str) -> RecoveryHistoryResponse:
    try:
        result = recovery_agent.get_history(case_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return RecoveryHistoryResponse(**result)


@app.get("/api/payments/return", summary="PayPal return URL")
def paypal_return() -> dict:
    return {
        "status": "approved",
        "message": "The buyer returned from PayPal. The backend should verify and capture the order before finalizing payment.",
    }


@app.get("/api/payments/cancel", summary="PayPal cancel URL")
def paypal_cancel() -> dict:
    return {
        "status": "cancelled",
        "message": "The payment was cancelled by the buyer before approval.",
    }
