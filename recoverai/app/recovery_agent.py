import json
import os
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from app.models import RecoveryClassificationResult, RecoveryChatResponse, RecoveryHistoryEntry, RecoveryPlanResult

try:
    from google import genai
except Exception:  # pragma: no cover - optional dependency path
    genai = None

load_dotenv()


class RecoveryAgent:
    """AI-powered recovery assistant for synthetic overdue payment workflows."""

    def __init__(self) -> None:
        self.name = "RecoverAI Agent"
        self.model_name = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        self.api_key = os.getenv("GEMINI_API_KEY")
        self.client = self._build_client()
        self.case_store: Dict[str, Dict[str, Any]] = {
            "RC-1001": {
                "case_id": "RC-1001",
                "customer_id": "CUST-001",
                "customer_name": "Avery Smith",
                "invoice_id": "INV-2024-001",
                "amount_due": 149.99,
                "currency": "USD",
                "due_date": "2024-10-15T00:00:00",
                "recovery_status": "open",
                "failure_reason": "Card was declined due to insufficient balance.",
                "previous_payment_attempts": ["Card declined", "Retry scheduled"],
                "previous_customer_interactions": ["Customer reported insufficient funds."],
                "payment_status": "failed",
            },
            "RC-1002": {
                "case_id": "RC-1002",
                "customer_id": "CUST-002",
                "customer_name": "Jordan Lee",
                "invoice_id": "INV-2024-002",
                "amount_due": 89.0,
                "currency": "USD",
                "due_date": "2024-10-18T00:00:00",
                "recovery_status": "open",
                "failure_reason": "Customer forgot to pay and requested a reminder.",
                "previous_payment_attempts": ["Reminder sent"],
                "previous_customer_interactions": ["Customer asked for a payment reminder."],
                "payment_status": "pending",
            },
            "RC-1003": {
                "case_id": "RC-1003",
                "customer_id": "CUST-003",
                "customer_name": "Noah Patel",
                "invoice_id": "INV-2024-003",
                "amount_due": 210.5,
                "currency": "USD",
                "due_date": "2024-10-20T00:00:00",
                "recovery_status": "open",
                "failure_reason": "Customer reported a disputed charge and requested review.",
                "previous_payment_attempts": ["Chargeback review initiated"],
                "previous_customer_interactions": ["Customer reported dispute."],
                "payment_status": "disputed",
            },
        }
        self.conversation_history: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self.action_history: Dict[str, List[str]] = defaultdict(list)

    def _build_client(self):
        if not self.api_key or genai is None:
            return None
        try:
            return genai.Client(api_key=self.api_key)
        except Exception:
            return None

    def _get_case(self, case_id: str) -> Dict[str, Any]:
        case = self.case_store.get(case_id)
        if not case:
            raise ValueError(f"Unknown recovery case ID: {case_id}")
        return case

    def analyze_case(self, case_data: Dict[str, Any]) -> Dict[str, Any]:
        """Generate a basic structured summary for a payment recovery case."""
        case_id = case_data.get("case_id")
        case = self._get_case(case_id) if case_id else case_data
        return {
            "case_id": case.get("case_id"),
            "status": "pending_analysis",
            "summary": "Recovery analysis ready for AI-driven classification and planning.",
            "recommended_actions": [
                "Review overdue invoice details",
                "Check payment failure reason",
                "Prepare secure retry or assistance flow",
            ],
        }

    def build_recovery_plan(self, case_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create a structured recovery plan placeholder."""
        if not case_data:
            return None
        case_id = case_data.get("case_id")
        if case_id:
            case = self._get_case(case_id)
            case_data = case
        return {
            "case_id": case_data.get("case_id"),
            "strategy": "Send a personalized reminder and offer secure recovery options.",
            "priority": "medium",
            "estimated_recovery_rate": 0.0,
        }

    def _fallback_classification(self, case_data: Dict[str, Any]) -> Dict[str, Any]:
        failure_reason = (case_data.get("failure_reason") or "").lower()
        previous = " ".join(case_data.get("previous_customer_interactions", []) + case_data.get("previous_payment_attempts", [])).lower()

        if any(token in failure_reason or token in previous for token in ["insufficient", "declined", "card", "balance", "bank"]):
            return {
                "category": "PAYMENT_METHOD_FAILURE",
                "confidence": 0.88,
                "explanation": "The payment issue appears to be caused by a declined or unsupported payment method.",
                "recommended_action": "REQUEST_PAYMENT_METHOD_UPDATE",
                "requires_human_review": False,
            }
        if any(token in failure_reason or token in previous for token in ["forgot", "missed", "reminder", "did not pay"]):
            return {
                "category": "FORGOT_PAYMENT",
                "confidence": 0.83,
                "explanation": "The account appears to have missed a payment without an active dispute or fraud signal.",
                "recommended_action": "SEND_FRIENDLY_REMINDER",
                "requires_human_review": False,
            }
        if any(token in failure_reason or token in previous for token in ["lost job", "reduced income", "financial", "hardship", "illness", "expense"]):
            return {
                "category": "FINANCIAL_HARDSHIP",
                "confidence": 0.86,
                "explanation": "The customer appears to be dealing with hardship and may need assistance options rather than a standard collection attempt.",
                "recommended_action": "OFFER_ASSISTANCE",
                "requires_human_review": False,
            }
        if any(token in failure_reason or token in previous for token in ["dispute", "chargeback", "fraud", "billing issue"]):
            return {
                "category": "PAYMENT_DISPUTE",
                "confidence": 0.91,
                "explanation": "The issue may require dispute handling and should not proceed with automated collection while review is ongoing.",
                "recommended_action": "ESCALATE_TO_DISPUTE_REVIEW",
                "requires_human_review": True,
            }
        if any(token in failure_reason or token in previous for token in ["suspicious", "unusual", "fraud", "abnormal"]):
            return {
                "category": "SUSPICIOUS_ACTIVITY",
                "confidence": 0.94,
                "explanation": "The payment issue shows signs of possible suspicious activity and needs human investigation.",
                "recommended_action": "FLAG_FOR_HUMAN_REVIEW",
                "requires_human_review": True,
            }
        return {
            "category": "UNKNOWN",
            "confidence": 0.5,
            "explanation": "There is not enough verified information to classify the issue confidently.",
            "recommended_action": "REQUEST_CLARIFICATION",
            "requires_human_review": True,
        }

    def _extract_json(self, text: str) -> Dict[str, Any]:
        if not text:
            raise ValueError("Gemini returned an empty response.")
        stripped = text.strip()
        if stripped.startswith("```"):
            stripped = stripped.strip("`")
            if "json" in stripped.lower():
                stripped = stripped.split("json", 1)[1].strip()
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start != -1 and end != -1 and start < end:
            stripped = stripped[start : end + 1]
        parsed = json.loads(stripped)
        if not isinstance(parsed, dict):
            raise ValueError("Gemini response was not a JSON object.")
        return parsed

    def _call_gemini(self, prompt: str, fallback: Dict[str, Any]) -> Dict[str, Any]:
        if not self.api_key or self.client is None:
            return fallback
        try:
            response = self.client.models.generate_content(model=self.model_name, contents=prompt)
            text = getattr(response, "text", None)
            if not text:
                return fallback
            payload = self._extract_json(text)
            required_keys = {"category", "confidence", "explanation", "recommended_action", "requires_human_review"}
            if not required_keys.issubset(payload.keys()):
                return fallback
            return payload
        except Exception:
            return fallback

    def classify_failure(self, case_id: str, case_data: Optional[Dict[str, Any]] = None) -> RecoveryClassificationResult:
        """Classify a payment failure using Gemini when available, falling back to safe rules when needed."""
        case = self._get_case(case_id)
        merged = {**case, **(case_data or {})}
        failure_reason = merged.get("failure_reason") or "Unknown"
        prompt = (
            "You are RecoverAI, a safe payment recovery assistant. "
            "Use synthetic data only and do not invent payment reasons. "
            "Classify the issue into one of: PAYMENT_METHOD_FAILURE, FORGOT_PAYMENT, FINANCIAL_HARDSHIP, PAYMENT_DISPUTE, SUSPICIOUS_ACTIVITY, UNKNOWN. "
            "Return valid JSON only with keys: category, confidence, explanation, recommended_action, requires_human_review. "
            f"Case details: {json.dumps(merged, default=str)}\n"
            f"Failure reason: {failure_reason}\n"
            "Explain only what is supported by the provided information; be conservative when facts are missing."
        )
        fallback = self._fallback_classification(merged)
        payload = self._call_gemini(prompt, fallback)
        payload["confidence"] = max(0.0, min(float(payload.get("confidence", 0.5)), 1.0))
        return RecoveryClassificationResult.model_validate(payload)

    def plan_recovery(self, case_id: str, classification: Optional[str] = None) -> RecoveryPlanResult:
        """Generate a recovery strategy from the case classification."""
        case = self._get_case(case_id)
        category = classification or self.classify_failure(case_id, case).category
        if category == "PAYMENT_METHOD_FAILURE":
            result = {
                "strategy": "Offer a secure retry option and ask the customer to confirm or update their payment method.",
                "recommended_next_action": "REQUEST_PAYMENT_METHOD_UPDATE",
                "customer_message": "We can help you update the payment method for a secure retry. Please let us know which option works best for you.",
                "reason": "The issue appears tied to a declined or unavailable payment method.",
                "human_review_required": False,
            }
        elif category == "FORGOT_PAYMENT":
            result = {
                "strategy": "Send a friendly reminder and offer a simple retry path.",
                "recommended_next_action": "SEND_FRIENDLY_REMINDER",
                "customer_message": "We noticed a missed payment. If you would like, we can help you review the outstanding amount and continue securely.",
                "reason": "The case appears to be a missed payment without a fraud or dispute signal.",
                "human_review_required": False,
            }
        elif category == "FINANCIAL_HARDSHIP":
            result = {
                "strategy": "Provide assistance information and route to human support when needed.",
                "recommended_next_action": "OFFER_ASSISTANCE",
                "customer_message": "We understand financial challenges can happen. We can review assistance options and connect you with support if needed.",
                "reason": "The case suggests hardship and may need a more supportive approach than standard collection messaging.",
                "human_review_required": False,
            }
        elif category == "PAYMENT_DISPUTE":
            result = {
                "strategy": "Pause automated collection and escalate to dispute review.",
                "recommended_next_action": "ESCALATE_TO_DISPUTE_REVIEW",
                "customer_message": "We are reviewing the dispute and will not continue automated collection until the matter is cleared.",
                "reason": "The account indicates an open dispute that requires review before further action.",
                "human_review_required": True,
            }
        elif category == "SUSPICIOUS_ACTIVITY":
            result = {
                "strategy": "Flag the account and require human investigation before any further action.",
                "recommended_next_action": "FLAG_FOR_HUMAN_REVIEW",
                "customer_message": "We have flagged this case for additional review to protect your account and maintain security.",
                "reason": "The issue shows characteristics associated with suspicious or potentially fraudulent activity.",
                "human_review_required": True,
            }
        else:
            result = {
                "strategy": "Ask for clarification and avoid any automatic collection step until the issue is understood.",
                "recommended_next_action": "REQUEST_CLARIFICATION",
                "customer_message": "We need a little more information so we can help in the safest way possible.",
                "reason": "The information available is incomplete and a conservative response is required.",
                "human_review_required": True,
            }

        return RecoveryPlanResult.model_validate(result)

    def _format_history(self, case_id: str) -> str:
        messages = self.conversation_history.get(case_id, [])
        if not messages:
            return "No previous messages."
        return "\n".join(f"{item.get('role')}: {item.get('message')}" for item in messages)

    def chat(self, case_id: str, message: str) -> RecoveryChatResponse:
        """Generate a customer-safe response while maintaining per-case conversation context."""
        case = self._get_case(case_id)
        history = self.conversation_history[case_id]
        history.append({"role": "customer", "message": message, "timestamp": datetime.utcnow().isoformat()})

        if not message or not message.strip():
            raise ValueError("Customer message cannot be empty.")

        text = f"Customer message: {message}\nCase: {json.dumps(case, default=str)}\nConversation: {self._format_history(case_id)}"
        prompt = (
            "You are RecoverAI, a safe payment recovery assistant. "
            "Use the customer and case context. Never threaten, shame, or pressure customers. "
            "Never promise a payment will succeed or invent fees or dates. "
            "Return valid JSON only with keys: reply, category, suggested_action, requires_approval. "
            f"{text}"
        )
        fallback = self._fallback_classification(case)
        category = fallback["category"]
        if "card" in message.lower() or "balance" in message.lower() or "insufficient" in message.lower():
            category = "PAYMENT_METHOD_FAILURE"
            suggested_action = "REQUEST_PAYMENT_METHOD_UPDATE"
            requires_approval = False
            reply = "I understand. You can update your payment method or explore the available assistance options."
        elif "job" in message.lower() or "hardship" in message.lower() or "cannot afford" in message.lower():
            category = "FINANCIAL_HARDSHIP"
            suggested_action = "OFFER_ASSISTANCE"
            requires_approval = False
            reply = "I’m sorry you’re dealing with that. We can look at assistance options and connect you with support if needed."
        elif "dispute" in message.lower() or "chargeback" in message.lower():
            category = "PAYMENT_DISPUTE"
            suggested_action = "ESCALATE_TO_DISPUTE_REVIEW"
            requires_approval = False
            reply = "I understand. We will review the dispute before continuing any additional collection steps."
        elif "approve" in message.lower() or "pay now" in message.lower() or "retry payment" in message.lower():
            category = "PAYMENT_METHOD_FAILURE"
            suggested_action = "REQUEST_PAYMENT_METHOD_UPDATE"
            requires_approval = True
            reply = "I can help prepare a secure payment option. Please confirm that you want to continue with the approved payment flow."
        else:
            category = category
            suggested_action = fallback["recommended_action"]
            requires_approval = fallback["requires_human_review"]
            reply = "I understand. Let’s review the payment issue together and keep the next step clear and safe."

        payload = self._call_gemini(prompt, {
            "reply": reply,
            "category": category,
            "suggested_action": suggested_action,
            "requires_approval": requires_approval,
        })

        history.append({
            "role": "assistant",
            "message": payload.get("reply", reply),
            "timestamp": datetime.utcnow().isoformat(),
        })

        result = RecoveryChatResponse(
            reply=payload.get("reply", reply),
            category=payload.get("category", category),
            suggested_action=payload.get("suggested_action", suggested_action),
            requires_approval=bool(payload.get("requires_approval", requires_approval)),
        )
        return result

    def get_payment_status(self, case_id: str) -> Dict[str, Any]:
        case = self._get_case(case_id)
        return {
            "case_id": case_id,
            "status": case.get("payment_status", "pending"),
            "amount": case.get("amount_due", 0),
            "currency": case.get("currency", "USD"),
        }

    def create_recovery_payment(self, case_id: str, amount: float = 5.0, currency: str = "USD", approved: bool = False) -> Dict[str, Any]:
        """Create a PayPal Sandbox order only after explicit customer approval."""
        if not approved:
            raise PermissionError("Customer approval is required before a payment order can be created.")
        self._get_case(case_id)
        from app.paypal_service import PayPalService
        service = PayPalService()
        result = service.create_demo_order(case_id)
        self.action_history[case_id].append(f"created_order:{result.get('order_id')}")
        return result

    def request_human_review(self, case_id: str, reason: str) -> Dict[str, Any]:
        """Create a human review record for an escalated recovery case."""
        self._get_case(case_id)
        review = {
            "case_id": case_id,
            "status": "queued",
            "reason": reason or "Requires human oversight.",
            "created_at": datetime.utcnow().isoformat(),
        }
        self.action_history[case_id].append(f"review:{review['status']}")
        return review

    def get_history(self, case_id: str) -> Dict[str, Any]:
        case = self._get_case(case_id)
        history = [
            RecoveryHistoryEntry(
                role=item.get("role", "customer"),
                message=item.get("message", ""),
                timestamp=datetime.fromisoformat(item.get("timestamp", datetime.utcnow().isoformat())),
            )
            for item in self.conversation_history.get(case_id, [])
        ]
        return {
            "case_id": case["case_id"],
            "conversation": [entry.model_dump(mode="json") for entry in history],
            "actions": self.action_history.get(case_id, []),
        }

    def execute_action(self, case_id: str, action: str, approved: bool = False, **kwargs: Any) -> Dict[str, Any]:
        """Validate allowed tool calls before executing them."""
        self._get_case(case_id)
        if action == "create_payment_order":
            amount = float(kwargs.get("amount", 5.0) or 5.0)
            currency = kwargs.get("currency", "USD") or "USD"
            return self.create_recovery_payment(case_id, amount=amount, currency=currency, approved=approved)
        if action == "request_human_review":
            return self.request_human_review(case_id, kwargs.get("reason", "Manual review required."))
        raise ValueError(f"Unsupported recovery action: {action}")
