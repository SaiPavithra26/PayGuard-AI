"""FastAPI router for PayLater Shield pre-purchase risk assessment endpoints."""

from dataclasses import asdict
from decimal import Decimal
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.customer import Customer
from app.models.risk_assessment import RiskAssessment
from app.schemas.risk import (
    CustomerRiskProfileResponse,
    ExposureSummarySchema,
    RiskAssessmentRequest,
    RiskAssessmentResponse,
    SignalDetailSchema,
    VelocitySummarySchema,
)
from app.services.exposure import ExposureAnalyzer
from app.services.risk_engine import RiskEngine
from app.services.velocity import VelocityAnalyzer

router = APIRouter(prefix="/risk", tags=["Risk Assessment"])

# Singleton services instances
_velocity_analyzer = VelocityAnalyzer()
_exposure_analyzer = ExposureAnalyzer()
_risk_engine = RiskEngine()


@router.post(
    "/assess",
    response_model=RiskAssessmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Assess pre-purchase PayLater risk",
    description=(
        "Evaluates transaction velocity, cumulative credit exposure, identity status, "
        "repayment behavior, and device telemetry to produce a deterministic risk score and recommendation."
    ),
)
def assess_risk(
    payload: RiskAssessmentRequest,
    db: Session = Depends(get_db),
) -> RiskAssessmentResponse:
    """Assess customer risk for a proposed Pay Later purchase."""
    # 1. Confirm customer exists
    customer = db.get(Customer, payload.customer_id)
    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Customer '{payload.customer_id}' not found",
        )

    # 2. Retrieve history and calculate telemetry
    txns = list(customer.transactions)
    insts = list(customer.installments)

    vel_result = _velocity_analyzer.analyze(txns)
    exp_result = _exposure_analyzer.analyze(insts, transactions=txns)

    # 3. Multi-factor risk evaluation
    eval_result = _risk_engine.evaluate(
        customer=customer,
        transactions=txns,
        installments=insts,
        session_device_signal=payload.device_risk_signal,
    )

    # 4. Persist assessment record in database
    assessment_id = f"RSK_{uuid.uuid4().hex[:10].upper()}"
    assessment = RiskAssessment(
        assessment_id=assessment_id,
        customer_id=customer.customer_id,
        risk_score=eval_result.risk_score,
        risk_level=eval_result.risk_level,
        risk_reasons=eval_result.to_audit_dict(),
        recommended_action=eval_result.recommended_action,
        created_at=eval_result.evaluated_at,
    )
    db.add(assessment)
    db.commit()
    db.refresh(assessment)

    # 5. Build structured response
    velocity_summary = VelocitySummarySchema(
        tx_count_1h=vel_result.tx_count_1h,
        tx_count_24h=vel_result.tx_count_24h,
        tx_amount_24h=vel_result.tx_amount_24h,
        tx_count_7d=vel_result.tx_count_7d,
        is_burst_pattern=vel_result.is_burst_pattern,
        is_velocity_elevated=vel_result.is_velocity_elevated,
        signals_triggered=vel_result.signals_triggered,
    )

    exposure_summary = ExposureSummarySchema(
        total_outstanding_amount=exp_result.total_outstanding_amount,
        total_overdue_amount=exp_result.total_overdue_amount,
        due_next_7d_amount=exp_result.due_next_7d_amount,
        active_installment_count=exp_result.active_installment_count,
        overdue_installment_count=exp_result.overdue_installment_count,
        failed_repayments_count=exp_result.failed_repayments_count,
        is_exposure_elevated=exp_result.is_exposure_elevated,
    )

    signals_dict = {
        name: SignalDetailSchema(
            signal_name=sig.signal_name,
            weight=sig.weight,
            score=sig.score,
            triggered=sig.triggered,
            explanation=sig.explanation,
            metrics=sig.metrics,
        )
        for name, sig in eval_result.signals.items()
    }

    return RiskAssessmentResponse(
        assessment_id=assessment.assessment_id,
        customer_id=customer.customer_id,
        proposed_amount=payload.amount,
        merchant=payload.merchant,
        risk_score=eval_result.risk_score,
        risk_level=eval_result.risk_level,
        recommended_action=eval_result.recommended_action,
        reasons=eval_result.reasons,
        evaluated_at=eval_result.evaluated_at,
        signals=signals_dict,
        velocity_summary=velocity_summary,
        exposure_summary=exposure_summary,
    )


@router.get(
    "/{customer_id}",
    response_model=CustomerRiskProfileResponse,
    summary="Get customer risk profile and latest assessment",
    description="Returns customer identity information, live exposure metrics, and the most recent risk evaluation.",
)
def get_customer_risk_profile(
    customer_id: str,
    db: Session = Depends(get_db),
) -> CustomerRiskProfileResponse:
    """Retrieve the latest risk assessment and live exposure summary for a customer."""
    # 1. Lookup customer
    customer = db.get(Customer, customer_id)
    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Customer '{customer_id}' not found",
        )

    # 2. Live velocity and exposure metrics
    txns = list(customer.transactions)
    insts = list(customer.installments)

    vel_result = _velocity_analyzer.analyze(txns)
    exp_result = _exposure_analyzer.analyze(insts, transactions=txns)

    velocity_summary = VelocitySummarySchema(
        tx_count_1h=vel_result.tx_count_1h,
        tx_count_24h=vel_result.tx_count_24h,
        tx_amount_24h=vel_result.tx_amount_24h,
        tx_count_7d=vel_result.tx_count_7d,
        is_burst_pattern=vel_result.is_burst_pattern,
        is_velocity_elevated=vel_result.is_velocity_elevated,
        signals_triggered=vel_result.signals_triggered,
    )

    exposure_summary = ExposureSummarySchema(
        total_outstanding_amount=exp_result.total_outstanding_amount,
        total_overdue_amount=exp_result.total_overdue_amount,
        due_next_7d_amount=exp_result.due_next_7d_amount,
        active_installment_count=exp_result.active_installment_count,
        overdue_installment_count=exp_result.overdue_installment_count,
        failed_repayments_count=exp_result.failed_repayments_count,
        is_exposure_elevated=exp_result.is_exposure_elevated,
    )

    # 3. Retrieve latest recorded risk assessment
    latest_assessment_orm = db.scalars(
        select(RiskAssessment)
        .where(RiskAssessment.customer_id == customer_id)
        .order_by(RiskAssessment.created_at.desc())
        .limit(1)
    ).first()

    latest_assessment_dto: Optional[RiskAssessmentResponse] = None
    if latest_assessment_orm:
        raw_reasons = latest_assessment_orm.risk_reasons or {}
        signals_raw = raw_reasons.get("signals", {})
        signals_dto = {
            k: SignalDetailSchema(**v) for k, v in signals_raw.items()
        } if signals_raw else {}

        latest_assessment_dto = RiskAssessmentResponse(
            assessment_id=latest_assessment_orm.assessment_id,
            customer_id=customer_id,
            proposed_amount=Decimal("0.00"),
            merchant="Previous Assessment",
            risk_score=latest_assessment_orm.risk_score,
            risk_level=latest_assessment_orm.risk_level,
            recommended_action=latest_assessment_orm.recommended_action,
            reasons=raw_reasons.get("reasons", []),
            evaluated_at=latest_assessment_orm.created_at,
            signals=signals_dto,
            velocity_summary=velocity_summary,
            exposure_summary=exposure_summary,
        )

    return CustomerRiskProfileResponse(
        customer_id=customer.customer_id,
        identity_status=customer.identity_status,
        device_risk_signal=customer.device_risk_signal,
        account_created_at=customer.account_created_at,
        latest_assessment=latest_assessment_dto,
        exposure_summary=exposure_summary,
        velocity_summary=velocity_summary,
    )


