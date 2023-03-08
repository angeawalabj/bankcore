"""
BankCore — Day 20: Metrics Collector
=======================================
Lightweight in-process metrics system.

Design: no external dependency (no Prometheus client library).
Interface is identical to what a real Prometheus client would expose —
swapping to prometheus_client = changing the backend, not the API.

Metric types:
  - Counter: monotonically increasing (total transfers, total errors)
  - Gauge: can go up and down (active accounts, queue depth)
  - Histogram: distribution of values (latency, amount sizes)

Usage:
    metrics = MetricsRegistry.get_instance()
    metrics.counter("transfers_total").inc()
    metrics.gauge("active_accounts").set(42)
    metrics.histogram("transfer_latency_ms").observe(234.5)
"""

from __future__ import annotations
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Counter
# ---------------------------------------------------------------------------

class Counter:
    """Monotonically increasing metric. Never decreases."""

    def __init__(self, name: str, description: str = "") -> None:
        self.name        = name
        self.description = description
        self._value      = 0.0
        self._lock       = threading.Lock()

    def inc(self, amount: float = 1.0) -> None:
        if amount < 0:
            raise ValueError("Counter can only increase.")
        with self._lock:
            self._value += amount

    @property
    def value(self) -> float:
        return self._value

    def reset(self) -> None:
        """For testing only."""
        with self._lock:
            self._value = 0.0

    def __repr__(self) -> str:
        return f"Counter({self.name}={self._value})"


# ---------------------------------------------------------------------------
# Gauge
# ---------------------------------------------------------------------------

class Gauge:
    """A metric that can go up and down."""

    def __init__(self, name: str, description: str = "") -> None:
        self.name        = name
        self.description = description
        self._value      = 0.0
        self._lock       = threading.Lock()

    def set(self, value: float) -> None:
        with self._lock:
            self._value = value

    def inc(self, amount: float = 1.0) -> None:
        with self._lock:
            self._value += amount

    def dec(self, amount: float = 1.0) -> None:
        with self._lock:
            self._value -= amount

    @property
    def value(self) -> float:
        return self._value

    def __repr__(self) -> str:
        return f"Gauge({self.name}={self._value})"


# ---------------------------------------------------------------------------
# Histogram
# ---------------------------------------------------------------------------

class Histogram:
    """
    Tracks the distribution of observed values.

    Provides:
    - count: number of observations
    - sum: total of all values
    - percentile(p): approximate Pth percentile
    - buckets: distribution across predefined bounds
    """

    DEFAULT_BUCKETS = [1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000]

    def __init__(
        self,
        name: str,
        description: str = "",
        buckets: list[float] = None,
    ) -> None:
        self.name        = name
        self.description = description
        self._buckets    = sorted(buckets or self.DEFAULT_BUCKETS)
        self._values:    list[float] = []
        self._sum        = 0.0
        self._lock       = threading.Lock()

    def observe(self, value: float) -> None:
        with self._lock:
            self._values.append(value)
            self._sum += value

    @property
    def count(self) -> int:
        return len(self._values)

    @property
    def sum(self) -> float:
        return self._sum

    @property
    def mean(self) -> float:
        if not self._values:
            return 0.0
        return self._sum / len(self._values)

    def percentile(self, p: float) -> float:
        """Return approximate Pth percentile (0-100)."""
        if not self._values:
            return 0.0
        sorted_vals = sorted(self._values)
        idx = int(len(sorted_vals) * p / 100)
        idx = min(idx, len(sorted_vals) - 1)
        return sorted_vals[idx]

    def bucket_counts(self) -> dict[float, int]:
        """Return count of values <= each bucket boundary."""
        counts = {}
        for bound in self._buckets:
            counts[bound] = sum(1 for v in self._values if v <= bound)
        return counts

    def __repr__(self) -> str:
        return f"Histogram({self.name}: count={self.count}, mean={self.mean:.2f})"


# ---------------------------------------------------------------------------
# MetricsRegistry — Singleton
# ---------------------------------------------------------------------------

class MetricsRegistry:
    """
    Central registry for all BankCore metrics.
    Singleton pattern (Day 01) — one registry per process.
    """

    _instance: Optional["MetricsRegistry"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._counters:   dict[str, Counter]   = {}
        self._gauges:     dict[str, Gauge]     = {}
        self._histograms: dict[str, Histogram] = {}

    @classmethod
    def get_instance(cls) -> "MetricsRegistry":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
                    cls._instance._register_bankcore_defaults()
        return cls._instance

    @classmethod
    def _reset(cls) -> None:
        with cls._lock:
            cls._instance = None

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def counter(self, name: str, description: str = "") -> Counter:
        if name not in self._counters:
            self._counters[name] = Counter(name, description)
        return self._counters[name]

    def gauge(self, name: str, description: str = "") -> Gauge:
        if name not in self._gauges:
            self._gauges[name] = Gauge(name, description)
        return self._gauges[name]

    def histogram(self, name: str, description: str = "") -> Histogram:
        if name not in self._histograms:
            self._histograms[name] = Histogram(name, description)
        return self._histograms[name]

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def snapshot(self) -> dict:
        """Return all current metric values as a dict."""
        return {
            "counters": {
                name: m.value for name, m in self._counters.items()
            },
            "gauges": {
                name: m.value for name, m in self._gauges.items()
            },
            "histograms": {
                name: {
                    "count": m.count,
                    "sum":   m.sum,
                    "mean":  m.mean,
                    "p50":   m.percentile(50),
                    "p95":   m.percentile(95),
                    "p99":   m.percentile(99),
                }
                for name, m in self._histograms.items()
            },
        }

    def _register_bankcore_defaults(self) -> None:
        """Pre-register all BankCore metrics with descriptions."""
        self.counter("transfers_total",       "Total number of completed transfers")
        self.counter("transfers_failed_total","Total number of failed transfers")
        self.counter("deposits_total",        "Total number of deposits")
        self.counter("withdrawals_total",     "Total number of withdrawals")
        self.counter("cache_hits_total",      "Cache hits")
        self.counter("cache_misses_total",    "Cache misses")
        self.counter("queue_messages_total",  "Messages published to queue")
        self.counter("dlq_messages_total",    "Messages sent to dead letter queue")
        self.gauge("active_accounts",         "Number of active accounts")
        self.gauge("queue_dlq_depth",         "Dead letter queue depth")
        self.histogram("transfer_latency_ms", "Transfer end-to-end latency in ms")
        self.histogram("transfer_amount_eur", "Transfer amounts in EUR")
        self.histogram("cache_latency_ms",    "Cache lookup latency in ms")
