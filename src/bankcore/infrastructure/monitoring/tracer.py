"""
BankCore — Day 20: Distributed Tracer
=======================================
Tracks requests as they flow through BankCore's microservices.

A Trace is a tree of Spans:
  - Trace: the entire journey of one request (e.g. one transfer)
  - Span: one unit of work within the trace (e.g. GET /accounts/{id})

Each span records:
  - service name, operation name
  - start time, end time, duration
  - parent span ID (for tree reconstruction)
  - tags: key-value metadata (http.status, db.table, etc.)
  - error flag

Trace context propagation (for HTTP headers):
  - X-Trace-ID: shared across all services for one request
  - X-Span-ID: current span, becomes parent for downstream calls

Usage:
    tracer = Tracer("account-service")

    with tracer.start_span("GET /accounts/{id}") as span:
        span.set_tag("account_id", account_id)
        result = do_work()
        span.set_tag("http.status", 200)
    # span auto-finished on context exit

    # Access the completed trace
    trace = tracer.get_trace(trace_id)
"""

from __future__ import annotations
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


# ---------------------------------------------------------------------------
# Span
# ---------------------------------------------------------------------------

@dataclass
class Span:
    """
    A single timed operation within a trace.
    Represents one unit of work: one HTTP call, one DB query, one cache lookup.
    """
    span_id:    str
    trace_id:   str
    operation:  str
    service:    str
    parent_id:  Optional[str] = None
    started_at: float         = field(default_factory=time.monotonic)
    finished_at: Optional[float] = None
    tags:       dict          = field(default_factory=dict)
    error:      bool          = False
    error_msg:  str           = ""

    @property
    def duration_ms(self) -> float:
        if self.finished_at is None:
            return (time.monotonic() - self.started_at) * 1000
        return (self.finished_at - self.started_at) * 1000

    @property
    def is_finished(self) -> bool:
        return self.finished_at is not None

    def finish(self) -> None:
        self.finished_at = time.monotonic()

    def set_tag(self, key: str, value) -> "Span":
        self.tags[key] = value
        return self

    def set_error(self, message: str) -> "Span":
        self.error     = True
        self.error_msg = message
        return self

    def to_dict(self) -> dict:
        return {
            "span_id":     self.span_id,
            "trace_id":    self.trace_id,
            "parent_id":   self.parent_id,
            "operation":   self.operation,
            "service":     self.service,
            "duration_ms": round(self.duration_ms, 2),
            "error":       self.error,
            "error_msg":   self.error_msg,
            "tags":        self.tags,
        }


# ---------------------------------------------------------------------------
# Trace
# ---------------------------------------------------------------------------

@dataclass
class Trace:
    """Collection of spans for one request."""
    trace_id:   str
    spans:      list[Span] = field(default_factory=list)
    created_at: datetime   = field(default_factory=datetime.now)

    def add_span(self, span: Span) -> None:
        self.spans.append(span)

    @property
    def total_duration_ms(self) -> float:
        if not self.spans:
            return 0.0
        return sum(s.duration_ms for s in self.spans)

    @property
    def root_span(self) -> Optional[Span]:
        return next((s for s in self.spans if s.parent_id is None), None)

    @property
    def has_errors(self) -> bool:
        return any(s.error for s in self.spans)

    @property
    def error_spans(self) -> list[Span]:
        return [s for s in self.spans if s.error]

    def span_count(self) -> int:
        return len(self.spans)

    def to_dict(self) -> dict:
        return {
            "trace_id":          self.trace_id,
            "span_count":        self.span_count(),
            "total_duration_ms": round(self.total_duration_ms, 2),
            "has_errors":        self.has_errors,
            "spans":             [s.to_dict() for s in self.spans],
        }

    def summary(self) -> str:
        root = self.root_span
        op   = root.operation if root else "unknown"
        return (
            f"Trace({self.trace_id[:8]}) "
            f"op={op} "
            f"spans={self.span_count()} "
            f"duration={self.total_duration_ms:.1f}ms "
            f"{'ERROR' if self.has_errors else 'OK'}"
        )


# ---------------------------------------------------------------------------
# Tracer
# ---------------------------------------------------------------------------

class Tracer:
    """
    Distributed tracer for one microservice.

    Maintains a thread-local active span so nested operations
    automatically get the correct parent span ID.

    Usage:
        tracer = Tracer("transaction-service")

        # As context manager (recommended)
        with tracer.start_span("transfer") as span:
            span.set_tag("amount", 500.0)
            # nested span automatically gets parent_id
            with tracer.start_span("GET /accounts/{id}") as child:
                child.set_tag("account_id", "ACC-001")
    """

    def __init__(self, service_name: str) -> None:
        self._service    = service_name
        self._traces:    dict[str, Trace] = {}
        self._lock       = threading.Lock()
        self._local      = threading.local()   # thread-local active span

    def new_trace(self) -> str:
        """Create a new trace and return its ID."""
        trace_id = str(uuid.uuid4())[:12].upper()
        with self._lock:
            self._traces[trace_id] = Trace(trace_id=trace_id)
        return trace_id

    def start_span(
        self,
        operation: str,
        trace_id:  Optional[str] = None,
        parent_id: Optional[str] = None,
    ) -> "SpanContext":
        """
        Start a span. Use as a context manager for automatic finish.

        If no trace_id provided, creates a new trace.
        If no parent_id provided, uses the thread-local active span.
        """
        if trace_id is None:
            trace_id = self.new_trace()

        # Use thread-local active span as parent if not specified
        active = getattr(self._local, "active_span", None)
        if parent_id is None and active is not None:
            parent_id = active.span_id

        span = Span(
            span_id=str(uuid.uuid4())[:8].upper(),
            trace_id=trace_id,
            operation=operation,
            service=self._service,
            parent_id=parent_id,
        )

        with self._lock:
            if trace_id not in self._traces:
                self._traces[trace_id] = Trace(trace_id=trace_id)
            self._traces[trace_id].add_span(span)

        return SpanContext(span, self)

    def _set_active(self, span: Optional[Span]) -> None:
        self._local.active_span = span

    def _get_active(self) -> Optional[Span]:
        return getattr(self._local, "active_span", None)

    def get_trace(self, trace_id: str) -> Optional[Trace]:
        return self._traces.get(trace_id)

    def all_traces(self) -> list[Trace]:
        return list(self._traces.values())

    def recent_traces(self, n: int = 10) -> list[Trace]:
        traces = sorted(self._traces.values(), key=lambda t: t.created_at, reverse=True)
        return traces[:n]

    def error_traces(self) -> list[Trace]:
        return [t for t in self._traces.values() if t.has_errors]

    def trace_count(self) -> int:
        return len(self._traces)

    def clear(self) -> None:
        with self._lock:
            self._traces.clear()


class SpanContext:
    """Context manager wrapper for Span."""

    def __init__(self, span: Span, tracer: Tracer) -> None:
        self._span   = span
        self._tracer = tracer
        self._prev_active: Optional[Span] = None

    def __enter__(self) -> Span:
        self._prev_active = self._tracer._get_active()
        self._tracer._set_active(self._span)
        return self._span

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if exc_type is not None:
            self._span.set_error(str(exc_val))
        self._span.finish()
        self._tracer._set_active(self._prev_active)
        return False   # don't suppress exceptions
