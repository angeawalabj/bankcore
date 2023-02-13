"""
BankCore — Day 03: Observer Pattern — AlertSystem
===================================================
AlertSystem: the event bus that decouples TransactionService from its reactions.

How it works:
  1. Services publish BankEvent instances to AlertSystem
  2. AlertSystem dispatches each event to all registered observers
  3. Observers react independently — they don't know about each other

Design decisions:
  - Singleton (Day 01 pattern): one AlertSystem shared by all services
  - Observers subscribe by event type — no observer receives events it ignores
  - Errors in one observer do NOT stop others — bank operations are resilient
  - Wildcard subscription (*) available for audit logging

Trade-off: synchronous dispatch. If NotificationService is slow, TransactionService
waits. This will be resolved in Day 18 with async message queues.
"""

import threading
from abc import ABC, abstractmethod
from typing import Callable

from bankcore.config_manager import ConfigManager
from bankcore.events import BankEvent, EventType


# ---------------------------------------------------------------------------
# Observer interface
# ---------------------------------------------------------------------------

class AlertObserver(ABC):
    """
    Base class for all AlertSystem observers.

    Day 09 (ISP): AlertObserver implements EventHandler (mandatory on_event)
    and EventFilter (optional supported_events). Both are available on all
    observers — subclasses that only care about specific events override
    supported_events(); those that want all events use the default ["*"].
    """
    from bankcore.interfaces import EventHandler, EventFilter

    @abstractmethod
    def on_event(self, event: BankEvent) -> None:
        """React to a bank event. Must not raise exceptions."""

    def supported_events(self) -> list[str]:
        """
        Override to subscribe only to specific event types.
        Return ["*"] to receive all events (e.g., AuditLogger).
        Default: subscribe to all events.
        """
        return ["*"]

    @property
    def name(self) -> str:
        return self.__class__.__name__


# ---------------------------------------------------------------------------
# AlertSystem — the Observable (Singleton)
# ---------------------------------------------------------------------------

class AlertSystem:
    """
    Central event bus for BankCore.

    Usage:
        alerts = AlertSystem.get_instance()
        alerts.subscribe(EventType.TRANSFER, my_observer)
        alerts.publish(BankEvent("transaction.transfer", "ACC-001", 500.0))
    """

    _instance: "AlertSystem | None" = None
    _lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        # Maps event_type → list of observers
        # "*" key receives all events (wildcard)
        self._observers: dict[str, list[AlertObserver]] = {}
        self._publish_count: int = 0

    @classmethod
    def get_instance(cls) -> "AlertSystem":
        """Thread-safe Singleton — same pattern as ConfigManager (Day 01)."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    # Subscription management
    # ------------------------------------------------------------------

    def subscribe(self, event_type: str, observer: AlertObserver) -> None:
        """
        Register an observer for a specific event type.
        Use "*" as event_type to receive all events.
        """
        if event_type not in self._observers:
            self._observers[event_type] = []
        if observer not in self._observers[event_type]:
            self._observers[event_type].append(observer)

    def subscribe_all(self, observer: AlertObserver) -> None:
        """
        Register an observer for all event types it declares
        via supported_events(). Convenience method.
        """
        for event_type in observer.supported_events():
            self.subscribe(event_type, observer)

    def unsubscribe(self, event_type: str, observer: AlertObserver) -> None:
        """Remove an observer from a specific event type."""
        if event_type in self._observers:
            self._observers[event_type] = [
                o for o in self._observers[event_type] if o is not observer
            ]

    def unsubscribe_all(self, observer: AlertObserver) -> None:
        """Remove an observer from all event types."""
        for event_type in list(self._observers.keys()):
            self.unsubscribe(event_type, observer)

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------

    def publish(self, event: BankEvent) -> int:
        """
        Dispatch an event to all registered observers.

        Observers for the specific event type AND wildcard observers ("*")
        both receive the event.

        Returns the number of observers notified.

        Error policy: if one observer raises, log it and continue.
        A broken NotificationService must not block fraud detection.
        """
        self._publish_count += 1
        notified = 0

        # Collect observers: specific type + wildcard
        targets: list[AlertObserver] = []
        targets.extend(self._observers.get(event.event_type, []))
        targets.extend(self._observers.get("*", []))

        # Deduplicate — an observer may have subscribed to both
        seen = set()
        unique_targets = []
        for obs in targets:
            if id(obs) not in seen:
                seen.add(id(obs))
                unique_targets.append(obs)

        for observer in unique_targets:
            try:
                observer.on_event(event)
                notified += 1
            except Exception as exc:
                # Log but don't propagate — resilience over completeness
                print(f"[AlertSystem] ERROR in {observer.name}: {exc}")

        return notified

    def observer_count(self, event_type: str = "*") -> int:
        """Return how many observers are registered for an event type."""
        return len(self._observers.get(event_type, []))

    @property
    def publish_count(self) -> int:
        return self._publish_count

    @classmethod
    def _reset(cls) -> None:
        """For testing only."""
        with cls._lock:
            cls._instance = None


# ---------------------------------------------------------------------------
# Register AlertObserver as implementing EventHandler + EventFilter (Day 09 — ISP)
# ---------------------------------------------------------------------------
from bankcore.interfaces import EventHandler, EventFilter
EventHandler.register(AlertObserver)
EventFilter.register(AlertObserver)


# ---------------------------------------------------------------------------
# Concrete Observers
# ---------------------------------------------------------------------------

class FraudDetector(AlertObserver):
    """
    Monitors transactions for suspicious patterns.
    Publishes a secondary "alert.fraud_suspected" event if fraud is detected.

    Current rules (simple — Day 21 will add ML-based detection):
      - Transfer > large_transaction_threshold
      - More than 3 transactions on the same account in 60 seconds
    """

    def __init__(self) -> None:
        self._recent: dict[str, list] = {}   # account_id → [timestamps]
        self._config = ConfigManager.get_instance()

    def supported_events(self) -> list[str]:
        return [EventType.TRANSFER, EventType.WITHDRAWAL]

    def on_event(self, event: BankEvent) -> None:
        self._check_large_amount(event)
        self._check_rapid_succession(event)

    def _check_large_amount(self, event: BankEvent) -> None:
        threshold = self._config.get("alerts.large_transaction_threshold", 5_000.0)
        if event.amount > threshold:
            alert = BankEvent(
                event_type=EventType.LARGE_TRANSACTION,
                account_id=event.account_id,
                amount=event.amount,
                metadata={"original_event": event.event_type, "threshold": threshold},
            )
            print(f"[FraudDetector] LARGE TRANSACTION: {event.amount:.2f} EUR "
                  f"on account {event.account_id}")
            AlertSystem.get_instance().publish(alert)

    def _check_rapid_succession(self, event: BankEvent) -> None:
        from datetime import datetime, timedelta
        now = datetime.now()
        account_id = event.account_id

        if account_id not in self._recent:
            self._recent[account_id] = []

        # Keep only transactions in the last 60 seconds
        self._recent[account_id] = [
            t for t in self._recent[account_id]
            if now - t < timedelta(seconds=60)
        ]
        self._recent[account_id].append(now)

        if len(self._recent[account_id]) > 3:
            print(f"[FraudDetector] RAPID TRANSACTIONS DETECTED "
                  f"on account {account_id}: "
                  f"{len(self._recent[account_id])} in 60s")


class NotificationService(AlertObserver):
    """
    Sends notifications to account holders.
    Currently prints to stdout — Day 18 will route through a message queue.
    """

    def supported_events(self) -> list[str]:
        return [
            EventType.TRANSFER,
            EventType.DEPOSIT,
            EventType.LOW_BALANCE,
            EventType.LARGE_TRANSACTION,
        ]

    def on_event(self, event: BankEvent) -> None:
        if event.is_type(EventType.TRANSFER):
            print(f"[NotificationService] SMS → Account {event.account_id}: "
                  f"Transfer of {event.amount:.2f} EUR processed.")

        elif event.is_type(EventType.DEPOSIT):
            print(f"[NotificationService] SMS → Account {event.account_id}: "
                  f"Deposit of {event.amount:.2f} EUR received.")

        elif event.is_type(EventType.LOW_BALANCE):
            threshold = event.metadata.get("threshold", 0)
            print(f"[NotificationService] EMAIL → Account {event.account_id}: "
                  f"Low balance alert! Balance below {threshold:.2f} EUR.")

        elif event.is_type(EventType.LARGE_TRANSACTION):
            print(f"[NotificationService] EMAIL → Account {event.account_id}: "
                  f"Large transaction of {event.amount:.2f} EUR — was this you?")


class BalanceMonitor(AlertObserver):
    """
    Watches account balances after every debit operation.
    Publishes a LOW_BALANCE alert event when balance drops below threshold.
    """

    def __init__(self) -> None:
        self._config = ConfigManager.get_instance()

    def supported_events(self) -> list[str]:
        return [EventType.TRANSFER, EventType.WITHDRAWAL]

    def on_event(self, event: BankEvent) -> None:
        balance = event.metadata.get("balance_after")
        if balance is None:
            return

        threshold = self._config.get("alerts.low_balance_threshold", 100.0)
        if balance < threshold:
            alert = BankEvent(
                event_type=EventType.LOW_BALANCE,
                account_id=event.account_id,
                amount=balance,
                metadata={"threshold": threshold},
            )
            AlertSystem.get_instance().publish(alert)


class AuditLogger(AlertObserver):
    """
    Records every bank event for compliance and debugging.
    Subscribes to ALL events via wildcard "*".

    Day 21 will make this write to an immutable append-only log.
    """

    def __init__(self) -> None:
        self._log: list[str] = []

    def supported_events(self) -> list[str]:
        return ["*"]   # Receives everything

    def on_event(self, event: BankEvent) -> None:
        entry = (
            f"{event.timestamp.strftime('%Y-%m-%d %H:%M:%S')} | "
            f"{event.event_type:30} | "
            f"account={event.account_id} | "
            f"amount={event.amount:>12.2f}"
        )
        self._log.append(entry)

    def get_log(self) -> list[str]:
        return list(self._log)

    def log_count(self) -> int:
        return len(self._log)
