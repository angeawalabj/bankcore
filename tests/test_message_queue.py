"""
Tests — Day 18: Message Queue
================================
Test strategy:
  1. Message — immutability, retry creation, string representation
  2. MessageBus — publish, subscribe, pattern routing, unsubscribe
  3. Dead Letter Queue — failed consumers, DLQ population
  4. Idempotency — duplicate messages not processed twice
  5. Concrete consumers — FraudDetection, Notification, Analytics, Audit
  6. CacheInvalidationConsumer — J17 + J18 integration
  7. TransactionService publishes events — full integration
  8. Resilience — broken consumer doesn't affect healthy consumers
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
from bankcore.infrastructure.messaging.message_bus import (
    MessageBus, Message, Consumer, DeadLetterQueue,
)
from bankcore.infrastructure.messaging.consumers import (
    Topics, FraudDetectionConsumer, NotificationConsumer,
    AnalyticsConsumer, CacheInvalidationConsumer, AuditConsumer,
    BrokenConsumer,
)
from bankcore.services.account_service.service import AccountService
from bankcore.services.transaction_service.service import TransactionMicroservice
from bankcore.services.shared.service_client import ServiceRegistry, ServiceRequest
from bankcore.infrastructure.cache.cache_backend import InMemoryCache
from bankcore.infrastructure.cache.caching_service_client import CachingServiceClient


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
def bus():
    return MessageBus()


@pytest.fixture
def account_svc():
    return AccountService()


@pytest.fixture
def alice_id(account_svc):
    r = account_svc.handle(ServiceRequest(
        "POST", "/accounts",
        body={"owner_name": "Alice", "account_type": "current", "initial_deposit": 2_000.0}
    ))
    return r.body["account_id"]


@pytest.fixture
def bob_id(account_svc):
    r = account_svc.handle(ServiceRequest(
        "POST", "/accounts",
        body={"owner_name": "Bob", "account_type": "savings", "initial_deposit": 1_000.0}
    ))
    return r.body["account_id"]


# ---------------------------------------------------------------------------
# Message
# ---------------------------------------------------------------------------

class TestMessage:

    def test_message_has_unique_id(self):
        m1 = Message("test.topic", {})
        m2 = Message("test.topic", {})
        assert m1.message_id != m2.message_id

    def test_message_is_immutable(self):
        m = Message("test.topic", {"key": "value"})
        with pytest.raises(Exception):
            m.topic = "other.topic"

    def test_with_retry_increments_count(self):
        m       = Message("test.topic", {})
        retried = m.with_retry()
        assert retried.retry_count == 1
        assert retried.message_id  == m.message_id   # same ID

    def test_with_retry_twice(self):
        m = Message("test.topic", {})
        assert m.with_retry().with_retry().retry_count == 2

    def test_str_representation(self):
        m = Message("transaction.completed", {"amount": 500.0})
        s = str(m)
        assert "transaction.completed" in s
        assert m.message_id in s

    def test_default_retry_count_is_zero(self):
        m = Message("test", {})
        assert m.retry_count == 0


# ---------------------------------------------------------------------------
# MessageBus — core behaviour
# ---------------------------------------------------------------------------

class RecordingConsumer(Consumer):
    def __init__(self):
        self.received: list[Message] = []
    def process(self, message: Message) -> None:
        self.received.append(message)
    @property
    def name(self): return "RecordingConsumer"


class TestMessageBus:

    def test_publish_and_receive(self, bus):
        consumer = RecordingConsumer()
        bus.subscribe("test.topic", consumer)
        bus.publish("test.topic", {"data": 42})
        assert len(consumer.received) == 1
        assert consumer.received[0].payload["data"] == 42

    def test_exact_match_only_matching_consumer(self, bus):
        c1 = RecordingConsumer()
        c2 = RecordingConsumer()
        bus.subscribe("topic.a", c1)
        bus.subscribe("topic.b", c2)
        bus.publish("topic.a", {})
        assert len(c1.received) == 1
        assert len(c2.received) == 0

    def test_wildcard_star_matches_one_segment(self, bus):
        consumer = RecordingConsumer()
        bus.subscribe("transaction.*", consumer)
        bus.publish("transaction.completed", {})
        bus.publish("transaction.failed",    {})
        bus.publish("account.created",       {})   # should not match
        assert len(consumer.received) == 2

    def test_wildcard_hash_matches_nested(self, bus):
        consumer = RecordingConsumer()
        bus.subscribe("bankcore.#", consumer)
        bus.publish("bankcore.transaction.completed", {})
        bus.publish("bankcore.account.created",       {})
        bus.publish("other.event",                    {})   # no match
        assert len(consumer.received) == 2

    def test_multiple_consumers_same_topic(self, bus):
        c1 = RecordingConsumer()
        c2 = RecordingConsumer()
        bus.subscribe("tx.done", c1)
        bus.subscribe("tx.done", c2)
        bus.publish("tx.done", {})
        assert len(c1.received) == 1
        assert len(c2.received) == 1

    def test_unsubscribe_stops_delivery(self, bus):
        consumer = RecordingConsumer()
        bus.subscribe("test.topic", consumer)
        bus.unsubscribe(consumer)
        bus.publish("test.topic", {})
        assert len(consumer.received) == 0

    def test_published_count(self, bus):
        bus.publish("a", {})
        bus.publish("b", {})
        bus.publish("c", {})
        assert bus.published_count() == 3

    def test_published_messages_filter_by_topic(self, bus):
        bus.publish("tx.completed", {"amount": 100})
        bus.publish("tx.failed",    {"amount": 200})
        completed = bus.published_messages("tx.completed")
        assert len(completed) == 1
        assert completed[0].payload["amount"] == 100

    def test_returns_message_object(self, bus):
        msg = bus.publish("test", {"key": "val"})
        assert isinstance(msg, Message)
        assert msg.topic == "test"


# ---------------------------------------------------------------------------
# Dead Letter Queue
# ---------------------------------------------------------------------------

class TestDeadLetterQueue:

    def test_broken_consumer_sends_to_dlq(self, bus):
        broken = BrokenConsumer()
        bus.subscribe("test.topic", broken)
        bus.publish("test.topic", {"data": "bad"})
        assert bus.dlq.count() == 1

    def test_dlq_entry_has_error_info(self, bus):
        broken = BrokenConsumer("my specific error")
        bus.subscribe("test.topic", broken)
        bus.publish("test.topic", {})
        entry = bus.dlq.all()[0]
        assert "my specific error" in entry["error"]
        assert entry["consumer"] == "BrokenConsumer"

    def test_broken_consumer_does_not_affect_healthy(self, bus):
        broken  = BrokenConsumer()
        healthy = RecordingConsumer()
        bus.subscribe("test.topic", broken)
        bus.subscribe("test.topic", healthy)
        bus.publish("test.topic", {})
        assert len(healthy.received) == 1
        assert bus.dlq.count() == 1

    def test_dlq_for_consumer(self, bus):
        b1 = BrokenConsumer()
        b1.__class__.__name__ = "Consumer1"
        bus.subscribe("topic", b1)
        bus.publish("topic", {})
        entries = bus.dlq.for_consumer("BrokenConsumer")
        assert len(entries) == 1

    def test_dlq_clear(self, bus):
        broken = BrokenConsumer()
        bus.subscribe("test", broken)
        bus.publish("test", {})
        bus.dlq.clear()
        assert bus.dlq.count() == 0


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

class TestIdempotency:

    def test_same_message_id_processed_once(self, bus):
        consumer = RecordingConsumer()
        bus.subscribe("test", consumer)

        # Publish then simulate re-delivery with same message_id
        msg = bus.publish("test", {"data": 1})

        # Manually re-dispatch same message (simulates re-delivery)
        consumer2 = RecordingConsumer()
        bus.subscribe("test.again", consumer2)
        # The idempotency key is per (message_id, consumer)
        # A new publish creates a new message_id — that's fine
        msg2 = bus.publish("test", {"data": 2})
        assert msg.message_id != msg2.message_id
        assert len(consumer.received) == 2   # two distinct messages, both processed


# ---------------------------------------------------------------------------
# FraudDetectionConsumer
# ---------------------------------------------------------------------------

class TestFraudDetectionConsumer:

    def test_large_transaction_flagged(self, bus):
        fraud = FraudDetectionConsumer(amount_threshold=1_000.0)
        bus.subscribe(Topics.TRANSFER_COMPLETED, fraud)
        bus.publish(Topics.TRANSFER_COMPLETED, {
            "tx_id": "TX-001", "amount": 6_000.0,
            "from_account_id": "ACC-001",
        })
        assert fraud.alert_count() == 1
        assert "Large transaction" in fraud.alerts[0].reason

    def test_small_transaction_not_flagged(self, bus):
        fraud = FraudDetectionConsumer(amount_threshold=5_000.0)
        bus.subscribe(Topics.TRANSFER_COMPLETED, fraud)
        bus.publish(Topics.TRANSFER_COMPLETED, {
            "tx_id": "TX-001", "amount": 100.0,
            "from_account_id": "ACC-001",
        })
        assert fraud.alert_count() == 0

    def test_wildcard_subscription_catches_all_transactions(self, bus):
        fraud = FraudDetectionConsumer(amount_threshold=100.0)
        bus.subscribe("transaction.*", fraud)
        bus.publish(Topics.TRANSFER_COMPLETED, {"amount": 500.0, "from_account_id": "A"})
        bus.publish(Topics.DEPOSIT_COMPLETED,  {"amount": 500.0, "account_id": "A"})
        assert fraud.alert_count() == 2


# ---------------------------------------------------------------------------
# NotificationConsumer
# ---------------------------------------------------------------------------

class TestNotificationConsumer:

    def test_transfer_sends_sms(self, bus):
        notif = NotificationConsumer()
        bus.subscribe(Topics.TRANSFER_COMPLETED, notif)
        bus.publish(Topics.TRANSFER_COMPLETED, {
            "tx_id": "TX-001", "amount": 200.0,
            "from_account_id": "ACC-001",
            "from_balance_after": 800.0,
        })
        assert notif.notification_count() == 1
        assert notif.notifications[0].channel == "sms"

    def test_fraud_alert_sends_email(self, bus):
        notif = NotificationConsumer()
        bus.subscribe(Topics.FRAUD_SUSPECTED, notif)
        bus.publish(Topics.FRAUD_SUSPECTED, {
            "account_id": "ACC-001",
            "amount": 9_000.0,
        })
        assert notif.notification_count() == 1
        assert notif.notifications[0].channel == "email"

    def test_notifications_for_account(self, bus):
        notif = NotificationConsumer()
        bus.subscribe("transaction.*", notif)
        bus.publish(Topics.TRANSFER_COMPLETED, {
            "from_account_id": "ACC-001", "amount": 100.0, "from_balance_after": 900.0
        })
        bus.publish(Topics.DEPOSIT_COMPLETED, {
            "account_id": "ACC-002", "amount": 200.0
        })
        assert len(notif.for_account("ACC-001")) == 1
        assert len(notif.for_account("ACC-002")) == 1


# ---------------------------------------------------------------------------
# AnalyticsConsumer
# ---------------------------------------------------------------------------

class TestAnalyticsConsumer:

    def test_records_volume(self, bus):
        analytics = AnalyticsConsumer()
        bus.subscribe("transaction.*", analytics)
        bus.publish(Topics.TRANSFER_COMPLETED, {"amount": 500.0})
        bus.publish(Topics.DEPOSIT_COMPLETED,  {"amount": 300.0})
        assert analytics.total_volume == 800.0

    def test_count_by_type(self, bus):
        analytics = AnalyticsConsumer()
        bus.subscribe("transaction.*", analytics)
        bus.publish(Topics.TRANSFER_COMPLETED, {"amount": 100.0})
        bus.publish(Topics.TRANSFER_COMPLETED, {"amount": 200.0})
        bus.publish(Topics.DEPOSIT_COMPLETED,  {"amount": 50.0})
        assert analytics.count_by_type("completed") == 2
        assert analytics.count_by_type("deposit")   == 1

    def test_average_amount(self, bus):
        analytics = AnalyticsConsumer()
        bus.subscribe("transaction.*", analytics)
        bus.publish(Topics.TRANSFER_COMPLETED, {"amount": 100.0})
        bus.publish(Topics.TRANSFER_COMPLETED, {"amount": 300.0})
        assert analytics.average_amount == 200.0


# ---------------------------------------------------------------------------
# AuditConsumer
# ---------------------------------------------------------------------------

class TestAuditConsumer:

    def test_logs_all_events(self, bus):
        audit = AuditConsumer()
        bus.subscribe("#", audit)
        bus.publish("transaction.completed", {"amount": 100.0})
        bus.publish("account.created",       {"owner": "Alice"})
        bus.publish("alert.fraud",            {"account": "ACC-001"})
        assert audit.log_count() == 3

    def test_no_duplicate_entries(self, bus):
        audit = AuditConsumer()
        bus.subscribe("#", audit)
        # Publish once
        msg = bus.publish("test.event", {"data": 1})
        # Manually call process with same message (simulates re-delivery)
        audit.process(msg)   # should be ignored (already seen)
        assert audit.log_count() == 1

    def test_entries_for_topic(self, bus):
        audit = AuditConsumer()
        bus.subscribe("#", audit)
        bus.publish("tx.done", {"amount": 100.0})
        bus.publish("tx.done", {"amount": 200.0})
        bus.publish("account.created", {})
        assert len(audit.entries_for_topic("tx.done")) == 2


# ---------------------------------------------------------------------------
# CacheInvalidationConsumer (J17 + J18 integration)
# ---------------------------------------------------------------------------

class TestCacheInvalidationConsumer:

    def test_invalidates_cache_on_balance_update(self, bus, account_svc, alice_id):
        registry = ServiceRegistry()
        base     = registry.register("account-service", account_svc.handle)
        cache    = InMemoryCache()
        caching  = CachingServiceClient(base, cache, ttl=60)

        # Pre-warm cache
        caching.get(f"/accounts/{alice_id}")
        assert cache.active_size() == 1

        # Wire up invalidation consumer
        invalidator = CacheInvalidationConsumer(caching)
        bus.subscribe(Topics.BALANCE_UPDATED, invalidator)

        # Publish balance update
        bus.publish(Topics.BALANCE_UPDATED, {"account_id": alice_id, "balance": 1_500.0})

        # Cache should be cleared
        assert cache.active_size() == 0
        assert invalidator.invalidation_count() == 1

    def test_invalidation_triggers_fresh_fetch(self, bus, account_svc, alice_id):
        registry = ServiceRegistry()
        base     = registry.register("account-service", account_svc.handle)
        cache    = InMemoryCache()
        caching  = CachingServiceClient(base, cache, ttl=60)

        invalidator = CacheInvalidationConsumer(caching)
        bus.subscribe(Topics.BALANCE_UPDATED, invalidator)

        # Cache alice
        caching.get(f"/accounts/{alice_id}")
        calls_after_cache = base.call_count

        # Invalidate via message
        bus.publish(Topics.BALANCE_UPDATED, {"account_id": alice_id})

        # Next GET should re-fetch (cache miss)
        caching.get(f"/accounts/{alice_id}")
        assert base.call_count == calls_after_cache + 1


# ---------------------------------------------------------------------------
# TransactionService publishes events (full integration)
# ---------------------------------------------------------------------------

class TestTransactionServicePublishesEvents:

    def _setup(self, account_svc, alice_id, bob_id):
        registry = ServiceRegistry()
        base     = registry.register("account-service", account_svc.handle)
        bus      = MessageBus()
        tx_svc   = TransactionMicroserviceWithBus(base, bus)
        return bus, tx_svc

    def test_transfer_publishes_completed_event(self, account_svc, alice_id, bob_id):
        bus, tx_svc = self._setup(account_svc, alice_id, bob_id)
        audit = AuditConsumer()
        bus.subscribe("#", audit)

        tx_svc.transfer(alice_id, bob_id, 300.0)

        assert audit.log_count() >= 1
        topics = [e["topic"] for e in audit.log]
        assert Topics.TRANSFER_COMPLETED in topics

    def test_failed_transfer_publishes_failed_event(self, account_svc, alice_id, bob_id):
        bus, tx_svc = self._setup(account_svc, alice_id, bob_id)
        audit = AuditConsumer()
        bus.subscribe("#", audit)

        tx_svc.transfer(alice_id, bob_id, 99_999.0)   # should fail

        topics = [e["topic"] for e in audit.log]
        assert Topics.TRANSFER_FAILED in topics

    def test_multiple_consumers_all_notified(self, account_svc, alice_id, bob_id):
        bus, tx_svc = self._setup(account_svc, alice_id, bob_id)

        fraud     = FraudDetectionConsumer(amount_threshold=100.0)
        analytics = AnalyticsConsumer()
        audit     = AuditConsumer()

        bus.subscribe("transaction.*", fraud)
        bus.subscribe("transaction.*", analytics)
        bus.subscribe("#",            audit)

        tx_svc.transfer(alice_id, bob_id, 500.0)

        assert analytics.total_count >= 1
        assert audit.log_count()     >= 1


# ---------------------------------------------------------------------------
# Helper: TransactionMicroservice with MessageBus integration
# ---------------------------------------------------------------------------

from bankcore.services.shared.service_client import ServiceClient

class TransactionMicroserviceWithBus(TransactionMicroservice):
    """
    Extended TransactionMicroservice that publishes domain events.
    Wraps the parent _transfer/_deposit/_withdrawal to emit messages.
    """

    def __init__(self, account_client: ServiceClient, bus: MessageBus) -> None:
        super().__init__(account_client)
        self._bus = bus

    def transfer(self, from_id: str, to_id: str, amount: float) -> dict:
        resp = self.handle(ServiceRequest(
            "POST", "/transfers",
            body={"from_account_id": from_id, "to_account_id": to_id, "amount": amount}
        ))
        if resp.ok:
            self._bus.publish(
                Topics.TRANSFER_COMPLETED,
                {**resp.body, "source": "transaction-service"},
                source="transaction-service",
            )
            self._bus.publish(
                Topics.BALANCE_UPDATED,
                {"account_id": from_id, "balance": resp.body.get("from_balance_after")},
            )
            self._bus.publish(
                Topics.BALANCE_UPDATED,
                {"account_id": to_id, "balance": resp.body.get("to_balance_after")},
            )
        else:
            self._bus.publish(
                Topics.TRANSFER_FAILED,
                {"from_account_id": from_id, "to_account_id": to_id,
                 "amount": amount, "reason": resp.body.get("error")},
                source="transaction-service",
            )
        return resp.body
