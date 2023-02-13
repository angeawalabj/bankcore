"""
Tests — Day 03: AlertSystem & Observer Pattern
================================================
Test strategy:
  1. Observer subscription/unsubscription mechanics
  2. Event dispatch — correct observers notified
  3. Wildcard subscription ("*") receives all events
  4. Error isolation — one broken observer doesn't stop others
  5. Concrete observers — FraudDetector, BalanceMonitor, AuditLogger
  6. TransactionService integration — publishes correct events
  7. Cross-day integration — ConfigManager thresholds respected
"""

import sys
import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, "src")

from bankcore.config_manager import ConfigManager
from bankcore.account_factory import AccountFactory
from bankcore.alert_system import (
    AlertSystem, AlertObserver,
    FraudDetector, NotificationService, BalanceMonitor, AuditLogger,
)
from bankcore.transaction_service import TransactionService
from bankcore.events import BankEvent, EventType


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

class RecordingObserver(AlertObserver):
    """Test double: records every event it receives."""

    def __init__(self, supported: list[str] = None):
        self._events: list[BankEvent] = []
        self._supported = supported or ["*"]

    def on_event(self, event: BankEvent) -> None:
        self._events.append(event)

    def supported_events(self) -> list[str]:
        return self._supported

    @property
    def received(self) -> list[BankEvent]:
        return list(self._events)

    def received_types(self) -> list[str]:
        return [e.event_type for e in self._events]

    def count(self) -> int:
        return len(self._events)


class BrokenObserver(AlertObserver):
    """Test double: always raises an exception."""

    def on_event(self, event: BankEvent) -> None:
        raise RuntimeError("Simulated observer failure")

    def supported_events(self) -> list[str]:
        return ["*"]


@pytest.fixture(autouse=True)
def reset_state():
    ConfigManager._reset()
    AlertSystem._reset()
    AccountFactory._reset_registry()
    yield
    ConfigManager._reset()
    AlertSystem._reset()
    AccountFactory._reset_registry()


# ---------------------------------------------------------------------------
# AlertSystem — subscription mechanics
# ---------------------------------------------------------------------------

class TestAlertSystemSubscription:

    def test_subscribe_registers_observer(self):
        alerts = AlertSystem.get_instance()
        obs = RecordingObserver()
        alerts.subscribe(EventType.TRANSFER, obs)
        assert alerts.observer_count(EventType.TRANSFER) == 1

    def test_subscribe_same_observer_twice_registers_once(self):
        alerts = AlertSystem.get_instance()
        obs = RecordingObserver()
        alerts.subscribe(EventType.TRANSFER, obs)
        alerts.subscribe(EventType.TRANSFER, obs)
        assert alerts.observer_count(EventType.TRANSFER) == 1

    def test_unsubscribe_removes_observer(self):
        alerts = AlertSystem.get_instance()
        obs = RecordingObserver()
        alerts.subscribe(EventType.TRANSFER, obs)
        alerts.unsubscribe(EventType.TRANSFER, obs)
        assert alerts.observer_count(EventType.TRANSFER) == 0

    def test_subscribe_all_uses_supported_events(self):
        alerts = AlertSystem.get_instance()
        obs = RecordingObserver(supported=[EventType.TRANSFER, EventType.DEPOSIT])
        alerts.subscribe_all(obs)
        assert alerts.observer_count(EventType.TRANSFER) == 1
        assert alerts.observer_count(EventType.DEPOSIT) == 1
        assert alerts.observer_count(EventType.WITHDRAWAL) == 0

    def test_unsubscribe_all_removes_from_all_types(self):
        alerts = AlertSystem.get_instance()
        obs = RecordingObserver(supported=[EventType.TRANSFER, EventType.DEPOSIT])
        alerts.subscribe_all(obs)
        alerts.unsubscribe_all(obs)
        assert alerts.observer_count(EventType.TRANSFER) == 0
        assert alerts.observer_count(EventType.DEPOSIT) == 0


# ---------------------------------------------------------------------------
# AlertSystem — event dispatch
# ---------------------------------------------------------------------------

class TestAlertSystemDispatch:

    def test_publish_notifies_subscribed_observer(self):
        alerts = AlertSystem.get_instance()
        obs = RecordingObserver()
        alerts.subscribe(EventType.TRANSFER, obs)

        event = BankEvent(EventType.TRANSFER, "ACC-001", 500.0)
        alerts.publish(event)

        assert obs.count() == 1
        assert obs.received[0] is event

    def test_publish_does_not_notify_unsubscribed_observer(self):
        alerts = AlertSystem.get_instance()
        obs = RecordingObserver()
        alerts.subscribe(EventType.DEPOSIT, obs)

        alerts.publish(BankEvent(EventType.TRANSFER, "ACC-001", 500.0))

        assert obs.count() == 0

    def test_wildcard_observer_receives_all_events(self):
        alerts = AlertSystem.get_instance()
        obs = RecordingObserver(supported=["*"])
        alerts.subscribe("*", obs)

        alerts.publish(BankEvent(EventType.TRANSFER,   "ACC-001", 100.0))
        alerts.publish(BankEvent(EventType.DEPOSIT,    "ACC-001", 200.0))
        alerts.publish(BankEvent(EventType.WITHDRAWAL, "ACC-001", 50.0))

        assert obs.count() == 3

    def test_multiple_observers_all_notified(self):
        alerts = AlertSystem.get_instance()
        obs_a = RecordingObserver()
        obs_b = RecordingObserver()
        alerts.subscribe(EventType.TRANSFER, obs_a)
        alerts.subscribe(EventType.TRANSFER, obs_b)

        alerts.publish(BankEvent(EventType.TRANSFER, "ACC-001", 500.0))

        assert obs_a.count() == 1
        assert obs_b.count() == 1

    def test_wildcard_plus_specific_observer_no_duplicate(self):
        """An observer subscribed to both specific + wildcard receives event once."""
        alerts = AlertSystem.get_instance()
        obs = RecordingObserver()
        alerts.subscribe(EventType.TRANSFER, obs)
        alerts.subscribe("*", obs)

        alerts.publish(BankEvent(EventType.TRANSFER, "ACC-001", 500.0))

        assert obs.count() == 1   # deduplicated

    def test_publish_returns_notified_count(self):
        alerts = AlertSystem.get_instance()
        obs_a = RecordingObserver()
        obs_b = RecordingObserver()
        alerts.subscribe(EventType.TRANSFER, obs_a)
        alerts.subscribe(EventType.TRANSFER, obs_b)

        count = alerts.publish(BankEvent(EventType.TRANSFER, "ACC-001", 100.0))
        assert count == 2

    def test_publish_increments_counter(self):
        alerts = AlertSystem.get_instance()
        assert alerts.publish_count == 0
        alerts.publish(BankEvent(EventType.TRANSFER, "ACC-001", 100.0))
        alerts.publish(BankEvent(EventType.DEPOSIT,  "ACC-001", 200.0))
        assert alerts.publish_count == 2


# ---------------------------------------------------------------------------
# Error isolation
# ---------------------------------------------------------------------------

class TestErrorIsolation:

    def test_broken_observer_does_not_stop_others(self):
        alerts = AlertSystem.get_instance()
        broken  = BrokenObserver()
        healthy = RecordingObserver()

        alerts.subscribe("*", broken)
        alerts.subscribe("*", healthy)

        # Should not raise — broken observer is silenced
        alerts.publish(BankEvent(EventType.TRANSFER, "ACC-001", 100.0))

        assert healthy.count() == 1

    def test_broken_observer_returns_partial_count(self):
        alerts = AlertSystem.get_instance()
        broken  = BrokenObserver()
        healthy = RecordingObserver()

        alerts.subscribe("*", broken)
        alerts.subscribe("*", healthy)

        count = alerts.publish(BankEvent(EventType.TRANSFER, "ACC-001", 100.0))
        assert count == 1  # only healthy was notified successfully


# ---------------------------------------------------------------------------
# Concrete observers
# ---------------------------------------------------------------------------

class TestAuditLogger:

    def test_records_all_events(self):
        alerts = AlertSystem.get_instance()
        audit  = AuditLogger()
        alerts.subscribe_all(audit)

        alerts.publish(BankEvent(EventType.TRANSFER,   "ACC-001", 100.0))
        alerts.publish(BankEvent(EventType.DEPOSIT,    "ACC-002", 200.0))
        alerts.publish(BankEvent(EventType.WITHDRAWAL, "ACC-001", 50.0))

        assert audit.log_count() == 3

    def test_log_contains_event_info(self):
        alerts = AlertSystem.get_instance()
        audit  = AuditLogger()
        alerts.subscribe_all(audit)

        alerts.publish(BankEvent(EventType.TRANSFER, "ACC-XYZ", 999.0))

        log = audit.get_log()
        assert any("ACC-XYZ" in entry for entry in log)
        assert any("transaction.transfer" in entry for entry in log)

    def test_get_log_returns_copy(self):
        alerts = AlertSystem.get_instance()
        audit  = AuditLogger()
        alerts.subscribe_all(audit)

        alerts.publish(BankEvent(EventType.TRANSFER, "ACC-001", 100.0))
        log = audit.get_log()
        log.clear()  # modify the returned list

        assert audit.log_count() == 1  # internal log unchanged


class TestBalanceMonitor:

    def test_publishes_low_balance_alert(self):
        alerts  = AlertSystem.get_instance()
        monitor = BalanceMonitor()
        recorder = RecordingObserver()

        alerts.subscribe_all(monitor)
        alerts.subscribe(EventType.LOW_BALANCE, recorder)

        # Simulate a transfer that left balance below threshold (100 EUR)
        alerts.publish(BankEvent(
            EventType.TRANSFER, "ACC-001", 500.0,
            metadata={"balance_after": 50.0}
        ))

        assert recorder.count() == 1
        assert recorder.received[0].event_type == EventType.LOW_BALANCE

    def test_no_alert_when_balance_above_threshold(self):
        alerts  = AlertSystem.get_instance()
        monitor = BalanceMonitor()
        recorder = RecordingObserver()

        alerts.subscribe_all(monitor)
        alerts.subscribe(EventType.LOW_BALANCE, recorder)

        alerts.publish(BankEvent(
            EventType.TRANSFER, "ACC-001", 500.0,
            metadata={"balance_after": 500.0}
        ))

        assert recorder.count() == 0

    def test_no_alert_when_balance_missing_from_metadata(self):
        alerts  = AlertSystem.get_instance()
        monitor = BalanceMonitor()
        recorder = RecordingObserver()

        alerts.subscribe_all(monitor)
        alerts.subscribe(EventType.LOW_BALANCE, recorder)

        # No balance_after in metadata
        alerts.publish(BankEvent(EventType.TRANSFER, "ACC-001", 500.0))

        assert recorder.count() == 0

    def test_uses_config_threshold(self):
        config = ConfigManager.get_instance()
        config.set("alerts.low_balance_threshold", 500.0)

        AlertSystem._reset()
        alerts  = AlertSystem.get_instance()
        monitor = BalanceMonitor()
        recorder = RecordingObserver()

        alerts.subscribe_all(monitor)
        alerts.subscribe(EventType.LOW_BALANCE, recorder)

        # balance_after = 300, threshold = 500 → should trigger
        alerts.publish(BankEvent(
            EventType.TRANSFER, "ACC-001", 200.0,
            metadata={"balance_after": 300.0}
        ))

        assert recorder.count() == 1


# ---------------------------------------------------------------------------
# TransactionService integration
# ---------------------------------------------------------------------------

class TestTransactionServiceObserverIntegration:

    def test_transfer_publishes_event(self):
        recorder = RecordingObserver()
        AlertSystem.get_instance().subscribe(EventType.TRANSFER, recorder)

        alice = AccountFactory.create("current", "Alice", 1_000.0)
        bob   = AccountFactory.create("savings", "Bob",   1_000.0)
        service = TransactionService()

        service.transfer(alice, bob, 200.0)

        assert recorder.count() == 1
        event = recorder.received[0]
        assert event.event_type == EventType.TRANSFER
        assert event.amount == 200.0
        assert event.account_id == alice.account_id

    def test_deposit_publishes_event(self):
        recorder = RecordingObserver()
        AlertSystem.get_instance().subscribe(EventType.DEPOSIT, recorder)

        alice   = AccountFactory.create("current", "Alice", 0.0)
        service = TransactionService()
        service.deposit(alice, 300.0)

        assert recorder.count() == 1

    def test_failed_transfer_does_not_publish_event(self):
        recorder = RecordingObserver()
        AlertSystem.get_instance().subscribe(EventType.TRANSFER, recorder)

        alice = AccountFactory.create("current", "Alice", 100.0)
        bob   = AccountFactory.create("savings", "Bob", 1_000.0)
        service = TransactionService()

        result = service.transfer(alice, bob, 5_000.0)  # exceeds Alice's balance

        assert result["success"] is False
        assert recorder.count() == 0

    def test_transfer_metadata_includes_balance_after(self):
        recorder = RecordingObserver()
        AlertSystem.get_instance().subscribe(EventType.TRANSFER, recorder)

        alice = AccountFactory.create("current", "Alice", 1_000.0)
        bob   = AccountFactory.create("savings", "Bob",   1_000.0)
        TransactionService().transfer(alice, bob, 400.0)

        event = recorder.received[0]
        assert "balance_after" in event.metadata
        assert event.metadata["balance_after"] == 600.0
