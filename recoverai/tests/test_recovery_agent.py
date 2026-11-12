import app.paypal_service as paypal_service_module
from app.recovery_agent import RecoveryAgent


def test_recovery_agent_classification_and_plan():
    agent = RecoveryAgent()

    classification = agent.classify_failure("RC-1001")
    assert classification.category == "PAYMENT_METHOD_FAILURE"
    assert 0.0 <= classification.confidence <= 1.0

    plan = agent.plan_recovery("RC-1001")
    assert plan.strategy
    assert plan.recommended_next_action


def test_recovery_agent_chat_and_history_flow():
    agent = RecoveryAgent()

    response = agent.chat("RC-1002", "I cannot afford the payment right now")
    assert "support" in response.reply.lower() or "review" in response.reply.lower()
    assert response.category == "FINANCIAL_HARDSHIP"

    history = agent.get_history("RC-1002")
    assert history["case_id"] == "RC-1002"
    assert len(history["conversation"]) >= 2


def test_recovery_agent_action_requires_approval(monkeypatch):
    agent = RecoveryAgent()

    def fake_create_demo_order(self, case_id):
        return {
            "order_id": "ORDER_TEST_123",
            "approval_url": "https://sandbox.paypal.com/approve/test",
            "status": "CREATED",
            "recovery_case_id": case_id,
        }

    monkeypatch.setattr(paypal_service_module.PayPalService, "create_demo_order", fake_create_demo_order)

    try:
        agent.execute_action("RC-1001", "create_payment_order", approved=False)
        assert False, "expected PermissionError for unapproved payment action"
    except PermissionError:
        pass

    result = agent.execute_action("RC-1001", "create_payment_order", approved=True)
    assert result["order_id"] == "ORDER_TEST_123"
    assert result["recovery_case_id"] == "RC-1001"
