import os
import time
import uuid
from typing import Any, Dict, Optional

import requests
from dotenv import load_dotenv

load_dotenv()


class PayPalError(RuntimeError):
    """Base error for PayPal-specific issues."""


class InvalidCredentialsError(PayPalError):
    """Raised when the Sandbox credentials are rejected by PayPal."""


class PayPalAPIError(PayPalError):
    """Raised when the PayPal API returns an unexpected response."""


class PayPalService:
    """Service layer for PayPal Sandbox authentication and checkout operations."""

    def __init__(self) -> None:
        self.client_id: Optional[str] = os.getenv("PAYPAL_CLIENT_ID")
        self.client_secret: Optional[str] = os.getenv("PAYPAL_CLIENT_SECRET")
        self.base_url: str = os.getenv("PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com")
        self.timeout_seconds: int = 15
        self.access_token: Optional[str] = None
        self.token_expires_at: float = 0.0
        self.default_amount: float = 5.00

    def is_configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def get_config_summary(self) -> dict:
        return {
            "base_url": self.base_url,
            "client_id_configured": bool(self.client_id),
            "client_secret_configured": bool(self.client_secret),
        }

    def _get_auth_pair(self) -> tuple[str, str]:
        if not self.client_id or not self.client_secret:
            raise InvalidCredentialsError("PayPal credentials are missing. Add them to your environment variables.")
        return self.client_id, self.client_secret

    def _build_headers(self, token: Optional[str] = None, request_id: Optional[str] = None) -> dict:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if request_id:
            headers["PayPal-Request-Id"] = request_id
        return headers

    def get_access_token(self) -> str:
        """Fetch and cache an OAuth 2.0 access token using client credentials."""
        if self.access_token and time.time() < self.token_expires_at - 30:
            return self.access_token

        client_id, client_secret = self._get_auth_pair()
        url = f"{self.base_url}/v1/oauth2/token"

        try:
            response = requests.post(
                url,
                data={"grant_type": "client_credentials"},
                auth=(client_id, client_secret),
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:  # pragma: no cover - simple network wrapper
            raise PayPalAPIError("PayPal authentication request failed because of a network or timeout error.") from exc

        if response.status_code == 401:
            raise InvalidCredentialsError("PayPal Sandbox credentials are invalid or expired.")

        if response.status_code != 200:
            detail = response.text.strip() or "Unknown error"
            raise PayPalAPIError(f"PayPal authentication failed with status {response.status_code}: {detail}")

        payload = response.json()
        token = payload.get("access_token")
        expires_in = payload.get("expires_in", 3600)

        if not token:
            raise PayPalAPIError("PayPal authentication succeeded but no access token was returned.")

        self.access_token = token
        self.token_expires_at = time.time() + int(expires_in)
        return token

    def create_order(
        self,
        recovery_case_id: str,
        amount: float = 5.00,
        description: str = "RecoverAI demo payment",
        return_url: Optional[str] = None,
        cancel_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a demo PayPal order for the specified recovery case."""
        if not recovery_case_id or not recovery_case_id.strip():
            raise ValueError("A valid recovery_case_id is required to create a PayPal order.")

        if amount <= 0:
            raise ValueError("The demo payment amount must be greater than zero.")

        token = self.get_access_token()
        order_reference = f"recoverai-{recovery_case_id}-{uuid.uuid4().hex[:8]}"
        base_return_url = return_url or "http://127.0.0.1:8000/api/payments/return"
        base_cancel_url = cancel_url or "http://127.0.0.1:8000/api/payments/cancel"

        payload = {
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "reference_id": order_reference,
                    "description": description,
                    "custom_id": recovery_case_id,
                    "amount": {
                        "currency_code": "USD",
                        "value": f"{float(amount):.2f}",
                    },
                }
            ],
            "application_context": {
                "brand_name": "PayGuard AI",
                "landing_page": "BILLING",
                "user_action": "PAY_NOW",
                "return_url": base_return_url,
                "cancel_url": base_cancel_url,
            },
        }

        try:
            response = requests.post(
                f"{self.base_url}/v2/checkout/orders",
                headers=self._build_headers(token),
                json=payload,
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:  # pragma: no cover - simple network wrapper
            raise PayPalAPIError("PayPal order creation failed because of a network or timeout error.") from exc

        if response.status_code not in (200, 201):
            detail = response.text.strip() or "Unknown error"
            raise PayPalAPIError(f"PayPal order creation failed with status {response.status_code}: {detail}")

        result = response.json()
        approval_url = next(
            (link["href"] for link in result.get("links", []) if link.get("rel") == "approve"),
            "",
        )

        if not approval_url:
            raise PayPalAPIError("PayPal order was created but no approval URL was returned.")

        return {
            "order_id": result.get("id"),
            "status": result.get("status"),
            "approval_url": approval_url,
            "recovery_case_id": recovery_case_id,
            "reference_id": order_reference,
        }

    def get_order(self, order_id: str) -> Dict[str, Any]:
        """Fetch an existing PayPal order for validation before capture."""
        if not order_id or not order_id.strip():
            raise ValueError("A valid order_id is required.")

        token = self.get_access_token()
        try:
            response = requests.get(
                f"{self.base_url}/v2/checkout/orders/{order_id}",
                headers=self._build_headers(token),
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:  # pragma: no cover - simple network wrapper
            raise PayPalAPIError("PayPal order lookup failed because of a network or timeout error.") from exc

        if response.status_code == 404:
            raise PayPalAPIError("The specified PayPal order could not be found.")
        if response.status_code != 200:
            detail = response.text.strip() or "Unknown error"
            raise PayPalAPIError(f"PayPal order lookup failed with status {response.status_code}: {detail}")

        return response.json()

    def capture_order(self, order_id: str, recovery_case_id: str) -> Dict[str, Any]:
        """Capture a PayPal order only after validation and buyer approval."""
        if not order_id or not order_id.strip():
            raise ValueError("A valid order_id is required to capture a payment.")
        if not recovery_case_id or not recovery_case_id.strip():
            raise ValueError("A valid recovery_case_id is required to capture a payment.")

        order = self.get_order(order_id)
        order_status = order.get("status")

        if order_status == "COMPLETED":
            raise PayPalAPIError("This order was already captured and cannot be captured again.")
        if order_status == "CREATED":
            raise PayPalAPIError("This PayPal order has not been approved by the buyer yet.")

        purchase_units = order.get("purchase_units", [])
        if not purchase_units:
            raise PayPalAPIError("The PayPal order does not contain purchase units for validation.")

        expected_custom_id = purchase_units[0].get("custom_id")
        if expected_custom_id != recovery_case_id:
            raise PayPalAPIError("The PayPal order is not associated with the expected recovery case.")

        request_id = str(uuid.uuid4())
        token = self.get_access_token()

        try:
            response = requests.post(
                f"{self.base_url}/v2/checkout/orders/{order_id}/capture",
                headers=self._build_headers(token, request_id),
                json={},
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:  # pragma: no cover - simple network wrapper
            raise PayPalAPIError("PayPal capture failed because of a network or timeout error.") from exc

        if response.status_code not in (200, 201):
            detail = response.text.strip() or "Unknown error"
            raise PayPalAPIError(f"PayPal capture failed with status {response.status_code}: {detail}")

        payload = response.json()
        capture_status = payload.get("status")
        if capture_status != "COMPLETED":
            raise PayPalAPIError(f"PayPal capture did not complete successfully. Status: {capture_status}")

        capture_details = payload.get("purchase_units", [{}])[0].get("payments", {}).get("captures", [])
        if not capture_details:
            raise PayPalAPIError("PayPal capture response was missing payment capture details.")

        capture = capture_details[0]
        amount = float(capture.get("amount", {}).get("value", 0) or 0)
        currency = capture.get("amount", {}).get("currency_code", "USD")

        return {
            "order_id": order_id,
            "capture_status": capture_status,
            "amount": amount,
            "currency": currency,
            "recovery_status": "completed",
        }

    def create_demo_order(self, recovery_case_id: str) -> Dict[str, Any]:
        """Simple helper that creates the default demo Sandbox order for RecoverAI."""
        return self.create_order(
            recovery_case_id=recovery_case_id,
            amount=self.default_amount,
            description="RecoverAI demo payment",
        )
