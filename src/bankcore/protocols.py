"""
BankCore — Day 10: Protocols (DIP)
=====================================
Structural interfaces for injectable dependencies.

Why Protocol instead of ABC?
  - ConfigManager, AlertSystem exist and work — we don't want to force them
    to inherit from a new ABC just to be injectable.
  - Protocol uses structural (duck) typing: any object with the right methods
    satisfies the protocol, without explicit declaration.
  - This means FakeConfig in tests just needs .get() and .set() — done.

These protocols are the "abstractions" in DIP:
  - High-level modules (TransactionService) depend on these protocols
  - Low-level modules (ConfigManager, AlertSystem) satisfy them structurally
  - Test doubles satisfy them too — zero patching of globals

Usage:
    def __init__(self, config: ConfigProtocol, alerts: AlertProtocol): ...

    # Production
    service = TransactionService(ConfigManager.get_instance(), AlertSystem.get_instance())

    # Test
    service = TransactionService(FakeConfig(), SpyAlertSystem())
"""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ConfigProtocol(Protocol):
    """
    Structural protocol for configuration providers.
    ConfigManager satisfies this without modification.
    FakeConfig in tests satisfies this with just .get() and .set().
    """

    def get(self, key: str, default: Any = None) -> Any:
        """Return the configuration value for key, or default."""
        ...

    def set(self, key: str, value: Any) -> None:
        """Set or override a configuration value."""
        ...


@runtime_checkable
class AlertProtocol(Protocol):
    """
    Structural protocol for event publishing systems.
    AlertSystem satisfies this without modification.
    SpyAlertSystem in tests records events without side effects.
    """

    def publish(self, event: Any) -> int:
        """Publish an event. Returns the number of observers notified."""
        ...

    def subscribe(self, event_type: str, observer: Any) -> None:
        """Register an observer for an event type."""
        ...


@runtime_checkable
class EventBuilderProtocol(Protocol):
    """
    Structural protocol for event construction.
    EventBuilder satisfies this without modification.
    """

    @staticmethod
    def transfer_event(from_account: Any, to_account: Any, amount: float) -> Any:
        ...

    @staticmethod
    def deposit_event(account: Any, amount: float) -> Any:
        ...

    @staticmethod
    def withdrawal_event(account: Any, amount: float) -> Any:
        ...


# ---------------------------------------------------------------------------
# Test doubles — lightweight fakes for DIP-based testing
# ---------------------------------------------------------------------------

class FakeConfig:
    """
    In-memory configuration for testing.
    Satisfies ConfigProtocol structurally.
    No ConfigManager, no Singleton, no file system.
    """

    def __init__(self, initial: dict | None = None) -> None:
        self._data: dict = dict(initial or {})
        # Sensible test defaults
        self._data.setdefault("limits.max_transfer_amount", 50_000.0)
        self._data.setdefault("limits.max_daily_transactions", 20)
        self._data.setdefault("alerts.low_balance_threshold", 100.0)
        self._data.setdefault("alerts.large_transaction_threshold", 5_000.0)
        self._data.setdefault("environment", "test")

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def all(self) -> dict:
        return dict(self._data)


class SpyAlertSystem:
    """
    Recording alert system for testing.
    Captures all published events without triggering real observers.
    Satisfies AlertProtocol structurally.
    """

    def __init__(self) -> None:
        self._published: list = []
        self._subscriptions: dict[str, list] = {}

    def publish(self, event: Any) -> int:
        self._published.append(event)
        return 0   # no real observers

    def subscribe(self, event_type: str, observer: Any) -> None:
        self._subscriptions.setdefault(event_type, []).append(observer)

    def subscribe_all(self, observer: Any) -> None:
        pass   # no-op in tests

    def unsubscribe(self, event_type: str, observer: Any) -> None:
        pass

    def unsubscribe_all(self, observer: Any) -> None:
        pass

    # Inspection helpers for assertions
    @property
    def events(self) -> list:
        return list(self._published)

    def event_count(self) -> int:
        return len(self._published)

    def events_of_type(self, event_type: str) -> list:
        return [e for e in self._published if e.event_type == event_type]

    def was_published(self, event_type: str) -> bool:
        return any(e.event_type == event_type for e in self._published)

    def clear(self) -> None:
        self._published.clear()
