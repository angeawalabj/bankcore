"""
BankCore — Day 24: Circuit Breaker
=====================================
Prevents cascading failures by failing fast when a service is down.

State machine:
  CLOSED    → normal operation, requests pass through
  OPEN      → circuit tripped, requests fail immediately
  HALF_OPEN → one probe request allowed, decides next state

Design:
  - CircuitBreaker wraps any callable (not just ServiceClient)
  - CircuitBreakerClient wraps ServiceClient (Decorator pattern, J05)
  - Fallback: optional callable invoked when circuit is OPEN
  - Thread-safe: threading.Lock protects state transitions
  - Metrics: state changes and call outcomes recorded

Usage:
    # Basic usage
    breaker = CircuitBreaker("account-service", failure_threshold=3)

    try:
        result = breaker.call(lambda: service.get_account(id))
    except CircuitOpenError:
        result = fallback_value

    # With fallback
    breaker = CircuitBreaker("account-service", fallback=lambda: cached_response)
    result = breaker.call(lambda: service.get_account(id))
    # Returns fallback if circuit is OPEN instead of raising

    # As ServiceClient wrapper (Day 16 integration)
    cb_client = CircuitBreakerClient(base_client, failure_threshold=3)
    response  = cb_client.get("/accounts/ACC-001")
    # Same interface as ServiceClient
"""

from __future__ import annotations
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any, Callable, Optional

from bankcore.services.shared.service_client import (
    ServiceClient, ServiceResponse,
)


# ---------------------------------------------------------------------------
# Circuit Breaker State
# ---------------------------------------------------------------------------

class CircuitState(Enum):
    CLOSED    = auto()   # normal — requests pass through
    OPEN      = auto()   # tripped — requests fail fast
    HALF_OPEN = auto()   # recovery probe — one request allowed


class CircuitOpenError(Exception):
    """Raised when a call is attempted with an OPEN circuit."""

    def __init__(self, service_name: str, retry_after: float) -> None:
        self.service_name = service_name
        self.retry_after  = retry_after
        super().__init__(
            f"Circuit OPEN for '{service_name}'. "
            f"Retry after {retry_after:.1f}s."
        )


# ---------------------------------------------------------------------------
# Circuit stats
# ---------------------------------------------------------------------------

@dataclass
class CircuitStats:
    """Counters for circuit breaker monitoring."""
    total_calls:        int   = 0
    successful_calls:   int   = 0
    failed_calls:       int   = 0
    rejected_calls:     int   = 0   # rejected because circuit is OPEN
    fallback_calls:     int   = 0
    state_changes:      list  = field(default_factory=list)

    @property
    def error_rate(self) -> float:
        total = self.successful_calls + self.failed_calls
        if total == 0:
            return 0.0
        return self.failed_calls / total

    def record_state_change(self, from_state: CircuitState, to_state: CircuitState) -> None:
        self.state_changes.append({
            "from":      from_state.name,
            "to":        to_state.name,
            "timestamp": datetime.now().isoformat(),
        })

    def summary(self) -> str:
        return (
            f"CircuitStats: {self.total_calls} calls, "
            f"{self.successful_calls} ok, "
            f"{self.failed_calls} failed, "
            f"{self.rejected_calls} rejected, "
            f"error_rate={self.error_rate:.1%}"
        )


# ---------------------------------------------------------------------------
# CircuitBreaker — core
# ---------------------------------------------------------------------------

class CircuitBreaker:
    """
    Thread-safe Circuit Breaker for any callable.

    Args:
        name:               service identifier for logging
        failure_threshold:  consecutive failures to OPEN (default 5)
        recovery_timeout:   seconds to wait before HALF_OPEN (default 30)
        success_threshold:  consecutive successes in HALF_OPEN to CLOSE (default 2)
        fallback:           optional callable invoked when circuit is OPEN

    The circuit breaker counts CONSECUTIVE failures.
    A single success in CLOSED state resets the failure counter.
    """

    def __init__(
        self,
        name: str,
        failure_threshold:  int            = 5,
        recovery_timeout:   float          = 30.0,
        success_threshold:  int            = 2,
        fallback:           Optional[Callable] = None,
    ) -> None:
        self._name              = name
        self._failure_threshold = failure_threshold
        self._recovery_timeout  = recovery_timeout
        self._success_threshold = success_threshold
        self._fallback          = fallback

        self._state             = CircuitState.CLOSED
        self._failure_count     = 0
        self._success_count     = 0
        self._last_failure_time: Optional[float] = None
        self._lock              = threading.Lock()
        self.stats              = CircuitStats()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute func through the circuit breaker.

        CLOSED:    execute normally, track outcome
        HALF_OPEN: execute as a probe, track outcome
        OPEN:      raise CircuitOpenError (or return fallback)
        """
        with self._lock:
            state = self._get_state()

        if state == CircuitState.OPEN:
            self.stats.rejected_calls += 1
            self.stats.total_calls    += 1
            if self._fallback is not None:
                self.stats.fallback_calls += 1
                return self._fallback(*args, **kwargs)
            raise CircuitOpenError(self._name, self._time_until_retry())

        # CLOSED or HALF_OPEN — attempt the call
        self.stats.total_calls += 1
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as exc:
            self._on_failure()
            raise

    def call_safe(
        self,
        func: Callable,
        default: Any = None,
        *args,
        **kwargs,
    ) -> Any:
        """
        Like call() but returns `default` instead of raising on OPEN.
        Useful for non-critical reads.
        """
        try:
            return self.call(func, *args, **kwargs)
        except CircuitOpenError:
            return default

    # ------------------------------------------------------------------
    # State management
    # ------------------------------------------------------------------

    def _get_state(self) -> CircuitState:
        """Return current state, transitioning OPEN→HALF_OPEN if timeout elapsed."""
        if self._state == CircuitState.OPEN:
            if self._last_failure_time is not None:
                elapsed = time.monotonic() - self._last_failure_time
                if elapsed >= self._recovery_timeout:
                    self._transition(CircuitState.HALF_OPEN)
        return self._state

    def _on_success(self) -> None:
        with self._lock:
            self.stats.successful_calls += 1
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self._success_threshold:
                    self._failure_count = 0
                    self._success_count = 0
                    self._transition(CircuitState.CLOSED)
            else:
                # Reset failure counter on success in CLOSED
                self._failure_count = 0

    def _on_failure(self) -> None:
        with self._lock:
            self.stats.failed_calls  += 1
            self._failure_count      += 1
            self._last_failure_time   = time.monotonic()
            self._success_count       = 0

            if self._state == CircuitState.HALF_OPEN:
                # Probe failed → back to OPEN
                self._transition(CircuitState.OPEN)
            elif self._failure_count >= self._failure_threshold:
                self._transition(CircuitState.OPEN)

    def _transition(self, new_state: CircuitState) -> None:
        """Record state change (called with lock held)."""
        if new_state != self._state:
            self.stats.record_state_change(self._state, new_state)
            self._state = new_state

    def _time_until_retry(self) -> float:
        if self._last_failure_time is None:
            return 0.0
        elapsed = time.monotonic() - self._last_failure_time
        return max(0.0, self._recovery_timeout - elapsed)

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    @property
    def state(self) -> CircuitState:
        with self._lock:
            return self._get_state()

    @property
    def name(self) -> str:
        return self._name

    @property
    def is_open(self) -> bool:
        return self.state == CircuitState.OPEN

    @property
    def is_closed(self) -> bool:
        return self.state == CircuitState.CLOSED

    def reset(self) -> None:
        """Manually reset the circuit to CLOSED. For testing and ops."""
        with self._lock:
            self._transition(CircuitState.CLOSED)
            self._failure_count = 0
            self._success_count = 0
            self._last_failure_time = None

    def __repr__(self) -> str:
        return (
            f"CircuitBreaker({self._name!r}, "
            f"state={self._state.name}, "
            f"failures={self._failure_count}/{self._failure_threshold})"
        )


# ---------------------------------------------------------------------------
# CircuitBreakerClient — wraps ServiceClient (Day 16)
# ---------------------------------------------------------------------------

class CircuitBreakerClient:
    """
    Wraps ServiceClient with Circuit Breaker protection.

    Same interface as ServiceClient — drop-in replacement.
    TransactionMicroservice receives this instead of plain ServiceClient.

    Usage:
        base_client = registry.get("account-service")
        cb_client   = CircuitBreakerClient(base_client, failure_threshold=3)
        tx_service  = TransactionMicroservice(cb_client)
        # If AccountService fails 3 times, circuit opens — fast fail
    """

    def __init__(
        self,
        client: ServiceClient,
        failure_threshold:  int   = 5,
        recovery_timeout:   float = 30.0,
        success_threshold:  int   = 2,
        fallback_response:  Optional[ServiceResponse] = None,
    ) -> None:
        self._client  = client
        self._breaker = CircuitBreaker(
            name=client.service_name,
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
            success_threshold=success_threshold,
        )
        self._fallback_response = fallback_response or ServiceResponse(
            503, {"error": "Service unavailable", "code": "CIRCUIT_OPEN"}
        )

    def get(self, path: str, params: dict = None) -> ServiceResponse:
        return self._call(lambda: self._client.get(path, params))

    def post(self, path: str, body: dict = None) -> ServiceResponse:
        return self._call(lambda: self._client.post(path, body))

    def patch(self, path: str, body: dict = None) -> ServiceResponse:
        return self._call(lambda: self._client.patch(path, body))

    def delete(self, path: str) -> ServiceResponse:
        return self._call(lambda: self._client.delete(path))

    def _call(self, func: Callable) -> ServiceResponse:
        """
        Execute through circuit breaker.
        Returns 503 fallback if circuit is OPEN or if the call raises any exception.
        This ensures TransactionService always gets a ServiceResponse, never an exception.
        """
        try:
            return self._breaker.call(func)
        except CircuitOpenError:
            return self._fallback_response
        except Exception as exc:
            # The call failed (circuit was CLOSED/HALF_OPEN but service errored)
            # Circuit breaker already counted this failure internally
            return ServiceResponse(
                503, {"error": str(exc), "code": "SERVICE_ERROR"}
            )

    @property
    def circuit(self) -> CircuitBreaker:
        return self._breaker

    @property
    def call_count(self) -> int:
        return self._client.call_count

    @property
    def service_name(self) -> str:
        return self._client.service_name

    def __repr__(self) -> str:
        return (
            f"CircuitBreakerClient({self._client.service_name!r}, "
            f"state={self._breaker.state.name})"
        )
