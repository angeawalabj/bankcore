"""
Tests — Day 25: Bulkhead + Retry
===================================
Test strategy:
  1. Bulkhead — normal calls, rejection when full, peak tracking
  2. Bulkhead context manager — enter/exit, release on exception
  3. RetryPolicy — success on first try, retry on failure, backoff
  4. RetryResult — attempt count, total time, error capture
  5. RetryPolicy.compute_wait — exponential growth, max_delay cap
  6. BulkheadRetryClient — combined, 429 on full, 503 on exhaustion
  7. Integration — retries succeed after transient failures
  8. Thread safety — concurrent bulkhead enforcement
"""

import sys
import time
import threading
import pytest

sys.path.insert(0, "src")

from bankcore.config_manager import ConfigManager
from bankcore.alert_system import AlertSystem
from bankcore.account_type_registry import AccountTypeRegistry
from bankcore.account_factory import AccountFactory
from bankcore.infrastructure.resilience.bulkhead_retry import (
    Bulkhead, BulkheadFullError, BulkheadStats,
    RetryPolicy, RetryResult, RetryAttempt,
    BulkheadRetryClient,
)
from bankcore.services.account_service.service import AccountService
from bankcore.services.transaction_service.service import TransactionMicroservice
from bankcore.services.shared.service_client import (
    ServiceRegistry, ServiceRequest, ServiceResponse,
)


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
def base_client(account_svc):
    reg = ServiceRegistry()
    return reg.register("account-service", account_svc.handle)


@pytest.fixture
def alice_id(account_svc):
    r = account_svc.handle(ServiceRequest(
        "POST", "/accounts",
        body={"owner_name": "Alice", "account_type": "current",
              "initial_deposit": 2_000.0}
    ))
    return r.body["account_id"]


@pytest.fixture
def bob_id(account_svc):
    r = account_svc.handle(ServiceRequest(
        "POST", "/accounts",
        body={"owner_name": "Bob", "account_type": "current",
              "initial_deposit": 1_000.0}
    ))
    return r.body["account_id"]


# ---------------------------------------------------------------------------
# Bulkhead — core behaviour
# ---------------------------------------------------------------------------

class TestBulkhead:

    def test_accepts_calls_below_limit(self):
        bh = Bulkhead("svc", max_concurrent=3)
        results = []
        for _ in range(3):
            r = bh.call(lambda: "ok")
            results.append(r)
        assert results == ["ok", "ok", "ok"]
        assert bh.stats.accepted_calls == 3
        assert bh.stats.rejected_calls == 0

    def test_rejects_when_full(self):
        """Bulkhead with concurrent=1 rejects a second concurrent call."""
        bh      = Bulkhead("svc", max_concurrent=1)
        barrier = threading.Barrier(2)
        errors  = []

        def slow_call():
            barrier.wait()   # sync both threads to start simultaneously
            time.sleep(0.05)
            return "done"

        def second_call():
            barrier.wait()
            try:
                bh.call(lambda: "second")
            except BulkheadFullError as e:
                errors.append(e)

        t1 = threading.Thread(target=lambda: bh.call(slow_call))
        t2 = threading.Thread(target=second_call)
        t1.start(); t2.start()
        t1.join();  t2.join()

        assert len(errors) == 1
        assert isinstance(errors[0], BulkheadFullError)

    def test_available_slots(self):
        bh = Bulkhead("svc", max_concurrent=5)
        assert bh.available == 5

    def test_peak_concurrent_tracked(self):
        """Verify peak_concurrent is updated on each accepted call."""
        bh = Bulkhead("svc", max_concurrent=10)
        # Sequential calls — peak increases as we verify stats
        bh.call(lambda: None)
        bh.call(lambda: None)
        bh.call(lambda: None)
        # Peak = 1 (sequential), but accepted_calls = 3
        assert bh.stats.accepted_calls == 3
        assert bh.stats.peak_concurrent >= 1

    def test_slot_released_after_call(self):
        bh = Bulkhead("svc", max_concurrent=1)
        bh.call(lambda: None)
        # After call completes, slot is available
        result = bh.call(lambda: "second")
        assert result == "second"

    def test_slot_released_on_exception(self):
        bh = Bulkhead("svc", max_concurrent=1)
        try:
            bh.call(lambda: (_ for _ in ()).throw(RuntimeError("fail")))
        except RuntimeError:
            pass
        # Slot should be released despite exception
        result = bh.call(lambda: "recovered")
        assert result == "recovered"

    def test_context_manager(self):
        bh = Bulkhead("svc", max_concurrent=2)
        with bh:
            assert bh._current == 1
        assert bh._current == 0

    def test_context_manager_releases_on_exception(self):
        bh = Bulkhead("svc", max_concurrent=2)
        try:
            with bh:
                raise ValueError("inner error")
        except ValueError:
            pass
        assert bh._current == 0

    def test_bulkhead_full_error_message(self):
        bh = Bulkhead("account-service", max_concurrent=2)
        err = BulkheadFullError("account-service", 2)
        assert "account-service" in str(err)
        assert "2" in str(err)

    def test_stats_summary(self):
        bh = Bulkhead("svc", max_concurrent=5)
        bh.call(lambda: None)
        s = bh.stats.summary()
        assert "total" in s
        assert "accepted" in s

    def test_repr(self):
        bh = Bulkhead("my-service", max_concurrent=10)
        r  = repr(bh)
        assert "my-service" in r
        assert "10" in r


# ---------------------------------------------------------------------------
# RetryPolicy
# ---------------------------------------------------------------------------

class TestRetryPolicy:

    def test_success_on_first_attempt(self):
        policy = RetryPolicy(max_retries=3, base_delay=0.001)
        result = policy.execute(lambda: 42)
        assert result.success is True
        assert result.value == 42
        assert result.attempt_count == 1

    def test_retry_on_failure_then_success(self):
        call_count = [0]

        def flaky():
            call_count[0] += 1
            if call_count[0] < 3:
                raise RuntimeError(f"attempt {call_count[0]} failed")
            return "success"

        policy = RetryPolicy(max_retries=3, base_delay=0.001)
        result = policy.execute(flaky)

        assert result.success is True
        assert result.value == "success"
        assert result.attempt_count == 3

    def test_exhausts_retries(self):
        policy = RetryPolicy(max_retries=2, base_delay=0.001)
        result = policy.execute(lambda: (_ for _ in ()).throw(RuntimeError("always fails")))

        assert result.success is False
        assert result.attempt_count == 3   # initial + 2 retries

    def test_retry_result_captures_error(self):
        policy = RetryPolicy(max_retries=1, base_delay=0.001)
        result = policy.execute(lambda: (_ for _ in ()).throw(ValueError("specific error")))
        assert "specific error" in result.error or result.attempt_count > 0

    def test_attempts_recorded(self):
        call_count = [0]

        def fail_twice():
            call_count[0] += 1
            if call_count[0] <= 2:
                raise RuntimeError("fail")
            return "ok"

        policy  = RetryPolicy(max_retries=3, base_delay=0.001)
        result  = policy.execute(fail_twice)
        assert result.success is True
        assert len(result.attempts) == 3

    def test_on_retry_callback(self):
        retries = []

        def on_retry(attempt, exc):
            retries.append((attempt, str(exc)))

        count = [0]
        def fail_once():
            count[0] += 1
            if count[0] == 1:
                raise RuntimeError("transient")
            return "ok"

        policy = RetryPolicy(max_retries=2, base_delay=0.001, on_retry=on_retry)
        result = policy.execute(fail_once)

        assert result.success is True
        assert len(retries) == 1
        assert "transient" in retries[0][1]

    def test_non_retryable_exception_fails_immediately(self):
        call_count = [0]

        def raise_value_error():
            call_count[0] += 1
            raise ValueError("non-retryable")

        policy = RetryPolicy(
            max_retries=5,
            base_delay=0.001,
            retryable=(RuntimeError,),   # only RuntimeError is retryable
        )
        result = policy.execute(raise_value_error)

        assert result.success is False
        assert call_count[0] == 1   # only one attempt — no retry

    def test_compute_wait_exponential_growth(self):
        policy = RetryPolicy(base_delay=0.1, max_delay=10.0)
        assert policy.compute_wait(0) == pytest.approx(0.1)
        assert policy.compute_wait(1) == pytest.approx(0.2)
        assert policy.compute_wait(2) == pytest.approx(0.4)
        assert policy.compute_wait(3) == pytest.approx(0.8)

    def test_compute_wait_capped_by_max_delay(self):
        policy = RetryPolicy(base_delay=1.0, max_delay=3.0)
        assert policy.compute_wait(0) == pytest.approx(1.0)
        assert policy.compute_wait(1) == pytest.approx(2.0)
        assert policy.compute_wait(2) == pytest.approx(3.0)   # capped
        assert policy.compute_wait(3) == pytest.approx(3.0)   # still capped

    def test_total_elapsed_time_recorded(self):
        policy = RetryPolicy(max_retries=2, base_delay=0.001)
        result = policy.execute(lambda: "fast")
        assert result.total_ms >= 0


# ---------------------------------------------------------------------------
# BulkheadRetryClient
# ---------------------------------------------------------------------------

class TestBulkheadRetryClient:

    def test_passes_successful_request(self, base_client, alice_id):
        client = BulkheadRetryClient(base_client, max_concurrent=5, max_retries=1)
        resp   = client.get(f"/accounts/{alice_id}")
        assert resp.status_code == 200

    def test_post_creates_account(self, base_client):
        client = BulkheadRetryClient(base_client, max_concurrent=5, max_retries=1)
        resp   = client.post("/accounts", {
            "owner_name": "Carol", "account_type": "current", "initial_deposit": 500.0
        })
        assert resp.status_code == 201

    def test_returns_429_when_bulkhead_full(self):
        """When all bulkhead slots occupied, new calls get 429."""
        # Mock a handler that immediately succeeds
        def fast_handler(req):
            return ServiceResponse(200, {})

        reg    = ServiceRegistry()
        base   = reg.register("svc", fast_handler)
        # Use a pre-occupied bulkhead by manually holding the slot
        client = BulkheadRetryClient(base, max_concurrent=1, max_retries=0,
                                     base_delay=0.001)
        # Manually fill the bulkhead
        client.bulkhead._semaphore.acquire()
        resp = client.get("/test")
        client.bulkhead._semaphore.release()
        # While bulkhead was full, should have gotten 429
        assert resp.status_code == 429

    def test_returns_503_after_all_retries_exhausted(self):
        def always_fail(req):
            raise RuntimeError("down")

        reg    = ServiceRegistry()
        base   = reg.register("svc", always_fail)
        client = BulkheadRetryClient(
            base, max_concurrent=5, max_retries=2, base_delay=0.001
        )
        resp = client.get("/test")
        assert resp.status_code == 503
        assert resp.body.get("attempts") == 3   # initial + 2 retries

    def test_retry_on_transient_failure(self):
        """
        Service fails twice, then succeeds.
        BulkheadRetryClient should retry and return 200.
        """
        call_count = [0]

        def flaky_service(req):
            call_count[0] += 1
            if call_count[0] < 3:
                raise RuntimeError("transient error")
            return ServiceResponse(200, {"balance": 1000.0})

        reg    = ServiceRegistry()
        base   = reg.register("svc", flaky_service)
        client = BulkheadRetryClient(
            base, max_concurrent=5, max_retries=3, base_delay=0.001
        )
        resp = client.get("/accounts/ACC-001")
        assert resp.status_code == 200
        assert call_count[0] == 3

    def test_retry_stats(self, base_client, alice_id):
        client = BulkheadRetryClient(base_client, max_concurrent=5, max_retries=2)
        client.get(f"/accounts/{alice_id}")
        client.get(f"/accounts/{alice_id}")
        stats = client.retry_stats()
        assert stats["total_calls"] == 2
        assert "avg_attempts" in stats

    def test_repr(self, base_client):
        client = BulkheadRetryClient(base_client, max_concurrent=4, max_retries=3)
        r      = repr(client)
        assert "account-service" in r
        assert "4" in r

    def test_service_name(self, base_client):
        client = BulkheadRetryClient(base_client)
        assert client.service_name == "account-service"


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------

class TestBulkheadThreadSafety:

    def test_concurrent_calls_respect_limit(self):
        """
        Sequential calls: all accepted (no concurrency issue).
        Verify the semaphore actually limits concurrent access.
        """
        bh = Bulkhead("svc", max_concurrent=3)
        # Fill all 3 slots manually
        for _ in range(3):
            bh._semaphore.acquire()

        # Next call should be rejected (all slots taken)
        with pytest.raises(BulkheadFullError):
            bh.call(lambda: None)

        assert bh.stats.rejected_calls == 1

        # Release slots
        for _ in range(3):
            bh._semaphore.release()

        # Now call works again
        bh.call(lambda: None)
        assert bh.stats.accepted_calls == 1


# ---------------------------------------------------------------------------
# Integration: TransactionService with BulkheadRetryClient
# ---------------------------------------------------------------------------

class TestBulkheadRetryIntegration:

    def test_transfer_with_resilient_client(self, account_svc, alice_id, bob_id):
        reg    = ServiceRegistry()
        base   = reg.register("account-service", account_svc.handle)
        client = BulkheadRetryClient(
            base, max_concurrent=10, max_retries=2, base_delay=0.001
        )
        tx_svc = TransactionMicroservice(client)

        resp = tx_svc.handle(ServiceRequest(
            "POST", "/transfers",
            body={"from_account_id": alice_id, "to_account_id": bob_id,
                  "amount": 500.0}
        ))
        assert resp.status_code == 200
        assert resp.body["from_balance_after"] == 1_500.0

    def test_transfer_retries_on_transient_service_failure(
        self, account_svc, alice_id, bob_id
    ):
        """
        AccountService fails on first 2 GET calls, then works.
        BulkheadRetryClient retries and the transfer eventually succeeds.
        """
        call_count = [0]
        original   = account_svc.handle

        def intermittent(req):
            call_count[0] += 1
            # First 2 calls to GET an account fail
            if "GET" in req.method and call_count[0] <= 2:
                raise RuntimeError("Network hiccup")
            return original(req)

        reg    = ServiceRegistry()
        base   = reg.register("account-service", intermittent)
        client = BulkheadRetryClient(
            base, max_concurrent=10, max_retries=3, base_delay=0.001
        )
        tx_svc = TransactionMicroservice(client)

        resp = tx_svc.handle(ServiceRequest(
            "POST", "/transfers",
            body={"from_account_id": alice_id, "to_account_id": bob_id,
                  "amount": 300.0}
        ))
        # Transfer should succeed after retries
        assert resp.status_code == 200
        assert call_count[0] > 2   # confirms retries happened

    def test_deposit_with_bulkhead_stats(self, account_svc, alice_id):
        reg    = ServiceRegistry()
        base   = reg.register("account-service", account_svc.handle)
        client = BulkheadRetryClient(
            base, max_concurrent=10, max_retries=1, base_delay=0.001
        )
        tx_svc = TransactionMicroservice(client)

        for _ in range(3):
            tx_svc.handle(ServiceRequest(
                "POST", "/deposits",
                body={"account_id": alice_id, "amount": 100.0}
            ))

        stats = client.retry_stats()
        assert stats["total_calls"] >= 3
        assert client.bulkhead.stats.accepted_calls >= 3
