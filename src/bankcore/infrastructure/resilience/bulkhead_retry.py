"""
BankCore — Day 25: Bulkhead + Retry
=====================================
Two complementary resilience patterns.

Bulkhead:
  - Limits concurrent calls to a service via semaphore
  - Prevents thread pool exhaustion from one slow service
  - Rejects immediately when semaphore is full (BulkheadFullError)

Retry with exponential backoff:
  - Retries transient failures with increasing wait times
  - Jitter prevents thundering herd
  - Configurable: max_retries, base_delay, max_delay, retryable exceptions

Usage:
    # Standalone Retry
    policy = RetryPolicy(max_retries=3, base_delay=0.1)
    result = policy.execute(lambda: service.call())

    # Standalone Bulkhead
    bulkhead = Bulkhead("account-service", max_concurrent=4)
    with bulkhead:
        result = service.call()

    # Combined as ServiceClient wrapper
    cb_client = BulkheadRetryClient(
        base_client,
        max_concurrent=4,
        max_retries=3,
        base_delay=0.05,
    )
    response = cb_client.get("/accounts/ACC-001")
"""

from __future__ import annotations
import random
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional, Type

from bankcore.services.shared.service_client import ServiceClient, ServiceResponse


# ---------------------------------------------------------------------------
# Bulkhead
# ---------------------------------------------------------------------------

class BulkheadFullError(Exception):
    """Raised when the bulkhead is at maximum concurrency."""

    def __init__(self, name: str, max_concurrent: int) -> None:
        self.name           = name
        self.max_concurrent = max_concurrent
        super().__init__(
            f"Bulkhead '{name}' is full ({max_concurrent} concurrent calls). "
            "Request rejected."
        )


@dataclass
class BulkheadStats:
    """Counters for bulkhead monitoring."""
    total_calls:    int = 0
    accepted_calls: int = 0
    rejected_calls: int = 0
    current:        int = 0
    peak_concurrent: int = 0

    def summary(self) -> str:
        return (
            f"BulkheadStats: {self.total_calls} total, "
            f"{self.accepted_calls} accepted, "
            f"{self.rejected_calls} rejected, "
            f"peak={self.peak_concurrent}"
        )


class Bulkhead:
    """
    Limits concurrent calls via a semaphore.

    Can be used as a context manager:
        with bulkhead:
            result = service.call()

    Or as a wrapper:
        result = bulkhead.call(lambda: service.call())
    """

    def __init__(self, name: str, max_concurrent: int = 10) -> None:
        self._name          = name
        self._max           = max_concurrent
        self._semaphore     = threading.Semaphore(max_concurrent)
        self._current       = 0
        self._lock          = threading.Lock()
        self.stats          = BulkheadStats()

    def call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute func with bulkhead protection."""
        if not self._semaphore.acquire(blocking=False):
            self.stats.total_calls    += 1
            self.stats.rejected_calls += 1
            raise BulkheadFullError(self._name, self._max)

        with self._lock:
            self._current += 1
            self.stats.total_calls    += 1
            self.stats.accepted_calls += 1
            if self._current > self.stats.peak_concurrent:
                self.stats.peak_concurrent = self._current
            self.stats.current = self._current

        try:
            return func(*args, **kwargs)
        finally:
            self._semaphore.release()
            with self._lock:
                self._current -= 1
                self.stats.current = self._current

    def __enter__(self) -> "Bulkhead":
        if not self._semaphore.acquire(blocking=False):
            raise BulkheadFullError(self._name, self._max)
        with self._lock:
            self._current += 1
            self.stats.peak_concurrent = max(
                self.stats.peak_concurrent, self._current
            )
        return self

    def __exit__(self, *args) -> bool:
        self._semaphore.release()
        with self._lock:
            self._current -= 1
        return False

    @property
    def available(self) -> int:
        """Number of available slots."""
        return self._max - self._current

    @property
    def is_full(self) -> bool:
        return self._current >= self._max

    @property
    def name(self) -> str:
        return self._name

    def __repr__(self) -> str:
        return (
            f"Bulkhead({self._name!r}, "
            f"{self._current}/{self._max})"
        )


# ---------------------------------------------------------------------------
# RetryPolicy
# ---------------------------------------------------------------------------

@dataclass
class RetryAttempt:
    """Record of one retry attempt."""
    attempt:    int
    success:    bool
    error:      str   = ""
    wait_ms:    float = 0.0
    elapsed_ms: float = 0.0


@dataclass
class RetryResult:
    """Result of a RetryPolicy execution."""
    success:    bool
    value:      Any   = None
    attempts:   list  = field(default_factory=list)
    total_ms:   float = 0.0
    error:      str   = ""

    @property
    def attempt_count(self) -> int:
        return len(self.attempts)


class RetryPolicy:
    """
    Retries a callable with exponential backoff + jitter.

    Backoff formula:
        wait = min(base_delay * (2 ** attempt), max_delay)
        wait += random(0, wait * jitter_factor)

    Args:
        max_retries:     max number of retries (not total attempts)
        base_delay:      initial wait in seconds (default 0.1s)
        max_delay:       cap on wait time (default 10s)
        jitter_factor:   randomness fraction (default 0.1 = ±10%)
        retryable:       exception types to retry (default: all)
        on_retry:        callback(attempt, exception) called before each retry
    """

    def __init__(
        self,
        max_retries:   int                          = 3,
        base_delay:    float                        = 0.1,
        max_delay:     float                        = 10.0,
        jitter_factor: float                        = 0.1,
        retryable:     tuple[Type[Exception], ...]  = (Exception,),
        on_retry:      Optional[Callable]           = None,
    ) -> None:
        self._max_retries   = max_retries
        self._base_delay    = base_delay
        self._max_delay     = max_delay
        self._jitter        = jitter_factor
        self._retryable     = retryable
        self._on_retry      = on_retry

    def execute(self, func: Callable, *args, **kwargs) -> RetryResult:
        """
        Execute func with retry logic.
        Returns RetryResult — never raises (errors captured in result).
        """
        attempts  = []
        total_start = time.monotonic()

        for attempt in range(self._max_retries + 1):
            attempt_start = time.monotonic()
            try:
                value       = func(*args, **kwargs)
                elapsed_ms  = (time.monotonic() - attempt_start) * 1000
                attempts.append(RetryAttempt(
                    attempt=attempt,
                    success=True,
                    elapsed_ms=elapsed_ms,
                ))
                return RetryResult(
                    success=True,
                    value=value,
                    attempts=attempts,
                    total_ms=(time.monotonic() - total_start) * 1000,
                )

            except Exception as exc:
                if not isinstance(exc, self._retryable):
                    # Non-retryable exception — fail immediately
                    elapsed_ms = (time.monotonic() - attempt_start) * 1000
                    attempts.append(RetryAttempt(
                        attempt=attempt, success=False,
                        error=str(exc), elapsed_ms=elapsed_ms,
                    ))
                    return RetryResult(
                        success=False, attempts=attempts,
                        total_ms=(time.monotonic() - total_start) * 1000,
                        error=str(exc),
                    )

                elapsed_ms = (time.monotonic() - attempt_start) * 1000
                wait_ms    = 0.0

                if attempt < self._max_retries:
                    wait_s  = min(
                        self._base_delay * (2 ** attempt),
                        self._max_delay,
                    )
                    jitter  = random.uniform(0, wait_s * self._jitter)
                    wait_s += jitter
                    wait_ms = wait_s * 1000

                    if self._on_retry:
                        self._on_retry(attempt + 1, exc)

                    time.sleep(wait_s)

                attempts.append(RetryAttempt(
                    attempt=attempt, success=False,
                    error=str(exc), wait_ms=wait_ms, elapsed_ms=elapsed_ms,
                ))

        return RetryResult(
            success=False,
            attempts=attempts,
            total_ms=(time.monotonic() - total_start) * 1000,
            error=f"All {self._max_retries + 1} attempts failed.",
        )

    def compute_wait(self, attempt: int) -> float:
        """Return the wait time (without jitter) for a given attempt number."""
        return min(self._base_delay * (2 ** attempt), self._max_delay)


# ---------------------------------------------------------------------------
# BulkheadRetryClient — combines both patterns as a ServiceClient wrapper
# ---------------------------------------------------------------------------

class BulkheadRetryClient:
    """
    ServiceClient wrapper combining Bulkhead + Retry.

    Request flow:
      1. Check bulkhead (reject immediately if full)
      2. Execute with retry policy
      3. Return response or 503 on exhaustion

    Same interface as ServiceClient — drop-in replacement.
    Composes naturally with CircuitBreakerClient (J24).
    """

    def __init__(
        self,
        client:         ServiceClient,
        max_concurrent: int   = 10,
        max_retries:    int   = 3,
        base_delay:     float = 0.1,
        max_delay:      float = 5.0,
        jitter_factor:  float = 0.1,
    ) -> None:
        self._client   = client
        self._bulkhead = Bulkhead(client.service_name, max_concurrent)
        self._retry    = RetryPolicy(
            max_retries=max_retries,
            base_delay=base_delay,
            max_delay=max_delay,
            jitter_factor=jitter_factor,
        )
        self._retry_log: list[RetryResult] = []

    def get(self, path: str, params: dict = None) -> ServiceResponse:
        return self._call(lambda: self._client.get(path, params))

    def post(self, path: str, body: dict = None) -> ServiceResponse:
        return self._call(lambda: self._client.post(path, body))

    def patch(self, path: str, body: dict = None) -> ServiceResponse:
        return self._call(lambda: self._client.patch(path, body))

    def delete(self, path: str) -> ServiceResponse:
        return self._call(lambda: self._client.delete(path))

    def _call(self, func: Callable) -> ServiceResponse:
        try:
            result = self._bulkhead.call(
                lambda: self._retry.execute(func)
            )
        except BulkheadFullError as e:
            return ServiceResponse(429, {
                "error": str(e),
                "code":  "BULKHEAD_FULL",
            })

        self._retry_log.append(result)

        if result.success:
            return result.value

        return ServiceResponse(503, {
            "error": result.error,
            "code":  "SERVICE_UNAVAILABLE",
            "attempts": result.attempt_count,
        })

    @property
    def bulkhead(self) -> Bulkhead:
        return self._bulkhead

    @property
    def retry_policy(self) -> RetryPolicy:
        return self._retry

    @property
    def call_count(self) -> int:
        return self._client.call_count

    @property
    def service_name(self) -> str:
        return self._client.service_name

    def retry_stats(self) -> dict:
        """Summary of retry behaviour across all calls."""
        if not self._retry_log:
            return {"total_calls": 0, "retried": 0, "avg_attempts": 0}
        retried    = sum(1 for r in self._retry_log if r.attempt_count > 1)
        avg        = sum(r.attempt_count for r in self._retry_log) / len(self._retry_log)
        return {
            "total_calls":   len(self._retry_log),
            "retried":       retried,
            "avg_attempts":  round(avg, 2),
        }

    def __repr__(self) -> str:
        return (
            f"BulkheadRetryClient({self.service_name!r}, "
            f"bulkhead={self._bulkhead}, "
            f"max_retries={self._retry._max_retries})"
        )
