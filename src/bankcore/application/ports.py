"""
BankCore — Day 12: Application Ports
======================================
Ports are interfaces defined by the Application layer.
Infrastructure implements them (Adapters).

This is the Clean Architecture's dependency inversion at the architecture level:
  - Application layer DEFINES what it needs (Port)
  - Infrastructure layer PROVIDES it (Adapter)
  - Application never imports from Infrastructure

The Application layer says: "I need something that can save and find accounts."
It does NOT say: "I need SQLAlchemy" or "I need a dict."
That's the Infrastructure's concern.

Day 14 (Repository Pattern) will add SQLite and In-Memory adapters.
Day 15 (Hexagonal Architecture) will add CLI and API adapters.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Optional, List, TYPE_CHECKING

if TYPE_CHECKING:
    from bankcore.account import Account
    from bankcore.domain.domain_events import DomainEvent


class AccountRepositoryPort(ABC):
    """
    Port: what the Application layer needs to persist accounts.

    This interface is defined HERE (Application), not in Infrastructure.
    Infrastructure implements it — Application never knows which implementation
    is active at runtime.

    This is the Repository Pattern (Day 14) as a Clean Architecture Port.
    """

    @abstractmethod
    def save(self, account: "Account") -> None:
        """Persist or update an account."""

    @abstractmethod
    def find_by_id(self, account_id: str) -> Optional["Account"]:
        """Return the account with this ID, or None if not found."""

    @abstractmethod
    def find_all(self) -> List["Account"]:
        """Return all accounts."""

    @abstractmethod
    def find_by_owner(self, owner_name: str) -> List["Account"]:
        """Return all accounts belonging to an owner."""

    @abstractmethod
    def count(self) -> int:
        """Return total number of accounts."""

    @abstractmethod
    def exists(self, account_id: str) -> bool:
        """Check if an account exists without loading it."""


class NotificationPort(ABC):
    """
    Port: what the Application layer needs to send notifications.

    The Application publishes domain events — it does NOT know
    whether they become SMS, emails, Kafka messages, or test spies.
    Infrastructure decides.
    """

    @abstractmethod
    def notify(self, event: "DomainEvent") -> None:
        """Dispatch a domain event to all registered handlers."""


class DomainEventStorePort(ABC):
    """
    Port: what Event Sourcing (Day 21) needs to persist domain events.

    Defined here so Use Cases can depend on it today —
    the full implementation arrives at Day 21.
    """

    @abstractmethod
    def append(self, event: "DomainEvent") -> None:
        """Append a domain event to the store."""

    @abstractmethod
    def get_events_for(self, aggregate_id: str) -> List["DomainEvent"]:
        """Return all events for an aggregate, in order."""
