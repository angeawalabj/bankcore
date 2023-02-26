"""
BankCore — Day 12: Domain Events
==================================
Domain Events represent things that happened in the domain.

Difference from BankEvent (Day 03):
  - BankEvent: infrastructure event published to AlertSystem (observers)
  - DomainEvent: pure domain fact, belongs to the innermost circle

Domain Events are:
  - Immutable (frozen=True)
  - Named in past tense ("MoneyTransferred", not "TransferMoney")
  - Rich with domain data (Money, AccountId) — not raw floats and strings
  - Collected by aggregate roots, dispatched by the Application layer

This separation allows the Domain to be tested with zero infrastructure:
no AlertSystem, no ConfigManager, no observers needed.

Day 21 (Event Sourcing) will use DomainEvents as the primary
persistence mechanism — the account's state is rebuilt from its events.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

from bankcore.domain.value_objects import Money, AccountId


@dataclass(frozen=True)
class DomainEvent:
    """
    Base class for all domain events.

    Every domain event has:
      - event_id: unique identifier for deduplication and idempotency
      - occurred_at: when this event happened
      - aggregate_id: which entity produced this event
    """
    aggregate_id: AccountId
    event_id:     str      = field(default_factory=lambda: str(uuid4())[:8].upper())
    occurred_at:  datetime = field(default_factory=datetime.now)

    @property
    def event_type(self) -> str:
        """Class name used for routing and logging."""
        return self.__class__.__name__

    def to_dict(self) -> dict:
        return {
            "event_type":   self.event_type,
            "event_id":     self.event_id,
            "aggregate_id": str(self.aggregate_id),
            "occurred_at":  self.occurred_at.isoformat(),
        }


@dataclass(frozen=True)
class AccountOpened(DomainEvent):
    """An account was opened with an initial deposit."""
    owner_name:      str   = ""
    account_type:    str   = ""
    initial_deposit: Money = field(default_factory=lambda: Money.zero())

    def to_dict(self) -> dict:
        return {
            **super().to_dict(),
            "owner_name":      self.owner_name,
            "account_type":    self.account_type,
            "initial_deposit": str(self.initial_deposit),
        }


@dataclass(frozen=True)
class MoneyDeposited(DomainEvent):
    """Money was credited to an account."""
    amount:      Money  = field(default_factory=lambda: Money.zero())
    description: str    = "Deposit"

    def to_dict(self) -> dict:
        return {**super().to_dict(), "amount": str(self.amount), "description": self.description}


@dataclass(frozen=True)
class MoneyWithdrawn(DomainEvent):
    """Money was debited from an account."""
    amount:      Money  = field(default_factory=lambda: Money.zero())
    description: str    = "Withdrawal"

    def to_dict(self) -> dict:
        return {**super().to_dict(), "amount": str(self.amount), "description": self.description}


@dataclass(frozen=True)
class MoneyTransferred(DomainEvent):
    """
    Funds moved from one account to another.
    The aggregate_id is the SOURCE account.
    """
    amount:          Money     = field(default_factory=lambda: Money.zero())
    to_account_id:   AccountId = field(default_factory=AccountId.generate)
    description:     str       = "Transfer"

    def to_dict(self) -> dict:
        return {
            **super().to_dict(),
            "amount":        str(self.amount),
            "to_account_id": str(self.to_account_id),
            "description":   self.description,
        }


@dataclass(frozen=True)
class InterestApplied(DomainEvent):
    """Annual interest was credited to a savings account."""
    interest_amount: Money = field(default_factory=lambda: Money.zero())
    rate:            float = 0.0

    def to_dict(self) -> dict:
        return {
            **super().to_dict(),
            "interest_amount": str(self.interest_amount),
            "rate":            f"{self.rate * 100:.2f}%",
        }


@dataclass(frozen=True)
class FeeCharged(DomainEvent):
    """A fee was deducted from an account."""
    fee_amount:    Money = field(default_factory=lambda: Money.zero())
    fee_type:      str   = "standard"
    strategy_name: str   = ""

    def to_dict(self) -> dict:
        return {
            **super().to_dict(),
            "fee_amount": str(self.fee_amount),
            "fee_type":   self.fee_type,
        }
