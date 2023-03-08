"""
Tests — Day 20: Monitoring
============================
Test strategy:
  1. Counter — inc, thread safety, no decrease
  2. Gauge — set/inc/dec
  3. Histogram — observe, percentiles, buckets
  4. MetricsRegistry — singleton, snapshot, pre-registered defaults
  5. Span — creation, tags, errors, duration, finish
  6. Trace — span tree, has_errors, total_duration
  7. Tracer — new_trace, start_span, context manager, nested spans
  8. HealthCheck — each check type
  9. HealthChecker — composite, status aggregation
  10. Integration — metrics recorded during service calls
"""

import sys
import time
import threading
import pytest

sys.path.insert(0, "src")

from bankcore.config_manager import ConfigManager
from bankcore.account_factory import AccountFactory
from bankcore.alert_system import AlertSystem
from bankcore.account_type_registry import AccountTypeRegistry
from bankcore.infrastructure.monitoring.metrics import (
    Counter, Gauge, Histogram, MetricsRegistry,
)
from bankcore.infrastructure.monitoring.tracer import (
    Span, Trace, Tracer, SpanContext,
)
from bankcore.infrastructure.monitoring.health_check import (
    CheckResult, HealthCheck, HealthChecker, HealthReport,
    RepositoryHealthCheck, CacheHealthCheck,
    MessageBusHealthCheck, MetricsHealthCheck,
)
from bankcore.infrastructure.cache.cache_backend import InMemoryCache
from bankcore.infrastructure.messaging.message_bus import MessageBus
from bankcore.infrastructure.persistence.in_memory_repository import (
    InMemoryAccountRepository,
)


@pytest.fixture(autouse=True)
def reset_state():
    ConfigManager._reset()
    AlertSystem._reset()
    AccountTypeRegistry._reset()
    AccountTypeRegistry._register_defaults()
    AccountFactory._reset_registry()
    MetricsRegistry._reset()
    yield
    ConfigManager._reset()
    AlertSystem._reset()
    AccountTypeRegistry._reset()
    AccountTypeRegistry._register_defaults()
    AccountFactory._reset_registry()
    MetricsRegistry._reset()


# ---------------------------------------------------------------------------
# Counter
# ---------------------------------------------------------------------------

class TestCounter:

    def test_initial_value_zero(self):
        c = Counter("test")
        assert c.value == 0.0

    def test_inc_default(self):
        c = Counter("test")
        c.inc()
        assert c.value == 1.0

    def test_inc_custom_amount(self):
        c = Counter("test")
        c.inc(5.0)
        assert c.value == 5.0

    def test_inc_accumulates(self):
        c = Counter("test")
        c.inc(3.0)
        c.inc(2.0)
        assert c.value == 5.0

    def test_negative_inc_raises(self):
        c = Counter("test")
        with pytest.raises(ValueError):
            c.inc(-1.0)

    def test_thread_safety(self):
        c      = Counter("test")
        errors = []

        def worker():
            try:
                for _ in range(100):
                    c.inc()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads: t.start()
        for t in threads: t.join()

        assert errors == []
        assert c.value == 1000.0

    def test_repr(self):
        c = Counter("transfers_total")
        c.inc(42)
        assert "transfers_total" in repr(c)
        assert "42" in repr(c)


# ---------------------------------------------------------------------------
# Gauge
# ---------------------------------------------------------------------------

class TestGauge:

    def test_set(self):
        g = Gauge("active_accounts")
        g.set(100)
        assert g.value == 100.0

    def test_inc(self):
        g = Gauge("active_accounts")
        g.set(10)
        g.inc(5)
        assert g.value == 15.0

    def test_dec(self):
        g = Gauge("active_accounts")
        g.set(10)
        g.dec(3)
        assert g.value == 7.0

    def test_can_go_negative(self):
        g = Gauge("balance")
        g.set(-500.0)
        assert g.value == -500.0

    def test_dec_default_amount(self):
        g = Gauge("count")
        g.set(5)
        g.dec()
        assert g.value == 4.0


# ---------------------------------------------------------------------------
# Histogram
# ---------------------------------------------------------------------------

class TestHistogram:

    def test_observe_and_count(self):
        h = Histogram("latency")
        h.observe(10.0)
        h.observe(20.0)
        h.observe(30.0)
        assert h.count == 3

    def test_sum(self):
        h = Histogram("latency")
        h.observe(100.0)
        h.observe(200.0)
        assert h.sum == 300.0

    def test_mean(self):
        h = Histogram("latency")
        h.observe(100.0)
        h.observe(200.0)
        assert h.mean == 150.0

    def test_mean_empty(self):
        h = Histogram("latency")
        assert h.mean == 0.0

    def test_percentile_p50(self):
        h = Histogram("latency")
        for v in [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]:
            h.observe(float(v))
        p50 = h.percentile(50)
        # 10 values: sorted index = int(10*50/100) = 5 → value = 60
        assert 40 <= p50 <= 70

    def test_percentile_p99(self):
        h = Histogram("latency")
        for v in range(1, 101):
            h.observe(float(v))
        p99 = h.percentile(99)
        assert p99 >= 95

    def test_bucket_counts(self):
        h = Histogram("latency", buckets=[10, 50, 100])
        h.observe(5.0)
        h.observe(25.0)
        h.observe(75.0)
        h.observe(150.0)
        counts = h.bucket_counts()
        assert counts[10]  == 1   # only 5
        assert counts[50]  == 2   # 5 and 25
        assert counts[100] == 3   # 5, 25, 75

    def test_repr(self):
        h = Histogram("transfer_latency_ms")
        h.observe(250.0)
        assert "transfer_latency_ms" in repr(h)
        assert "count=1" in repr(h)


# ---------------------------------------------------------------------------
# MetricsRegistry
# ---------------------------------------------------------------------------

class TestMetricsRegistry:

    def test_singleton(self):
        r1 = MetricsRegistry.get_instance()
        r2 = MetricsRegistry.get_instance()
        assert r1 is r2

    def test_reset_creates_new_instance(self):
        r1 = MetricsRegistry.get_instance()
        MetricsRegistry._reset()
        r2 = MetricsRegistry.get_instance()
        assert r1 is not r2

    def test_counter_registered_and_retrieved(self):
        r = MetricsRegistry.get_instance()
        c = r.counter("test_counter", "A test counter")
        c.inc(5)
        assert r.counter("test_counter").value == 5.0

    def test_gauge_registered_and_retrieved(self):
        r = MetricsRegistry.get_instance()
        g = r.gauge("test_gauge")
        g.set(42)
        assert r.gauge("test_gauge").value == 42.0

    def test_histogram_registered_and_retrieved(self):
        r = MetricsRegistry.get_instance()
        h = r.histogram("test_hist")
        h.observe(100.0)
        assert r.histogram("test_hist").count == 1

    def test_default_metrics_pre_registered(self):
        r        = MetricsRegistry.get_instance()
        snapshot = r.snapshot()
        assert "transfers_total"        in snapshot["counters"]
        assert "transfers_failed_total" in snapshot["counters"]
        assert "active_accounts"        in snapshot["gauges"]
        assert "transfer_latency_ms"    in snapshot["histograms"]

    def test_snapshot_structure(self):
        r        = MetricsRegistry.get_instance()
        snapshot = r.snapshot()
        assert "counters"   in snapshot
        assert "gauges"     in snapshot
        assert "histograms" in snapshot

    def test_snapshot_histogram_fields(self):
        r = MetricsRegistry.get_instance()
        r.histogram("latency").observe(100.0)
        snap = r.snapshot()
        h    = snap["histograms"]["latency"]
        assert "count" in h
        assert "mean"  in h
        assert "p50"   in h
        assert "p95"   in h
        assert "p99"   in h


# ---------------------------------------------------------------------------
# Span
# ---------------------------------------------------------------------------

class TestSpan:

    def test_span_creation(self):
        s = Span(span_id="S1", trace_id="T1", operation="test_op", service="svc")
        assert s.span_id   == "S1"
        assert s.trace_id  == "T1"
        assert s.operation == "test_op"

    def test_span_duration_before_finish(self):
        s = Span(span_id="S1", trace_id="T1", operation="op", service="svc")
        time.sleep(0.01)
        assert s.duration_ms > 5

    def test_span_finish(self):
        s = Span(span_id="S1", trace_id="T1", operation="op", service="svc")
        s.finish()
        assert s.is_finished is True
        duration = s.duration_ms
        time.sleep(0.01)
        assert s.duration_ms == duration   # frozen after finish

    def test_set_tag(self):
        s = Span(span_id="S1", trace_id="T1", operation="op", service="svc")
        s.set_tag("http.status", 200)
        assert s.tags["http.status"] == 200

    def test_set_error(self):
        s = Span(span_id="S1", trace_id="T1", operation="op", service="svc")
        s.set_error("Connection refused")
        assert s.error is True
        assert "Connection refused" in s.error_msg

    def test_to_dict(self):
        s = Span(span_id="S1", trace_id="T1", operation="op", service="svc")
        s.set_tag("key", "val")
        s.finish()
        d = s.to_dict()
        assert "span_id" in d
        assert "duration_ms" in d
        assert "tags" in d

    def test_chained_set_tag(self):
        s = Span(span_id="S1", trace_id="T1", operation="op", service="svc")
        result = s.set_tag("a", 1).set_tag("b", 2)
        assert result is s
        assert s.tags == {"a": 1, "b": 2}


# ---------------------------------------------------------------------------
# Tracer
# ---------------------------------------------------------------------------

class TestTracer:

    def test_new_trace_returns_id(self):
        tracer   = Tracer("test-service")
        trace_id = tracer.new_trace()
        assert isinstance(trace_id, str)
        assert len(trace_id) > 0

    def test_start_span_creates_span(self):
        tracer = Tracer("test-service")
        ctx    = tracer.start_span("my-operation")
        with ctx as span:
            assert span.operation == "my-operation"
            assert span.service   == "test-service"

    def test_span_auto_finishes_on_context_exit(self):
        tracer = Tracer("test-service")
        with tracer.start_span("op") as span:
            pass
        assert span.is_finished

    def test_span_captures_exception(self):
        tracer = Tracer("test-service")
        with pytest.raises(ValueError):
            with tracer.start_span("op") as span:
                raise ValueError("test error")
        assert span.error is True
        assert "test error" in span.error_msg

    def test_nested_spans_get_parent_id(self):
        tracer = Tracer("test-service")
        with tracer.start_span("parent") as parent:
            with tracer.start_span("child") as child:
                pass
        assert child.parent_id == parent.span_id

    def test_get_trace(self):
        tracer   = Tracer("test-service")
        trace_id = tracer.new_trace()
        with tracer.start_span("op", trace_id=trace_id):
            pass
        trace = tracer.get_trace(trace_id)
        assert trace is not None
        assert trace.span_count() == 1

    def test_trace_has_errors_when_span_errors(self):
        tracer = Tracer("test-service")
        with pytest.raises(RuntimeError):
            with tracer.start_span("op") as span:
                raise RuntimeError("fail")
        traces = tracer.all_traces()
        assert any(t.has_errors for t in traces)

    def test_multiple_spans_in_one_trace(self):
        tracer   = Tracer("test-service")
        trace_id = tracer.new_trace()
        with tracer.start_span("span1", trace_id=trace_id): pass
        with tracer.start_span("span2", trace_id=trace_id): pass
        with tracer.start_span("span3", trace_id=trace_id): pass
        trace = tracer.get_trace(trace_id)
        assert trace.span_count() == 3

    def test_trace_summary(self):
        tracer   = Tracer("svc")
        trace_id = tracer.new_trace()
        with tracer.start_span("transfer", trace_id=trace_id): pass
        trace   = tracer.get_trace(trace_id)
        summary = trace.summary()
        assert "transfer" in summary
        assert trace_id[:8] in summary

    def test_error_traces_filter(self):
        tracer = Tracer("svc")
        with tracer.start_span("ok_op"): pass
        with pytest.raises(ValueError):
            with tracer.start_span("bad_op"): raise ValueError("x")
        assert len(tracer.error_traces()) == 1


# ---------------------------------------------------------------------------
# Health Checks
# ---------------------------------------------------------------------------

class TestHealthChecks:

    def test_repository_check_ok(self):
        repo  = InMemoryAccountRepository()
        check = RepositoryHealthCheck(repo)
        result = check.check()
        assert result.status == "ok"
        assert result.is_healthy

    def test_repository_check_shows_count(self):
        repo  = InMemoryAccountRepository()
        repo.save(AccountFactory.create("current", "Alice", 100.0))
        check  = RepositoryHealthCheck(repo)
        result = check.check()
        assert result.details["account_count"] == 1

    def test_cache_check_ok(self):
        cache  = InMemoryCache()
        check  = CacheHealthCheck(cache)
        result = check.check()
        assert result.status == "ok"
        assert "hit_rate" in result.details

    def test_cache_check_latency_recorded(self):
        cache  = InMemoryCache()
        check  = CacheHealthCheck(cache)
        result = check.check()
        assert result.latency_ms >= 0

    def test_message_bus_check_ok(self):
        bus    = MessageBus()
        check  = MessageBusHealthCheck(bus)
        result = check.check()
        assert result.status == "ok"

    def test_message_bus_check_degraded_on_dlq(self):
        from bankcore.infrastructure.messaging.consumers import BrokenConsumer
        bus     = MessageBus()
        broken  = BrokenConsumer()
        bus.subscribe("test", broken)
        for _ in range(15):
            bus.publish("test", {})
        check  = MessageBusHealthCheck(bus)
        result = check.check()
        assert result.status in ("degraded", "error")

    def test_metrics_check_ok_at_zero_errors(self):
        registry = MetricsRegistry.get_instance()
        registry.counter("transfers_total").inc(100)
        # no failures → error rate = 0
        check  = MetricsHealthCheck(registry)
        result = check.check()
        assert result.status == "ok"

    def test_metrics_check_degraded_on_high_error_rate(self):
        registry = MetricsRegistry.get_instance()
        registry.counter("transfers_total").inc(100)
        registry.counter("transfers_failed_total").inc(10)  # 10% > 5% threshold
        check  = MetricsHealthCheck(registry)
        result = check.check()
        assert result.status in ("degraded", "error")


# ---------------------------------------------------------------------------
# HealthChecker — composite
# ---------------------------------------------------------------------------

class TestHealthChecker:

    def test_all_ok_is_healthy(self):
        repo    = InMemoryAccountRepository()
        checker = HealthChecker("test-service")
        checker.add_check("db", RepositoryHealthCheck(repo))
        checker.add_check("cache", CacheHealthCheck(InMemoryCache()))
        report  = checker.check()
        assert report.status == "healthy"
        assert report.is_healthy

    def test_one_error_is_unhealthy(self):
        class AlwaysError(HealthCheck):
            def check(self):
                return CheckResult("bad", "error", message="boom")

        checker = HealthChecker("test-service")
        checker.add_check("good", RepositoryHealthCheck(InMemoryAccountRepository()))
        checker.add_check("bad",  AlwaysError())
        report  = checker.check()
        assert report.status == "unhealthy"
        assert not report.is_healthy

    def test_one_degraded_is_degraded(self):
        class Degraded(HealthCheck):
            def check(self):
                return CheckResult("warn", "degraded", message="slow")

        checker = HealthChecker("test-service")
        checker.add_check("ok",      RepositoryHealthCheck(InMemoryAccountRepository()))
        checker.add_check("warning", Degraded())
        report  = checker.check()
        assert report.status == "degraded"

    def test_report_to_dict(self):
        checker = HealthChecker("account-service")
        checker.add_check("db", RepositoryHealthCheck(InMemoryAccountRepository(), name="db"))
        report  = checker.check()
        d       = report.to_dict()
        assert "service"    in d
        assert "status"     in d
        assert "checks"     in d
        assert "uptime_s"   in d
        assert "db" in d["checks"]

    def test_uptime_increases(self):
        checker = HealthChecker("svc")
        r1 = checker.check()
        time.sleep(0.05)
        r2 = checker.check()
        assert r2.uptime_s > r1.uptime_s

    def test_chained_add_check(self):
        repo    = InMemoryAccountRepository()
        checker = (HealthChecker("svc")
                   .add_check("db",    RepositoryHealthCheck(repo))
                   .add_check("cache", CacheHealthCheck(InMemoryCache())))
        report  = checker.check()
        assert len(report.checks) == 2
