"""
Tests — Day 16: Microservices
===============================
Test strategy:
  1. ServiceClient — request/response simulation
  2. ServiceRegistry — service discovery
  3. AccountService — all routes
  4. TransactionService — transfer, deposit, withdrawal
  5. Inter-service communication — TransactionService calls AccountService
  6. Data isolation — each service owns its data
  7. Fault scenarios — service unavailable, insufficient funds
  8. Rollback — partial failure reversal
"""

import sys
import pytest

sys.path.insert(0, "src")

from bankcore.config_manager import ConfigManager
from bankcore.account_factory import AccountFactory
from bankcore.alert_system import AlertSystem
from bankcore.account_type_registry import AccountTypeRegistry
from bankcore.services.shared.service_client import (
    ServiceClient, ServiceRegistry, ServiceRequest, ServiceResponse,
)
from bankcore.services.account_service.service import AccountService
from bankcore.services.transaction_service.service import TransactionMicroservice
from bankcore.protocols import FakeConfig


@pytest.fixture(autouse=True)
def reset_state():
    ConfigManager._reset()
    AlertSystem._reset()
    AccountTypeRegistry._reset()
    AccountTypeRegistry._register_defaults()
    AccountFactory._reset_registry()
    yield
    ConfigManager._reset()
    AlertSystem._reset()
    AccountTypeRegistry._reset()
    AccountTypeRegistry._register_defaults()
    AccountFactory._reset_registry()


@pytest.fixture
def account_svc():
    return AccountService()


@pytest.fixture
def registry(account_svc):
    reg = ServiceRegistry()
    reg.register("account-service", account_svc.handle)
    return reg


@pytest.fixture
def tx_svc(registry):
    client = registry.get("account-service")
    return TransactionMicroservice(client)


@pytest.fixture
def alice_id(account_svc):
    resp = account_svc.handle(ServiceRequest(
        "POST", "/accounts",
        body={"owner_name": "Alice", "account_type": "current", "initial_deposit": 2_000.0}
    ))
    return resp.body["account_id"]


@pytest.fixture
def bob_id(account_svc):
    resp = account_svc.handle(ServiceRequest(
        "POST", "/accounts",
        body={"owner_name": "Bob", "account_type": "savings", "initial_deposit": 1_000.0}
    ))
    return resp.body["account_id"]


# ---------------------------------------------------------------------------
# ServiceClient
# ---------------------------------------------------------------------------

class TestServiceClient:

    def test_get_calls_handler(self):
        def handler(req): return ServiceResponse(200, {"ok": True})
        client   = ServiceClient("test-service", handler)
        response = client.get("/test")
        assert response.status_code == 200
        assert response.body["ok"] is True

    def test_post_passes_body(self):
        received_body = {}
        def handler(req):
            received_body.update(req.body)
            return ServiceResponse(201, {"created": True})
        client = ServiceClient("test-service", handler)
        client.post("/items", {"name": "widget", "value": 42})
        assert received_body["name"] == "widget"

    def test_call_count_increments(self):
        def handler(req): return ServiceResponse(200, {})
        client = ServiceClient("test-service", handler)
        client.get("/a")
        client.get("/b")
        client.post("/c", {})
        assert client.call_count == 3

    def test_call_log_records_details(self):
        def handler(req): return ServiceResponse(200, {})
        client = ServiceClient("test-service", handler)
        client.get("/accounts")
        log = client.get_call_log()
        assert len(log) == 1
        assert log[0]["method"] == "GET"
        assert log[0]["path"] == "/accounts"
        assert log[0]["status"] == 200

    def test_latency_is_recorded(self):
        def handler(req): return ServiceResponse(200, {})
        client = ServiceClient("test-service", handler)
        client.get("/test")
        log = client.get_call_log()
        assert log[0]["latency_ms"] >= 0

    def test_ok_property(self):
        assert ServiceResponse(200, {}).ok is True
        assert ServiceResponse(201, {}).ok is True
        assert ServiceResponse(400, {}).ok is False
        assert ServiceResponse(404, {}).ok is False
        assert ServiceResponse(500, {}).ok is False

    def test_reset_stats(self):
        def handler(req): return ServiceResponse(200, {})
        client = ServiceClient("test-service", handler)
        client.get("/a")
        client.get("/b")
        client.reset_stats()
        assert client.call_count == 0
        assert client.get_call_log() == []

    def test_call_is_auto_traced(self):
        """Day 20: every _call() opens a real Span on the client's Tracer."""
        def handler(req): return ServiceResponse(200, {"ok": True})
        client = ServiceClient("test-service", handler)
        client.get("/accounts/ACC-001")

        traces = client.tracer.all_traces()
        assert len(traces) == 1
        span = traces[0].root_span
        assert span.operation == "GET test-service/accounts/ACC-001"
        assert span.tags["http.status"] == 200
        assert span.error is False
        assert span.is_finished is True

    def test_failed_call_marks_span_as_error(self):
        def handler(req): return ServiceResponse(503, {"error": "unavailable"})
        client = ServiceClient("test-service", handler)
        client.get("/accounts/ACC-001")

        span = client.tracer.all_traces()[0].root_span
        assert span.error is True


# ---------------------------------------------------------------------------
# ServiceRegistry
# ---------------------------------------------------------------------------

class TestServiceRegistry:

    def test_register_and_get(self):
        reg = ServiceRegistry()
        def handler(req): return ServiceResponse(200, {})
        reg.register("my-service", handler)
        client = reg.get("my-service")
        assert client.service_name == "my-service"

    def test_get_unknown_raises(self):
        reg = ServiceRegistry()
        with pytest.raises(KeyError, match="not registered"):
            reg.get("nonexistent")

    def test_is_registered(self):
        reg = ServiceRegistry()
        def handler(req): return ServiceResponse(200, {})
        assert reg.is_registered("svc") is False
        reg.register("svc", handler)
        assert reg.is_registered("svc") is True

    def test_registered_services_list(self):
        reg = ServiceRegistry()
        def handler(req): return ServiceResponse(200, {})
        reg.register("svc-a", handler)
        reg.register("svc-b", handler)
        assert "svc-a" in reg.registered_services()
        assert "svc-b" in reg.registered_services()

    def test_total_calls(self):
        reg = ServiceRegistry()
        def handler(req): return ServiceResponse(200, {})
        c1 = reg.register("svc-a", handler)
        c2 = reg.register("svc-b", handler)
        c1.get("/a")
        c2.get("/b")
        c2.get("/c")
        assert reg.total_calls() == 3


# ---------------------------------------------------------------------------
# AccountService — all routes
# ---------------------------------------------------------------------------

class TestAccountService:

    def test_create_account_returns_201(self, account_svc):
        resp = account_svc.handle(ServiceRequest(
            "POST", "/accounts",
            body={"owner_name": "Alice", "account_type": "current", "initial_deposit": 500.0}
        ))
        assert resp.status_code == 201
        assert "account_id" in resp.body

    def test_get_account_returns_200(self, account_svc, alice_id):
        resp = account_svc.handle(ServiceRequest("GET", f"/accounts/{alice_id}"))
        assert resp.status_code == 200
        assert resp.body["owner_name"] == "Alice"
        assert resp.body["balance"] == 2_000.0

    def test_get_account_includes_min_possible_balance(self, account_svc, alice_id):
        resp = account_svc.handle(ServiceRequest("GET", f"/accounts/{alice_id}"))
        assert "min_possible_balance" in resp.body

    def test_get_unknown_returns_404(self, account_svc):
        resp = account_svc.handle(ServiceRequest("GET", "/accounts/GHOST"))
        assert resp.status_code == 404
        assert resp.body["code"] == "ACCOUNT_NOT_FOUND"

    def test_list_accounts_returns_200(self, account_svc, alice_id, bob_id):
        resp = account_svc.handle(ServiceRequest("GET", "/accounts"))
        assert resp.status_code == 200
        assert resp.body["count"] == 2

    def test_list_accounts_filter_by_type(self, account_svc, alice_id, bob_id):
        resp = account_svc.handle(ServiceRequest(
            "GET", "/accounts", params={"type": "savings"}
        ))
        assert resp.body["count"] == 1
        assert resp.body["accounts"][0]["account_type"] == "savings"

    def test_update_balance(self, account_svc, alice_id):
        resp = account_svc.handle(ServiceRequest(
            "PATCH", f"/accounts/{alice_id}/balance",
            body={"balance": 1_500.0}
        ))
        assert resp.status_code == 200
        assert resp.body["balance"] == 1_500.0

    def test_update_balance_below_minimum_fails(self, account_svc, alice_id):
        resp = account_svc.handle(ServiceRequest(
            "PATCH", f"/accounts/{alice_id}/balance",
            body={"balance": -500.0}   # below min_possible_balance=0 for current
        ))
        assert resp.status_code == 422
        assert resp.body["code"] == "BALANCE_BELOW_MINIMUM"

    def test_create_invalid_type_returns_422(self, account_svc):
        resp = account_svc.handle(ServiceRequest(
            "POST", "/accounts",
            body={"owner_name": "Alice", "account_type": "crypto"}
        ))
        assert resp.status_code == 422

    def test_unknown_route_returns_404(self, account_svc):
        resp = account_svc.handle(ServiceRequest("GET", "/nonexistent"))
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# TransactionService
# ---------------------------------------------------------------------------

class TestTransactionMicroservice:

    def test_deposit_succeeds(self, tx_svc, alice_id):
        resp = tx_svc.handle(ServiceRequest(
            "POST", "/deposits",
            body={"account_id": alice_id, "amount": 500.0}
        ))
        assert resp.status_code == 200
        assert resp.body["success"] is True
        assert resp.body["balance_after"] == 2_500.0

    def test_deposit_records_transaction(self, tx_svc, alice_id):
        tx_svc.handle(ServiceRequest(
            "POST", "/deposits",
            body={"account_id": alice_id, "amount": 300.0}
        ))
        assert tx_svc.transaction_log.count() == 1

    def test_withdrawal_succeeds(self, tx_svc, alice_id):
        resp = tx_svc.handle(ServiceRequest(
            "POST", "/withdrawals",
            body={"account_id": alice_id, "amount": 500.0}
        ))
        assert resp.status_code == 200
        assert resp.body["balance_after"] == 1_500.0

    def test_withdrawal_insufficient_funds(self, tx_svc, alice_id):
        resp = tx_svc.handle(ServiceRequest(
            "POST", "/withdrawals",
            body={"account_id": alice_id, "amount": 99_999.0}
        ))
        assert resp.status_code == 422
        assert resp.body["code"] == "INSUFFICIENT_FUNDS"

    def test_withdrawal_does_not_record_failed_tx(self, tx_svc, alice_id):
        tx_svc.handle(ServiceRequest(
            "POST", "/withdrawals",
            body={"account_id": alice_id, "amount": 99_999.0}
        ))
        assert tx_svc.transaction_log.count() == 0

    def test_get_transaction(self, tx_svc, alice_id):
        resp = tx_svc.handle(ServiceRequest(
            "POST", "/deposits",
            body={"account_id": alice_id, "amount": 100.0}
        ))
        tx_id = resp.body["tx_id"]
        get_resp = tx_svc.handle(ServiceRequest("GET", f"/transactions/{tx_id}"))
        assert get_resp.status_code == 200
        assert get_resp.body["tx_id"] == tx_id

    def test_list_transactions_by_account(self, tx_svc, alice_id):
        tx_svc.handle(ServiceRequest("POST", "/deposits",
            body={"account_id": alice_id, "amount": 100.0}))
        tx_svc.handle(ServiceRequest("POST", "/deposits",
            body={"account_id": alice_id, "amount": 200.0}))
        resp = tx_svc.handle(ServiceRequest(
            "GET", "/transactions", params={"account_id": alice_id}
        ))
        assert resp.body["count"] == 2


# ---------------------------------------------------------------------------
# Inter-service communication
# ---------------------------------------------------------------------------

class TestInterServiceCommunication:

    def test_transfer_calls_account_service(self, tx_svc, alice_id, bob_id):
        """TransactionService calls AccountService for account data."""
        calls_before = tx_svc.account_client.call_count
        tx_svc.handle(ServiceRequest(
            "POST", "/transfers",
            body={"from_account_id": alice_id, "to_account_id": bob_id, "amount": 500.0}
        ))
        calls_after = tx_svc.account_client.call_count
        # Should have called: GET alice, GET bob, PATCH alice, PATCH bob = 4 calls
        assert calls_after - calls_before == 4

    def test_successful_transfer(self, tx_svc, account_svc, alice_id, bob_id):
        resp = tx_svc.handle(ServiceRequest(
            "POST", "/transfers",
            body={"from_account_id": alice_id, "to_account_id": bob_id, "amount": 600.0}
        ))
        assert resp.status_code == 200
        assert resp.body["success"] is True
        assert resp.body["from_balance_after"] == 1_400.0
        assert resp.body["to_balance_after"]   == 1_600.0

    def test_transfer_updates_account_service_balances(
        self, tx_svc, account_svc, alice_id, bob_id
    ):
        """AccountService reflects the balance change after transfer."""
        tx_svc.handle(ServiceRequest(
            "POST", "/transfers",
            body={"from_account_id": alice_id, "to_account_id": bob_id, "amount": 300.0}
        ))
        alice_resp = account_svc.handle(ServiceRequest("GET", f"/accounts/{alice_id}"))
        bob_resp   = account_svc.handle(ServiceRequest("GET", f"/accounts/{bob_id}"))
        assert alice_resp.body["balance"] == 1_700.0
        assert bob_resp.body["balance"]   == 1_300.0

    def test_transfer_with_unknown_sender_fails(self, tx_svc, bob_id):
        resp = tx_svc.handle(ServiceRequest(
            "POST", "/transfers",
            body={"from_account_id": "GHOST", "to_account_id": bob_id, "amount": 100.0}
        ))
        assert resp.status_code == 404

    def test_transfer_with_unknown_receiver_fails(self, tx_svc, alice_id):
        resp = tx_svc.handle(ServiceRequest(
            "POST", "/transfers",
            body={"from_account_id": alice_id, "to_account_id": "GHOST", "amount": 100.0}
        ))
        assert resp.status_code == 404

    def test_transfer_insufficient_funds_no_balance_change(
        self, tx_svc, account_svc, alice_id, bob_id
    ):
        """Failed transfer leaves both accounts unchanged."""
        tx_svc.handle(ServiceRequest(
            "POST", "/transfers",
            body={"from_account_id": alice_id, "to_account_id": bob_id, "amount": 99_999.0}
        ))
        alice_resp = account_svc.handle(ServiceRequest("GET", f"/accounts/{alice_id}"))
        bob_resp   = account_svc.handle(ServiceRequest("GET", f"/accounts/{bob_id}"))
        assert alice_resp.body["balance"] == 2_000.0   # unchanged
        assert bob_resp.body["balance"]   == 1_000.0   # unchanged

    def test_transfer_limit_enforced(self, tx_svc, alice_id, bob_id):
        resp = tx_svc.handle(ServiceRequest(
            "POST", "/transfers",
            body={"from_account_id": alice_id, "to_account_id": bob_id, "amount": 100_000.0}
        ))
        assert resp.status_code == 422
        assert resp.body["code"] == "LIMIT_EXCEEDED"

    def test_transfer_records_in_own_log(self, tx_svc, alice_id, bob_id):
        tx_svc.handle(ServiceRequest(
            "POST", "/transfers",
            body={"from_account_id": alice_id, "to_account_id": bob_id, "amount": 200.0}
        ))
        assert tx_svc.transaction_log.count() == 1
        record = tx_svc.transaction_log.all()[0]
        assert record["type"] == "TRANSFER"
        assert record["amount"] == 200.0

    def test_validation_errors_do_not_call_account_service(
        self, tx_svc, alice_id, bob_id
    ):
        """Validation failures never hit AccountService — fail fast."""
        calls_before = tx_svc.account_client.call_count
        tx_svc.handle(ServiceRequest(
            "POST", "/transfers",
            body={"from_account_id": alice_id, "to_account_id": bob_id, "amount": -100.0}
        ))
        assert tx_svc.account_client.call_count == calls_before


# ---------------------------------------------------------------------------
# Data isolation — each service owns its data
# ---------------------------------------------------------------------------

class TestDataIsolation:

    def test_transaction_log_is_separate_from_account_service(
        self, tx_svc, account_svc, alice_id, bob_id
    ):
        """
        TransactionService maintains its own transaction log.
        AccountService has no transaction history (that's TS's job).
        """
        tx_svc.handle(ServiceRequest(
            "POST", "/transfers",
            body={"from_account_id": alice_id, "to_account_id": bob_id, "amount": 100.0}
        ))
        # AccountService has no transaction log
        assert not hasattr(account_svc, "transaction_log") or \
               account_svc.repository.count() == 2   # only accounts, no tx log

        # TransactionService has its own log
        assert tx_svc.transaction_log.count() == 1

    def test_multiple_tx_services_do_not_share_log(self, registry):
        """Two instances of TransactionService have independent logs."""
        client = registry.get("account-service")
        ts1    = TransactionMicroservice(client)
        ts2    = TransactionMicroservice(client)

        # Both share the same AccountService but have independent tx logs
        assert ts1.transaction_log is not ts2.transaction_log
        assert ts1.transaction_log.count() == 0
        assert ts2.transaction_log.count() == 0
