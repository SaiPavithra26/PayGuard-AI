import pytest
import requests

from app.paypal_service import InvalidCredentialsError, PayPalAPIError, PayPalService


class DummyResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text or ""

    def json(self):
        return self._payload


def test_successful_oauth_token_generation(monkeypatch):
    service = PayPalService()
    service.client_id = "demo_client_id"
    service.client_secret = "demo_client_secret"

    def fake_post(url, data=None, auth=None, timeout=None):
        assert url.endswith("/v1/oauth2/token")
        assert data == {"grant_type": "client_credentials"}
        assert auth == ("demo_client_id", "demo_client_secret")
        return DummyResponse(200, {"access_token": "demo_token", "expires_in": 3600})

    monkeypatch.setattr(requests, "post", fake_post)

    token = service.get_access_token()

    assert token == "demo_token"
    assert service.access_token == "demo_token"


def test_invalid_sandbox_credentials(monkeypatch):
    service = PayPalService()
    service.client_id = "bad_client"
    service.client_secret = "bad_secret"

    def fake_post(url, data=None, auth=None, timeout=None):
        return DummyResponse(401, {"error": "invalid_client"}, "invalid_client")

    monkeypatch.setattr(requests, "post", fake_post)

    with pytest.raises(InvalidCredentialsError):
        service.get_access_token()


def test_successful_order_creation(monkeypatch):
    service = PayPalService()
    service.client_id = "demo_client_id"
    service.client_secret = "demo_client_secret"
    service.access_token = "demo_token"
    service.token_expires_at = 9999999999

    def fake_post(url, headers=None, json=None, timeout=None):
        assert url.endswith("/v2/checkout/orders")
        assert headers["Authorization"] == "Bearer demo_token"
        assert json["intent"] == "CAPTURE"
        assert json["purchase_units"][0]["amount"]["value"] == "5.00"
        return DummyResponse(
            201,
            {
                "id": "ORDER_123",
                "status": "CREATED",
                "links": [{"rel": "approve", "href": "https://sandbox.paypal.com/approve/123"}],
            },
        )

    monkeypatch.setattr(requests, "post", fake_post)

    result = service.create_order("RC-1001")

    assert result["order_id"] == "ORDER_123"
    assert result["status"] == "CREATED"
    assert "sandbox.paypal.com/approve" in result["approval_url"]


def test_missing_or_invalid_recovery_case():
    service = PayPalService()

    with pytest.raises(ValueError):
        service.create_order("   ")


def test_capture_before_buyer_approval(monkeypatch):
    service = PayPalService()
    service.client_id = "demo_client_id"
    service.client_secret = "demo_client_secret"
    monkeypatch.setattr(service, "get_access_token", lambda: "demo_token")

    def fake_get(url, headers=None, timeout=None):
        assert url.endswith("/v2/checkout/orders/ORDER_123")
        return DummyResponse(
            200,
            {"id": "ORDER_123", "status": "CREATED", "purchase_units": [{"custom_id": "RC-1001"}]},
        )

    monkeypatch.setattr(requests, "get", fake_get)

    with pytest.raises(PayPalAPIError, match="not been approved"):
        service.capture_order("ORDER_123", "RC-1001")


def test_successful_capture_after_approval(monkeypatch):
    service = PayPalService()
    monkeypatch.setattr(service, "get_access_token", lambda: "demo_token")

    def fake_get(url, headers=None, timeout=None):
        return DummyResponse(
            200,
            {"id": "ORDER_123", "status": "APPROVED", "purchase_units": [{"custom_id": "RC-1001"}]},
        )

    def fake_post(url, headers=None, json=None, timeout=None):
        assert url.endswith("/ORDER_123/capture")
        assert headers["PayPal-Request-Id"]
        assert headers["Authorization"] == "Bearer demo_token"
        return DummyResponse(
            201,
            {
                "status": "COMPLETED",
                "purchase_units": [
                    {"payments": {"captures": [{"amount": {"currency_code": "USD", "value": "5.00"}}]}}
                ],
            },
        )

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(requests, "post", fake_post)

    result = service.capture_order("ORDER_123", "RC-1001")

    assert result["capture_status"] == "COMPLETED"
    assert result["amount"] == 5.0
    assert result["currency"] == "USD"


def test_duplicate_capture_attempt(monkeypatch):
    service = PayPalService()
    monkeypatch.setattr(service, "get_access_token", lambda: "demo_token")

    def fake_get(url, headers=None, timeout=None):
        return DummyResponse(
            200,
            {"id": "ORDER_123", "status": "COMPLETED", "purchase_units": [{"custom_id": "RC-1001"}]},
        )

    monkeypatch.setattr(requests, "get", fake_get)

    with pytest.raises(PayPalAPIError, match="already captured"):
        service.capture_order("ORDER_123", "RC-1001")


def test_paypal_network_failure(monkeypatch):
    service = PayPalService()
    service.client_id = "demo_client_id"
    service.client_secret = "demo_client_secret"
    service.access_token = "demo_token"
    service.token_expires_at = 9999999999

    def fake_post(url, headers=None, json=None, timeout=None):
        raise requests.exceptions.RequestException("temporary network issue")

    monkeypatch.setattr(requests, "post", fake_post)

    with pytest.raises(PayPalAPIError, match="network|timeout"):
        service.create_order("RC-1001")
