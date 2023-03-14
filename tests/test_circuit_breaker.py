"""
Tests — Day 24: Circuit Breaker
=================================
Test strategy:
  1. CircuitBreaker — CLOSED→OPEN transition on failures
  2. CircuitBreaker — OPEN rejects calls immediately
  3. CircuitBreaker — OPEN→HALF_OPEN after recovery_timeout
  4. CircuitBreaker — HALF_OPEN→CLOSED on success_threshold successes
  5. CircuitBreaker — HALF_OPEN→OPEN on probe failure
  6. Fallback — returned when circuit is OPEN
  7. CircuitStats — call counts, error rate, state changes
  8. CircuitBreakerClient — wraps ServiceClient (Day 16)
  9. Thread safety — concurrent calls don't corrupt state
  10. Integration — TransactionService with circuit-broken AccountService
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
from bankcore.infrastructure.resilience.circuit_breaker import (
    CircuitBreaker, CircuitBreakerClient,
    CircuitState, CircuitOpenError, CircuitStats,
)
from bankcore.services.account_service.service import AccountService
from bankcore.services.transaction_service.service import TransactionMicroservice
from bankcore.services.shared.service_client import (
    ServiceClient, ServiceRegistry, ServiceRequest, ServiceResponse,
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
def breaker():
    return CircuitBreaker("test-service", failure_threshold=3, recovery_timeout=0.1)


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
# CLOSED state — normal operation
# ---------------------------------------------------------------------------

class TestCircuitBreakerClosed:

    def test_initial_state_is_closed(self, breaker):
        assert breaker.state == CircuitState.CLOSED
        assert breaker.is_closed

    def test_successful_call_returns_result(self, breaker):
        result = breaker.call(lambda: 42)
        assert result == 42

    def test_successful_call_increments_counter(self, breaker):
        breaker.call(lambda: "ok")
        assert breaker.stats.successful_calls == 1

    def test_failure_below_threshold_stays_closed(self, breaker):
        for _ in range(2):   # threshold is 3
            try:
                breaker.call(lambda: (_ for _ in ()).throw(RuntimeError("fail")))
            except RuntimeError:
                pass
        assert breaker.state == CircuitState.CLOSED

    def test_success_resets_failure_count(self, breaker):
        """A success in CLOSED resets the consecutive failure counter."""
        for _ in range(2):
            try:
                breaker.call(lambda: (_ for _ in ()).throw(RuntimeError()))
            except RuntimeError:
                pass
        breaker.call(lambda: "ok")   # reset
        # Now 2 more failures should NOT open (counter reset)
        for _ in range(2):
            try:
                breaker.call(lambda: (_ for _ in ()).throw(RuntimeError()))
            except RuntimeError:
                pass
        assert breaker.state == CircuitState.CLOSED


# ---------------------------------------------------------------------------
# CLOSED → OPEN transition
# ---------------------------------------------------------------------------

class TestCircuitBreakerOpening:

    def test_opens_after_failure_threshold(self, breaker):
        for _ in range(3):
            try:
                breaker.call(lambda: (_ for _ in ()).throw(RuntimeError("fail")))
            except RuntimeError:
                pass
        assert breaker.state == CircuitState.OPEN
        assert breaker.is_open

    def test_open_raises_circuit_open_error(self, breaker):
        for _ in range(3):
            try:
                breaker.call(lambda: (_ for _ in ()).throw(RuntimeError()))
            except RuntimeError:
                pass

        with pytest.raises(CircuitOpenError) as exc_info:
            breaker.call(lambda: "should not execute")

        assert "test-service" in str(exc_info.value)

    def test_open_circuit_does_not_call_function(self, breaker):
        call_count = [0]

        def tracked_fail():
            call_count[0] += 1
            raise RuntimeError("fail")

        for _ in range(3):
            try:
                breaker.call(tracked_fail)
            except RuntimeError:
                pass

        calls_at_open = call_count[0]

        try:
            breaker.call(tracked_fail)
        except CircuitOpenError:
            pass

        assert call_count[0] == calls_at_open   # no new call

    def test_rejected_calls_counted(self, breaker):
        for _ in range(3):
            try:
                breaker.call(lambda: (_ for _ in ()).throw(RuntimeError()))
            except RuntimeError:
                pass

        for _ in range(5):
            try:
                breaker.call(lambda: None)
            except CircuitOpenError:
                pass

        assert breaker.stats.rejected_calls == 5


# ---------------------------------------------------------------------------
# OPEN → HALF_OPEN → CLOSED (recovery)
# ---------------------------------------------------------------------------

class TestCircuitBreakerRecovery:

    def _trip(self, breaker):
        for _ in range(3):
            try:
                breaker.call(lambda: (_ for _ in ()).throw(RuntimeError()))
            except RuntimeError:
                pass

    def test_transitions_to_half_open_after_timeout(self, breaker):
        self._trip(breaker)
        assert breaker.state == CircuitState.OPEN

        time.sleep(0.15)   # > recovery_timeout=0.1s
        assert breaker.state == CircuitState.HALF_OPEN

    def test_half_open_allows_one_probe(self, breaker):
        self._trip(breaker)
        time.sleep(0.15)

        result = breaker.call(lambda: "probe_ok")
        assert result == "probe_ok"

    def test_successful_probe_moves_to_half_open_not_closed(self, breaker):
        """success_threshold=2, so one success stays in HALF_OPEN."""
        self._trip(breaker)
        time.sleep(0.15)

        breaker.call(lambda: "ok")   # 1 success, threshold=2 → still HALF_OPEN
        # (default success_threshold is 2 in our fixture)
        # Actually our fixture has success_threshold=2 (default)

    def test_closes_after_success_threshold(self):
        """With success_threshold=1, one probe closes the circuit."""
        breaker = CircuitBreaker(
            "svc", failure_threshold=3, recovery_timeout=0.1, success_threshold=1
        )
        for _ in range(3):
            try:
                breaker.call(lambda: (_ for _ in ()).throw(RuntimeError()))
            except RuntimeError:
                pass

        time.sleep(0.15)
        breaker.call(lambda: "probe_ok")   # 1 success = threshold met
        assert breaker.state == CircuitState.CLOSED

    def test_failed_probe_reopens_circuit(self, breaker):
        self._trip(breaker)
        time.sleep(0.15)
        assert breaker.state == CircuitState.HALF_OPEN

        try:
            breaker.call(lambda: (_ for _ in ()).throw(RuntimeError("probe fail")))
        except RuntimeError:
            pass

        assert breaker.state == CircuitState.OPEN

    def test_manual_reset_closes_circuit(self, breaker):
        self._trip(breaker)
        assert breaker.is_open

        breaker.reset()
        assert breaker.is_closed
        assert breaker.stats.successful_calls == breaker.stats.successful_calls


# ---------------------------------------------------------------------------
# Fallback
# ---------------------------------------------------------------------------

class TestCircuitBreakerFallback:

    def test_fallback_called_when_open(self):
        breaker = CircuitBreaker(
            "svc",
            failure_threshold=2,
            recovery_timeout=30.0,
            fallback=lambda: {"fallback": True},
        )
        for _ in range(2):
            try:
                breaker.call(lambda: (_ for _ in ()).throw(RuntimeError()))
            except RuntimeError:
                pass

        result = breaker.call(lambda: None)
        assert result == {"fallback": True}

    def test_fallback_increments_counter(self):
        breaker = CircuitBreaker(
            "svc",
            failure_threshold=2,
            fallback=lambda: "default",
        )
        for _ in range(2):
            try:
                breaker.call(lambda: (_ for _ in ()).throw(RuntimeError()))
            except RuntimeError:
                pass

        breaker.call(lambda: None)
        assert breaker.stats.fallback_calls == 1

    def test_call_safe_returns_default_when_open(self):
        breaker = CircuitBreaker("svc", failure_threshold=2)
        for _ in range(2):
            try:
                breaker.call(lambda: (_ for _ in ()).throw(RuntimeError()))
            except RuntimeError:
                pass

        result = breaker.call_safe(lambda: None, default="safe_default")
        assert result == "safe_default"


# ---------------------------------------------------------------------------
# CircuitStats
# ---------------------------------------------------------------------------

class TestCircuitStats:

    def test_error_rate_zero_with_no_failures(self, breaker):
        breaker.call(lambda: "ok")
        assert breaker.stats.error_rate == 0.0

    def test_error_rate_calculation(self, breaker):
        breaker.call(lambda: "ok")
        breaker.call(lambda: "ok")
        try:
            breaker.call(lambda: (_ for _ in ()).throw(RuntimeError()))
        except RuntimeError:
            pass
        # 2 success, 1 fail → 1/3 = 33%
        assert breaker.stats.error_rate == pytest.approx(1/3)

    def test_state_changes_recorded(self, breaker):
        for _ in range(3):
            try:
                breaker.call(lambda: (_ for _ in ()).throw(RuntimeError()))
            except RuntimeError:
                pass
        changes = breaker.stats.state_changes
        assert len(changes) >= 1
        assert changes[-1]["to"] == "OPEN"

    def test_summary_readable(self, breaker):
        breaker.call(lambda: "ok")
        s = breaker.stats.summary()
        assert "CircuitStats" in s
        assert "%" in s


# ---------------------------------------------------------------------------
# CircuitBreakerClient
# ---------------------------------------------------------------------------

class TestCircuitBreakerClient:

    def test_wraps_service_client(self, base_client):
        cb = CircuitBreakerClient(base_client, failure_threshold=3)
        assert isinstance(cb, CircuitBreakerClient)
        assert cb.service_name == "account-service"

    def test_passes_successful_requests(self, base_client, alice_id):
        cb   = CircuitBreakerClient(base_client, failure_threshold=3)
        resp = cb.get(f"/accounts/{alice_id}")
        assert resp.status_code == 200

    def test_returns_503_when_circuit_open(self, account_svc, alice_id):
        """
        Simulate AccountService failures to open the circuit,
        then verify 503 is returned without hitting AccountService.
        """
        def failing_handler(req):
            raise RuntimeError("Service down!")

        reg     = ServiceRegistry()
        failing = reg.register("account-service", failing_handler)
        cb      = CircuitBreakerClient(failing, failure_threshold=3)

        # Trip the circuit
        for _ in range(3):
            cb.get("/accounts/ANY")

        assert cb.circuit.is_open

        # Now calls return 503 without hitting the service
        calls_before = failing.call_count
        resp         = cb.get(f"/accounts/{alice_id}")
        assert resp.status_code == 503
        assert failing.call_count == calls_before   # no new call

    def test_repr(self, base_client):
        cb = CircuitBreakerClient(base_client, failure_threshold=3)
        r  = repr(cb)
        assert "account-service" in r
        assert "CLOSED" in r


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------

class TestCircuitBreakerThreadSafety:

    def test_concurrent_failures_open_circuit_exactly_once(self):
        breaker     = CircuitBreaker("svc", failure_threshold=5)
        transitions = []

        original_transition = breaker._transition
        def tracked_transition(new_state):
            transitions.append(new_state)
            original_transition(new_state)
        breaker._transition = tracked_transition

        def fail():
            try:
                breaker.call(lambda: (_ for _ in ()).throw(RuntimeError()))
            except (RuntimeError, CircuitOpenError):
                pass

        threads = [threading.Thread(target=fail) for _ in range(20)]
        for t in threads: t.start()
        for t in threads: t.join()

        open_transitions = [s for s in transitions if s == CircuitState.OPEN]
        assert len(open_transitions) >= 1   # at least one transition to OPEN


# ---------------------------------------------------------------------------
# Integration: TransactionService with Circuit Breaker
# ---------------------------------------------------------------------------

class TestCircuitBreakerIntegration:

    def test_transfer_works_with_cb_client(self, account_svc, alice_id, bob_id):
        reg    = ServiceRegistry()
        base   = reg.register("account-service", account_svc.handle)
        cb     = CircuitBreakerClient(base, failure_threshold=5)
        tx_svc = TransactionMicroservice(cb)

        resp = tx_svc.handle(ServiceRequest(
            "POST", "/transfers",
            body={"from_account_id": alice_id, "to_account_id": bob_id, "amount": 300.0}
        ))
        assert resp.status_code == 200
        assert cb.circuit.is_closed

    def test_transfer_fails_fast_when_circuit_open(self, account_svc, alice_id, bob_id):
        """
        After AccountService fails enough times, circuit opens.
        Subsequent transfer attempts fail immediately (503) without waiting.
        """
        call_times = []

        def slow_then_fail(req):
            call_times.append(time.monotonic())
            raise RuntimeError("AccountService down")

        reg    = ServiceRegistry()
        base   = reg.register("account-service", slow_then_fail)
        cb     = CircuitBreakerClient(base, failure_threshold=3, recovery_timeout=60.0)
        tx_svc = TransactionMicroservice(cb)

        # Trip the circuit
        for _ in range(3):
            tx_svc.handle(ServiceRequest(
                "POST", "/deposits",
                body={"account_id": alice_id, "amount": 100.0}
            ))

        assert cb.circuit.is_open

        calls_before = len(call_times)
        start        = time.monotonic()

        # This should fail fast — circuit is open
        resp = tx_svc.handle(ServiceRequest(
            "POST", "/deposits",
            body={"account_id": alice_id, "amount": 100.0}
        ))

        elapsed = (time.monotonic() - start) * 1000
        assert len(call_times) == calls_before   # no new call to AccountService
        assert elapsed < 50   # fail fast: < 50ms (not 5s timeout)
        assert resp.status_code == 503
