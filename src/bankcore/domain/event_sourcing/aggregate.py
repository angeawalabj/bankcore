"""
BankCore — Day 21: AccountAggregate & Projections
===================================================
Account as an Event-Sourced aggregate.

AccountAggregate:
  - Has NO persistent state — balance is always computed
  - Rebuilt from events via from_events()
  - Emits new events via commands (deposit, withdraw, transfer)
  - Version tracked for optimistic locking

Projections:
  - AccountProjection: current state (balance, owner, type)
  - BalanceHistoryProjection: balance evolution over time
  - AuditProjection: compliance-grade event log

The key insight:
    account.balance is NOT stored. It's the SUM of all deposits MINUS
    all withdrawals since the account was opened. The EventStore is
    the source of truth. If you distrust the balance, replay the events.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from bankcore.domain.domain_events import (
    DomainEvent, AccountOpened, MoneyDeposited, MoneyWithdrawn,
    MoneyTransferred, InterestApplied, FeeCharged,
)
from bankcore.domain.value_objects import Money, AccountId
from bankcore.domain.event_sourcing.event_store import InProcessEventStore, StoredEvent


# ---------------------------------------------------------------------------
# AccountAggregate — event-sourced account
# ---------------------------------------------------------------------------

class AccountAggregate:
    """
    An account whose state is derived entirely from its event stream.

    No balance column. No state mutations.
    To know the balance: replay all events since AccountOpened.

    Commands produce events. Events mutate state.
    The separation between "produce event" and "apply event" is intentional:
    it allows replaying events from the store without re-executing commands.
    """

    def __init__(self) -> None:
        self._account_id:   Optional[str]   = None
        self._owner_name:   str             = ""
        self._account_type: str             = ""
        self._balance:      float           = 0.0
        self._min_balance:  float           = 0.0
        self._interest_rate: float          = 0.0
        self._version:      int             = 0
        self._pending:      list[DomainEvent] = []   # not yet persisted

    # ------------------------------------------------------------------
    # Reconstruction
    # ------------------------------------------------------------------

    @classmethod
    def from_events(cls, stored_events: list[StoredEvent]) -> "AccountAggregate":
        """Rebuild account state by replaying all stored events."""
        account = cls()
        for stored in stored_events:
            account._apply(stored.event)
            account._version = stored.aggregate_version
        return account

    # ------------------------------------------------------------------
    # Commands — produce events
    # ------------------------------------------------------------------

    def open(
        self,
        account_id: str,
        owner_name: str,
        account_type: str,
        initial_deposit: float,
        interest_rate: float = 0.0,
        min_balance: float = 0.0,
    ) -> "AccountAggregate":
        """Command: open a new account."""
        if self._account_id is not None:
            raise ValueError("Account already opened.")

        event = AccountOpened(
            aggregate_id=AccountId(account_id),
            owner_name=owner_name,
            account_type=account_type,
            initial_deposit=Money.eur(initial_deposit),
        )
        self._record(event)
        return self

    def deposit(self, amount: float, description: str = "Deposit") -> "AccountAggregate":
        """Command: credit the account."""
        if amount <= 0:
            raise ValueError(f"Deposit amount must be positive: {amount}")

        event = MoneyDeposited(
            aggregate_id=AccountId(self._account_id),
            amount=Money.eur(amount),
            description=description,
        )
        self._record(event)
        return self

    def withdraw(self, amount: float, description: str = "Withdrawal") -> "AccountAggregate":
        """Command: debit the account."""
        if amount <= 0:
            raise ValueError(f"Withdrawal amount must be positive: {amount}")
        if self._balance - amount < self._min_balance:
            raise ValueError(
                f"Insufficient funds: balance={self._balance:.2f}, "
                f"amount={amount:.2f}, min={self._min_balance:.2f}"
            )

        event = MoneyWithdrawn(
            aggregate_id=AccountId(self._account_id),
            amount=Money.eur(amount),
            description=description,
        )
        self._record(event)
        return self

    def transfer_out(self, amount: float, to_account_id: str) -> "AccountAggregate":
        """Command: debit for an outgoing transfer."""
        if amount <= 0:
            raise ValueError("Transfer amount must be positive.")
        if self._balance - amount < self._min_balance:
            raise ValueError(
                f"Insufficient funds for transfer: {self._balance:.2f} - {amount:.2f}"
            )

        event = MoneyTransferred(
            aggregate_id=AccountId(self._account_id),
            amount=Money.eur(amount),
            to_account_id=AccountId(to_account_id),
            description=f"Transfer to {to_account_id}",
        )
        self._record(event)
        return self

    def apply_interest(self) -> "AccountAggregate":
        """Command: credit annual interest."""
        if self._interest_rate <= 0:
            raise ValueError("Account has no interest rate.")

        interest = self._balance * self._interest_rate
        event = InterestApplied(
            aggregate_id=AccountId(self._account_id),
            interest_amount=Money.eur(round(interest, 2)),
            rate=self._interest_rate,
        )
        self._record(event)
        return self

    # ------------------------------------------------------------------
    # Event application — pure state mutation
    # ------------------------------------------------------------------

    def _apply(self, event: DomainEvent) -> None:
        """Apply an event to mutate internal state."""
        if isinstance(event, AccountOpened):
            self._account_id   = str(event.aggregate_id)
            self._owner_name   = event.owner_name
            self._account_type = event.account_type
            self._balance      = event.initial_deposit.amount
            # Restore default rates by account type
            if event.account_type == "savings":
                self._interest_rate = 0.025

        elif isinstance(event, MoneyDeposited):
            self._balance += event.amount.amount

        elif isinstance(event, MoneyWithdrawn):
            self._balance -= event.amount.amount

        elif isinstance(event, MoneyTransferred):
            self._balance -= event.amount.amount

        elif isinstance(event, InterestApplied):
            self._balance += event.interest_amount.amount

        elif isinstance(event, FeeCharged):
            self._balance -= event.fee_amount.amount

    def _record(self, event: DomainEvent) -> None:
        """Record a new event: apply immediately + add to pending."""
        self._apply(event)
        self._pending.append(event)

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def pop_pending_events(self) -> list[DomainEvent]:
        """Return and clear pending events (for the store to persist)."""
        events         = list(self._pending)
        self._pending.clear()
        return events

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def account_id(self) -> str:
        return self._account_id or ""

    @property
    def owner_name(self) -> str:
        return self._owner_name

    @property
    def account_type(self) -> str:
        return self._account_type

    @property
    def balance(self) -> float:
        return self._balance

    @property
    def version(self) -> int:
        return self._version

    @property
    def interest_rate(self) -> float:
        return self._interest_rate

    def set_interest_rate(self, rate: float) -> None:
        self._interest_rate = rate

    def set_min_balance(self, min_bal: float) -> None:
        self._min_balance = min_bal


# ---------------------------------------------------------------------------
# Projections
# ---------------------------------------------------------------------------

@dataclass
class AccountSnapshot:
    """Current state of an account as a projection."""
    account_id:   str
    owner_name:   str
    account_type: str
    balance:      float
    version:      int
    event_count:  int
    last_updated: Optional[str] = None


class AccountProjection:
    """
    Computes the current state of an account from its event stream.
    Used for read queries without loading the full aggregate.
    """

    def __init__(self) -> None:
        self._snapshot = AccountSnapshot(
            account_id="", owner_name="", account_type="",
            balance=0.0, version=0, event_count=0,
        )

    def apply(self, stored: StoredEvent) -> None:
        event = stored.event
        snap  = self._snapshot

        if isinstance(event, AccountOpened):
            self._snapshot = AccountSnapshot(
                account_id=str(event.aggregate_id),
                owner_name=event.owner_name,
                account_type=event.account_type,
                balance=event.initial_deposit.amount,
                version=stored.aggregate_version,
                event_count=1,
                last_updated=stored.stored_at.isoformat(),
            )
        else:
            new_balance = snap.balance
            if isinstance(event, (MoneyDeposited, InterestApplied)):
                amount = (event.amount if hasattr(event, "amount")
                          else event.interest_amount)
                new_balance += amount.amount
            elif isinstance(event, (MoneyWithdrawn, MoneyTransferred, FeeCharged)):
                amount = (event.amount if hasattr(event, "amount")
                          else event.fee_amount)
                new_balance -= amount.amount

            self._snapshot = AccountSnapshot(
                account_id=snap.account_id,
                owner_name=snap.owner_name,
                account_type=snap.account_type,
                balance=new_balance,
                version=stored.aggregate_version,
                event_count=snap.event_count + 1,
                last_updated=stored.stored_at.isoformat(),
            )

    @classmethod
    def from_store(
        cls, store: InProcessEventStore, account_id: str
    ) -> "AccountProjection":
        proj = cls()
        for stored in store.get_events(account_id):
            proj.apply(stored)
        return proj

    @property
    def snapshot(self) -> AccountSnapshot:
        return self._snapshot

    @property
    def balance(self) -> float:
        return self._snapshot.balance


@dataclass
class BalancePoint:
    """Balance at a point in time."""
    version:    int
    balance:    float
    event_type: str
    amount:     float
    occurred_at: str


class BalanceHistoryProjection:
    """
    Tracks balance evolution over time for reporting.
    Useful for: charts, anomaly detection, dispute resolution.
    """

    def __init__(self) -> None:
        self._history: list[BalancePoint] = []
        self._balance: float = 0.0

    def apply(self, stored: StoredEvent) -> None:
        event = stored.event
        delta = 0.0

        if isinstance(event, AccountOpened):
            self._balance = event.initial_deposit.amount
            delta         = self._balance
        elif isinstance(event, MoneyDeposited):
            delta          = event.amount.amount
            self._balance += delta
        elif isinstance(event, MoneyWithdrawn):
            delta          = -event.amount.amount
            self._balance += delta
        elif isinstance(event, MoneyTransferred):
            delta          = -event.amount.amount
            self._balance += delta
        elif isinstance(event, InterestApplied):
            delta          = event.interest_amount.amount
            self._balance += delta
        elif isinstance(event, FeeCharged):
            delta          = -event.fee_amount.amount
            self._balance += delta
        else:
            return

        self._history.append(BalancePoint(
            version=stored.aggregate_version,
            balance=round(self._balance, 2),
            event_type=stored.event_type,
            amount=round(delta, 2),
            occurred_at=event.occurred_at.isoformat(),
        ))

    @classmethod
    def from_store(
        cls, store: InProcessEventStore, account_id: str
    ) -> "BalanceHistoryProjection":
        proj = cls()
        for stored in store.get_events(account_id):
            proj.apply(stored)
        return proj

    @property
    def history(self) -> list[BalancePoint]:
        return list(self._history)

    @property
    def current_balance(self) -> float:
        return self._balance

    def balance_at_version(self, version: int) -> Optional[float]:
        for point in reversed(self._history):
            if point.version <= version:
                return point.balance
        return None
