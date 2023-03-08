"""
BankCore — Day 20: Health Check
==================================
Composite health check system for BankCore services.

Kubernetes-style health probes:
  - Liveness:  is the service alive? (restart if not)
  - Readiness: is it ready to receive traffic? (remove from load balancer if not)

Each check is a callable that returns a CheckResult.
HealthChecker composes multiple checks and returns the overall status.

Usage:
    checker = HealthChecker("account-service")
    checker.add_check("database", DatabaseCheck(repo))
    checker.add_check("cache",    CacheCheck(cache))

    result = checker.check()
    print(result.status)    # "healthy", "degraded", "unhealthy"
    print(result.to_dict()) # full JSON-serializable report
"""

from __future__ import annotations
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


# ---------------------------------------------------------------------------
# CheckResult
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    """Result of a single health check."""
    name:        str
    status:      str          # "ok", "degraded", "error"
    latency_ms:  float = 0.0
    message:     str   = ""
    details:     dict  = field(default_factory=dict)
    checked_at:  str   = field(default_factory=lambda: datetime.now().isoformat())

    @property
    def is_healthy(self) -> bool:
        return self.status == "ok"

    @property
    def is_degraded(self) -> bool:
        return self.status == "degraded"

    def to_dict(self) -> dict:
        return {
            "name":       self.name,
            "status":     self.status,
            "latency_ms": round(self.latency_ms, 2),
            "message":    self.message,
            "details":    self.details,
            "checked_at": self.checked_at,
        }


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

class HealthCheck(ABC):
    """Abstract health check — each subclass tests one dependency."""

    @abstractmethod
    def check(self) -> CheckResult:
        """Run the check and return a result."""


class RepositoryHealthCheck(HealthCheck):
    """Verifies the account repository is accessible."""

    def __init__(self, repository, name: str = "database") -> None:
        self._repo = repository
        self._name = name

    def check(self) -> CheckResult:
        start = time.monotonic()
        try:
            count = self._repo.count()
            latency = (time.monotonic() - start) * 1000
            return CheckResult(
                name=self._name,
                status="ok",
                latency_ms=latency,
                message=f"Repository accessible. {count} accounts.",
                details={"account_count": count},
            )
        except Exception as e:
            latency = (time.monotonic() - start) * 1000
            return CheckResult(
                name=self._name,
                status="error",
                latency_ms=latency,
                message=f"Repository error: {e}",
            )


class CacheHealthCheck(HealthCheck):
    """Verifies the cache is functional."""

    def __init__(self, cache, name: str = "cache") -> None:
        self._cache = cache
        self._name  = name

    def check(self) -> CheckResult:
        start = time.monotonic()
        try:
            self._cache.set("_health_probe", "ok", ttl_seconds=5)
            result = self._cache.get("_health_probe")
            self._cache.delete("_health_probe")
            latency = (time.monotonic() - start) * 1000

            if result != "ok":
                return CheckResult(
                    name=self._name,
                    status="degraded",
                    latency_ms=latency,
                    message="Cache read/write inconsistency.",
                )

            hit_rate = self._cache.stats.hit_rate
            status   = "ok" if hit_rate >= 0 else "degraded"
            return CheckResult(
                name=self._name,
                status=status,
                latency_ms=latency,
                message=f"Cache functional. Hit rate: {hit_rate:.1%}",
                details={
                    "hit_rate":   round(hit_rate, 3),
                    "active_entries": self._cache.active_size(),
                },
            )
        except Exception as e:
            latency = (time.monotonic() - start) * 1000
            return CheckResult(
                name=self._name,
                status="error",
                latency_ms=latency,
                message=f"Cache error: {e}",
            )


class MessageBusHealthCheck(HealthCheck):
    """Verifies the message bus is functional."""

    def __init__(self, bus, name: str = "message_bus") -> None:
        self._bus  = bus
        self._name = name

    def check(self) -> CheckResult:
        start = time.monotonic()
        try:
            dlq_depth = self._bus.dlq.count()
            latency   = (time.monotonic() - start) * 1000

            status  = "ok"
            message = f"Message bus functional. DLQ depth: {dlq_depth}."
            if dlq_depth > 10:
                status  = "degraded"
                message = f"DLQ depth elevated: {dlq_depth} messages."
            if dlq_depth > 100:
                status  = "error"
                message = f"DLQ critical: {dlq_depth} messages."

            return CheckResult(
                name=self._name,
                status=status,
                latency_ms=latency,
                message=message,
                details={
                    "published_total": self._bus.published_count(),
                    "dlq_depth":       dlq_depth,
                    "subscribers":     self._bus.subscriber_count(),
                },
            )
        except Exception as e:
            latency = (time.monotonic() - start) * 1000
            return CheckResult(
                name=self._name,
                status="error",
                latency_ms=latency,
                message=f"Message bus error: {e}",
            )


class MetricsHealthCheck(HealthCheck):
    """Reports current metric values as part of health check."""

    def __init__(self, registry, name: str = "metrics") -> None:
        self._registry = registry
        self._name     = name

    def check(self) -> CheckResult:
        start    = time.monotonic()
        snapshot = self._registry.snapshot()
        latency  = (time.monotonic() - start) * 1000

        transfers_failed = snapshot["counters"].get("transfers_failed_total", 0)
        transfers_total  = snapshot["counters"].get("transfers_total", 0)
        error_rate = (
            transfers_failed / transfers_total
            if transfers_total > 0 else 0.0
        )

        status = "ok"
        if error_rate > 0.05:
            status = "degraded"
        if error_rate > 0.20:
            status = "error"

        return CheckResult(
            name=self._name,
            status=status,
            latency_ms=latency,
            message=f"Error rate: {error_rate:.1%}",
            details={
                "transfers_total":  transfers_total,
                "error_rate":       round(error_rate, 4),
                "cache_hit_rate":   snapshot["counters"].get("cache_hits_total", 0),
            },
        )


# ---------------------------------------------------------------------------
# HealthChecker — composite
# ---------------------------------------------------------------------------

@dataclass
class HealthReport:
    """Aggregated result of all health checks."""
    service:    str
    status:     str   # "healthy", "degraded", "unhealthy"
    checks:     list[CheckResult]
    checked_at: str = field(default_factory=lambda: datetime.now().isoformat())
    uptime_s:   float = 0.0

    @property
    def is_healthy(self) -> bool:
        return self.status == "healthy"

    def to_dict(self) -> dict:
        return {
            "service":    self.service,
            "status":     self.status,
            "uptime_s":   round(self.uptime_s, 1),
            "checked_at": self.checked_at,
            "checks":     {c.name: c.to_dict() for c in self.checks},
        }


class HealthChecker:
    """
    Runs all registered checks and aggregates status.

    Aggregation rules:
      - All checks OK   → "healthy"
      - Any degraded    → "degraded"
      - Any error       → "unhealthy"
    """

    def __init__(self, service_name: str) -> None:
        self._service  = service_name
        self._checks:  dict[str, HealthCheck] = {}
        self._started  = time.monotonic()

    def add_check(self, name: str, check: HealthCheck) -> "HealthChecker":
        self._checks[name] = check
        return self

    def check(self) -> HealthReport:
        results  = [c.check() for c in self._checks.values()]
        statuses = {r.status for r in results}

        if "error" in statuses:
            overall = "unhealthy"
        elif "degraded" in statuses:
            overall = "degraded"
        else:
            overall = "healthy"

        return HealthReport(
            service=self._service,
            status=overall,
            checks=results,
            uptime_s=time.monotonic() - self._started,
        )
