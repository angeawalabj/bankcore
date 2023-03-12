"""
BankCore — Day 22: CQRS
==========================
Separates the write path (Commands) from the read path (Queries).

Write path: Command → CommandHandler → EventStore (J21)
Read path:  Query → QueryHandler → ReadModel (in-memory projection)

Key property: ReadModels are updated asynchronously from EventStore.
This enables independent scaling and optimization of reads vs writes.

Connection to previous days:
  - J21 (EventStore): commands append events, read models project them
  - J18 (MessageBus): events are published to update read models
  - J11 (Commands): same Command pattern, now routed through CQRS handlers
  - J14 (Specifications): queries use specs for filtering
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from bankcore.domain.event_sourcing.event_store import InProcessEventStore
from bankcore.domain.event_sourcing.aggregate import AccountAggregate
from bankcore.domain.domain_events import (
    AccountOpened, MoneyDeposited, MoneyWithdrawn,
    MoneyTransferred, InterestApplied,
)
from bankcore.domain.value_objects import AccountId, Money


# ---------------------------------------------------------------------------
# Base classes
# ---------------------------------------------------------------------------

class Command(ABC):
    """Base for all write-side commands."""

    @property
    def command_type(self) -> str:
        return self.__class__.__name__


class Query(ABC):
    """Base for all read-side queries."""

    @property
    def query_type(self) -> str:
        return self.__class__.__name__


@dataclass(frozen=True)
class CommandResult:
    """Result of a command execution."""
    success:    bool
    aggregate_id: str = ""
    version:    int   = 0
    error:      str   = ""

    @classmethod
    def ok(cls, aggregate_id: str, version: int) -> "CommandResult":
        return cls(success=True, aggregate_id=aggregate_id, version=version)

    @classmethod
    def fail(cls, error: str) -> "CommandResult":
        return cls(success=False, error=error)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OpenAccountCommand(Command):
    account_id:      str
    owner_name:      str
    account_type:    str
    initial_deposit: float
    interest_rate:   float = 0.0
    min_balance:     float = 0.0


@dataclass(frozen=True)
class DepositCommand(Command):
    account_id:  str
    amount:      float
    description: str = "Deposit"


@dataclass(frozen=True)
class WithdrawCommand(Command):
    account_id:  str
    amount:      float
    description: str = "Withdrawal"


@dataclass(frozen=True)
class TransferCommand(Command):
    from_account_id: str
    to_account_id:   str
    amount:          float
    description:     str = "Transfer"


@dataclass(frozen=True)
class ApplyInterestCommand(Command):
    account_id: str


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GetBalanceQuery(Query):
    account_id: str


@dataclass(frozen=True)
class GetAccountSummaryQuery(Query):
    account_id: str


@dataclass(frozen=True)
class ListAccountsQuery(Query):
    page:      int   = 1
    page_size: int   = 20
    owner:     str   = ""
    actype:    str   = ""


@dataclass(frozen=True)
class GetTransactionHistoryQuery(Query):
    account_id: str
    limit:      int = 50


# ---------------------------------------------------------------------------
# Read Models
# ---------------------------------------------------------------------------

@dataclass
class BalanceReadModel:
    """Optimized for fast balance lookups."""
    account_id:   str
    balance:      float
    version:      int
    last_updated: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class AccountSummaryReadModel:
    """Optimized for dashboard/list views."""
    account_id:    str
    owner_name:    str
    account_type:  str
    balance:       float
    tx_count:      int
    version:       int
    opened_at:     str = ""
    last_activity: str = ""


@dataclass
class TransactionRecord:
    """One entry in the transaction history read model."""
    event_type:  str
    amount:      float
    balance_after: float
    description: str
    occurred_at: str
    version:     int


class TransactionHistoryReadModel:
    """Ordered list of transactions for an account."""

    def __init__(self, account_id: str) -> None:
        self.account_id = account_id
        self._records:  list[TransactionRecord] = []
        self._balance   = 0.0

    def add(self, record: TransactionRecord) -> None:
        self._records.append(record)
        self._balance = record.balance_after

    @property
    def records(self) -> list[TransactionRecord]:
        return list(reversed(self._records))   # newest first

    @property
    def current_balance(self) -> float:
        return self._balance

    def count(self) -> int:
        return len(self._records)


# ---------------------------------------------------------------------------
# Read Model Store — in-memory projection cache
# ---------------------------------------------------------------------------

class ReadModelStore:
    """
    In-memory store of all read models.
    Updated by ProjectionUpdater when events arrive.
    Queried by QueryHandler for fast reads.
    """

    def __init__(self) -> None:
        self._balances:   dict[str, BalanceReadModel]             = {}
        self._summaries:  dict[str, AccountSummaryReadModel]      = {}
        self._histories:  dict[str, TransactionHistoryReadModel]  = {}

    # Writes (called by ProjectionUpdater)
    def update_balance(self, model: BalanceReadModel) -> None:
        self._balances[model.account_id] = model

    def update_summary(self, model: AccountSummaryReadModel) -> None:
        self._summaries[model.account_id] = model

    def add_transaction(self, account_id: str, record: TransactionRecord) -> None:
        if account_id not in self._histories:
            self._histories[account_id] = TransactionHistoryReadModel(account_id)
        self._histories[account_id].add(record)

    # Reads (called by QueryHandler)
    def get_balance(self, account_id: str) -> Optional[BalanceReadModel]:
        return self._balances.get(account_id)

    def get_summary(self, account_id: str) -> Optional[AccountSummaryReadModel]:
        return self._summaries.get(account_id)

    def get_history(self, account_id: str) -> Optional[TransactionHistoryReadModel]:
        return self._histories.get(account_id)

    def all_summaries(self) -> list[AccountSummaryReadModel]:
        return list(self._summaries.values())

    def account_count(self) -> int:
        return len(self._summaries)


# ---------------------------------------------------------------------------
# ProjectionUpdater — event → read model
# ---------------------------------------------------------------------------

class ProjectionUpdater:
    """
    Listens to events and updates Read Models.
    In production: runs in a separate process, consuming from MessageBus.
    Here: called synchronously after each command for simplicity.
    """

    def __init__(self, store: ReadModelStore) -> None:
        self._store = store

    def apply(self, event, version: int) -> None:
        """Apply a domain event to all relevant read models."""
        agg_id = str(event.aggregate_id)

        if isinstance(event, AccountOpened):
            balance = event.initial_deposit.amount
            self._store.update_balance(BalanceReadModel(
                account_id=agg_id, balance=balance, version=version,
            ))
            self._store.update_summary(AccountSummaryReadModel(
                account_id=agg_id,
                owner_name=event.owner_name,
                account_type=event.account_type,
                balance=balance,
                tx_count=1,
                version=version,
                opened_at=event.occurred_at.isoformat(),
                last_activity=event.occurred_at.isoformat(),
            ))
            self._store.add_transaction(agg_id, TransactionRecord(
                event_type="AccountOpened",
                amount=balance,
                balance_after=balance,
                description="Account opened",
                occurred_at=event.occurred_at.isoformat(),
                version=version,
            ))

        elif isinstance(event, (MoneyDeposited, MoneyWithdrawn,
                                MoneyTransferred, InterestApplied)):
            self._update_financial(event, version, agg_id)

    def _update_financial(self, event, version: int, agg_id: str) -> None:
        """Update balance and summary for financial events."""
        current_balance = self._store.get_balance(agg_id)
        bal = current_balance.balance if current_balance else 0.0

        if isinstance(event, MoneyDeposited):
            delta = event.amount.amount
            desc  = event.description
            etype = "Deposit"
        elif isinstance(event, MoneyWithdrawn):
            delta = -event.amount.amount
            desc  = event.description
            etype = "Withdrawal"
        elif isinstance(event, MoneyTransferred):
            delta = -event.amount.amount
            desc  = f"Transfer to {event.to_account_id}"
            etype = "Transfer"
        elif isinstance(event, InterestApplied):
            delta = event.interest_amount.amount
            desc  = f"Interest {event.rate * 100:.2f}%"
            etype = "Interest"
        else:
            return

        new_bal = bal + delta
        self._store.update_balance(BalanceReadModel(
            account_id=agg_id, balance=new_bal, version=version,
        ))
        summary = self._store.get_summary(agg_id)
        if summary:
            summary.balance      = new_bal
            summary.tx_count    += 1
            summary.version      = version
            summary.last_activity = event.occurred_at.isoformat()

        self._store.add_transaction(agg_id, TransactionRecord(
            event_type=etype,
            amount=abs(delta),
            balance_after=new_bal,
            description=desc,
            occurred_at=event.occurred_at.isoformat(),
            version=version,
        ))


# ---------------------------------------------------------------------------
# CommandHandler — write side
# ---------------------------------------------------------------------------

class AccountCommandHandler:
    """
    Handles all account write commands.
    Loads aggregate from EventStore, applies command, persists new events.
    """

    def __init__(
        self,
        event_store: InProcessEventStore,
        projection_updater: ProjectionUpdater,
    ) -> None:
        self._store   = event_store
        self._updater = projection_updater

    def handle(self, command: Command) -> CommandResult:
        try:
            if isinstance(command, OpenAccountCommand):
                return self._open(command)
            if isinstance(command, DepositCommand):
                return self._deposit(command)
            if isinstance(command, WithdrawCommand):
                return self._withdraw(command)
            if isinstance(command, TransferCommand):
                return self._transfer(command)
            if isinstance(command, ApplyInterestCommand):
                return self._apply_interest(command)
            return CommandResult.fail(f"Unknown command: {command.command_type}")
        except Exception as e:
            return CommandResult.fail(str(e))

    def _open(self, cmd: OpenAccountCommand) -> CommandResult:
        account = AccountAggregate()
        account.open(
            cmd.account_id, cmd.owner_name, cmd.account_type,
            cmd.initial_deposit,
        )
        # Set rates after open (they're stored in aggregate config, not events)
        if cmd.interest_rate:
            account.set_interest_rate(cmd.interest_rate)
        if cmd.min_balance:
            account.set_min_balance(cmd.min_balance)
        return self._persist(account)

    def _deposit(self, cmd: DepositCommand) -> CommandResult:
        account = self._load(cmd.account_id)
        if account is None:
            return CommandResult.fail(f"Account {cmd.account_id} not found.")
        account.deposit(cmd.amount, cmd.description)
        return self._persist(account)

    def _withdraw(self, cmd: WithdrawCommand) -> CommandResult:
        account = self._load(cmd.account_id)
        if account is None:
            return CommandResult.fail(f"Account {cmd.account_id} not found.")
        account.withdraw(cmd.amount, cmd.description)
        return self._persist(account)

    def _transfer(self, cmd: TransferCommand) -> CommandResult:
        from_acc = self._load(cmd.from_account_id)
        to_acc   = self._load(cmd.to_account_id)
        if from_acc is None:
            return CommandResult.fail(f"Account {cmd.from_account_id} not found.")
        if to_acc is None:
            return CommandResult.fail(f"Account {cmd.to_account_id} not found.")

        from_acc.transfer_out(cmd.amount, cmd.to_account_id)
        to_acc.deposit(cmd.amount, f"Transfer from {cmd.from_account_id}")

        # Persist both atomically (append_all)
        events_from = from_acc.pop_pending_events()
        events_to   = to_acc.pop_pending_events()
        for event in events_from:
            stored = self._store.append(event)
            self._updater.apply(event, stored.aggregate_version)
        for event in events_to:
            stored = self._store.append(event)
            self._updater.apply(event, stored.aggregate_version)

        return CommandResult.ok(
            cmd.from_account_id,
            self._store.get_version(cmd.from_account_id),
        )

    def _apply_interest(self, cmd: ApplyInterestCommand) -> CommandResult:
        account = self._load(cmd.account_id)
        if account is None:
            return CommandResult.fail(f"Account {cmd.account_id} not found.")
        # Interest rate is not stored in events — derived from account type on rebuild
        # Already set in _apply(AccountOpened) for savings accounts
        account.apply_interest()
        return self._persist(account)

    def _load(self, account_id: str) -> Optional[AccountAggregate]:
        events = self._store.get_events(account_id)
        if not events:
            return None
        return AccountAggregate.from_events(events)

    def _persist(self, account: AccountAggregate) -> CommandResult:
        events = account.pop_pending_events()
        for event in events:
            stored = self._store.append(event)
            self._updater.apply(event, stored.aggregate_version)
        return CommandResult.ok(
            account.account_id,
            self._store.get_version(account.account_id),
        )


# ---------------------------------------------------------------------------
# QueryHandler — read side
# ---------------------------------------------------------------------------

class AccountQueryHandler:
    """
    Handles all account read queries.
    Reads exclusively from Read Models — never touches EventStore.
    This is the key CQRS separation.
    """

    def __init__(self, read_model_store: ReadModelStore) -> None:
        self._store = read_model_store

    def handle(self, query: Query) -> Any:
        if isinstance(query, GetBalanceQuery):
            return self._get_balance(query)
        if isinstance(query, GetAccountSummaryQuery):
            return self._get_summary(query)
        if isinstance(query, ListAccountsQuery):
            return self._list_accounts(query)
        if isinstance(query, GetTransactionHistoryQuery):
            return self._get_history(query)
        raise ValueError(f"Unknown query: {query.query_type}")

    def _get_balance(self, query: GetBalanceQuery) -> Optional[float]:
        model = self._store.get_balance(query.account_id)
        return model.balance if model else None

    def _get_summary(self, query: GetAccountSummaryQuery) -> Optional[dict]:
        model = self._store.get_summary(query.account_id)
        if model is None:
            return None
        return {
            "account_id":    model.account_id,
            "owner_name":    model.owner_name,
            "account_type":  model.account_type,
            "balance":       model.balance,
            "tx_count":      model.tx_count,
            "version":       model.version,
            "last_activity": model.last_activity,
        }

    def _list_accounts(self, query: ListAccountsQuery) -> dict:
        summaries = self._store.all_summaries()
        if query.owner:
            summaries = [s for s in summaries
                         if s.owner_name.lower() == query.owner.lower()]
        if query.actype:
            summaries = [s for s in summaries
                         if s.account_type == query.actype]
        total = len(summaries)
        start = (query.page - 1) * query.page_size
        page  = summaries[start:start + query.page_size]
        return {
            "accounts": [
                {"account_id": s.account_id, "owner_name": s.owner_name,
                 "balance": s.balance, "account_type": s.account_type}
                for s in page
            ],
            "total":     total,
            "page":      query.page,
            "page_size": query.page_size,
        }

    def _get_history(self, query: GetTransactionHistoryQuery) -> list[dict]:
        history = self._store.get_history(query.account_id)
        if history is None:
            return []
        records = history.records[:query.limit]
        return [
            {
                "event_type":   r.event_type,
                "amount":       r.amount,
                "balance_after": r.balance_after,
                "description":  r.description,
                "occurred_at":  r.occurred_at,
            }
            for r in records
        ]


# ---------------------------------------------------------------------------
# CQRSFacade — single entry point (like BankApplicationService for J11)
# ---------------------------------------------------------------------------

class CQRSFacade:
    """
    Unified entry point for CQRS operations.
    Clients call either handle_command() or handle_query() — never both.
    """

    def __init__(self) -> None:
        self._event_store  = InProcessEventStore()
        self._read_store   = ReadModelStore()
        self._updater      = ProjectionUpdater(self._read_store)
        self._commands     = AccountCommandHandler(self._event_store, self._updater)
        self._queries      = AccountQueryHandler(self._read_store)

    def handle_command(self, command: Command) -> CommandResult:
        return self._commands.handle(command)

    def handle_query(self, query: Query) -> Any:
        return self._queries.handle(query)

    @property
    def event_store(self) -> InProcessEventStore:
        return self._event_store

    @property
    def read_store(self) -> ReadModelStore:
        return self._read_store
