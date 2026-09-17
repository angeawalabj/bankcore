"""
BankCore — Day 11: Use Cases (Application Layer)
=================================================
Use Cases are the entry points to BankCore's business logic.

Each Use Case:
  1. Receives a Command (validated input DTO)
  2. Loads required domain objects
  3. Orchestrates domain services (TransactionPipeline, FeeCalculator)
  4. Returns a UseCaseResult — never raises for business failures
  5. Is independently testable with injected fakes (DIP, Day 10)

Architecture rule (Layered Architecture, Day 11):
  - Use Cases depend on Domain (Account, FeeStrategy) ✓
  - Use Cases depend on Infrastructure via interfaces (DIP, Day 10) ✓
  - Use Cases do NOT depend on Presentation (CLI, API) ✓
  - Domain does NOT depend on Use Cases ✓

The BankContainer (Day 10) wires everything — Use Cases receive
their dependencies through it, never constructing them directly.
"""

from __future__ import annotations
from typing import Optional, TYPE_CHECKING

from bankcore.application.commands import (
    TransferCommand, DepositCommand, WithdrawCommand,
    CreateAccountCommand, ApplyInterestCommand,
    UseCaseResult,
)
from bankcore.application.ports import AccountRepositoryPort
from bankcore.application.unit_of_work import UnitOfWork
from bankcore.infrastructure.monitoring.metrics import MetricsRegistry
from bankcore.interfaces import InterestBearing

if TYPE_CHECKING:
    from bankcore.container import BankContainer


class AccountRegistry(AccountRepositoryPort):
    """
    In-memory account store.

    Day 11 original — now implements AccountRepositoryPort (Day 12).
    Replaced by InMemoryAccountRepository in infrastructure layer,
    but kept here for backward compatibility with Day 11 tests.
    """

    def __init__(self) -> None:
        self._accounts: dict = {}   # account_id → Account

    def save(self, account) -> None:
        self._accounts[account.account_id] = account

    def find_by_id(self, account_id: str):
        return self._accounts.get(account_id)

    def find_all(self) -> list:
        return list(self._accounts.values())

    def find_by_owner(self, owner_name: str) -> list:
        name = owner_name.strip().lower()
        return [a for a in self._accounts.values()
                if a.owner_name.lower() == name]

    def exists(self, account_id: str) -> bool:
        return account_id in self._accounts

    def count(self) -> int:
        return len(self._accounts)


class TransferUseCase:
    """
    Transfer funds between two accounts.

    Orchestrates: account lookup → pipeline execution → result mapping.
    Business failures are captured in UseCaseResult, not raised as exceptions.

    Dependencies injected via BankContainer (Day 10 — DIP).
    """

    def __init__(self, container: "BankContainer", registry: AccountRepositoryPort) -> None:
        self._pipeline  = container.build_pipeline(
            validate=True, log=False, rate_limit=False, apply_fees=False
        )
        self._registry  = registry

    def execute(self, command: TransferCommand) -> UseCaseResult:
        import time
        metrics = MetricsRegistry.get_instance()
        started = time.perf_counter()

        def _fail(reason: str, code: str) -> UseCaseResult:
            metrics.counter("transfers_failed_total").inc()
            return UseCaseResult.fail(reason, code=code)

        # Step 1: load domain objects
        from_account = self._registry.find_by_id(command.from_account_id)
        to_account   = self._registry.find_by_id(command.to_account_id)

        if from_account is None:
            return _fail(f"Account {command.from_account_id} not found.", "ACCOUNT_NOT_FOUND")
        if to_account is None:
            return _fail(f"Account {command.to_account_id} not found.", "ACCOUNT_NOT_FOUND")

        # Step 2: execute via pipeline (Decorator stack from Day 05)
        result = self._pipeline.transfer(from_account, to_account, command.amount)

        if not result["success"]:
            return _fail(result.get("reason", "Transfer failed."), "TRANSFER_REJECTED")

        # Step 3: persist both updated accounts atomically (Day 14: Unit
        # of Work) — one transaction, not two independent saves, so a
        # failure partway through can't leave a debit without its credit.
        uow = UnitOfWork(self._registry)
        uow.register_dirty(from_account)
        uow.register_dirty(to_account)
        uow.commit()

        # Step 4: observability (Day 20) — only successful transfers count
        # towards latency/amount distributions; failures already counted above.
        metrics.counter("transfers_total").inc()
        metrics.histogram("transfer_latency_ms").observe((time.perf_counter() - started) * 1000)
        metrics.histogram("transfer_amount_eur").observe(command.amount)

        return UseCaseResult.ok(
            from_account_id=command.from_account_id,
            to_account_id=command.to_account_id,
            amount=command.amount,
            from_balance_after=from_account.balance,
            to_balance_after=to_account.balance,
            initiated_by=command.initiated_by,
        )


class DepositUseCase:
    """Credit an account with a given amount."""

    def __init__(self, container: "BankContainer", registry: AccountRepositoryPort) -> None:
        self._service  = container.transaction_service
        self._registry = registry

    def execute(self, command: DepositCommand) -> UseCaseResult:
        account = self._registry.find_by_id(command.account_id)
        if account is None:
            return UseCaseResult.fail(
                f"Account {command.account_id} not found.",
                code="ACCOUNT_NOT_FOUND",
            )

        result = self._service.deposit(account, command.amount)

        if not result["success"]:
            return UseCaseResult.fail(
                result.get("reason", "Deposit failed."),
                code="DEPOSIT_REJECTED",
            )

        self._registry.save(account)
        MetricsRegistry.get_instance().counter("deposits_total").inc()
        return UseCaseResult.ok(
            account_id=command.account_id,
            amount=command.amount,
            balance_after=account.balance,
            initiated_by=command.initiated_by,
        )


class WithdrawUseCase:
    """Debit an account."""

    def __init__(self, container: "BankContainer", registry: AccountRepositoryPort) -> None:
        self._service  = container.transaction_service
        self._registry = registry

    def execute(self, command: WithdrawCommand) -> UseCaseResult:
        account = self._registry.find_by_id(command.account_id)
        if account is None:
            return UseCaseResult.fail(
                f"Account {command.account_id} not found.",
                code="ACCOUNT_NOT_FOUND",
            )

        result = self._service.withdraw(account, command.amount)

        if not result["success"]:
            return UseCaseResult.fail(
                result.get("reason", "Withdrawal failed."),
                code="WITHDRAWAL_REJECTED",
            )

        self._registry.save(account)
        MetricsRegistry.get_instance().counter("withdrawals_total").inc()
        return UseCaseResult.ok(
            account_id=command.account_id,
            amount=command.amount,
            balance_after=account.balance,
            initiated_by=command.initiated_by,
        )


class CreateAccountUseCase:
    """Open a new bank account."""

    def __init__(self, container: "BankContainer", registry: AccountRepositoryPort) -> None:
        self._registry = registry
        self._container = container

    def execute(self, command: CreateAccountCommand) -> UseCaseResult:
        from bankcore.account_factory import AccountFactory
        from bankcore.account_type_registry import AccountTypeRegistry

        if not AccountTypeRegistry.is_registered(command.account_type):
            available = ", ".join(AccountTypeRegistry.available())
            return UseCaseResult.fail(
                f"Unknown account type '{command.account_type}'. "
                f"Available: {available}",
                code="INVALID_ACCOUNT_TYPE",
            )

        account = AccountFactory.create(
            command.account_type,
            command.owner_name,
            command.initial_deposit,
        )

        self._registry.save(account)

        # Publish account created event via alert system
        from bankcore.event_builder import EventBuilder
        self._container.alert_system.publish(
            EventBuilder.account_created_event(account)
        )

        return UseCaseResult.ok(
            account_id=account.account_id,
            owner_name=account.owner_name,
            account_type=account.account_type,
            initial_balance=account.balance,
            initiated_by=command.initiated_by,
        )


class ApplyInterestUseCase:
    """
    Apply annual interest to a savings account.

    ISP (Day 09): depends on InterestBearing, not SavingsAccount.
    Any account that satisfies InterestBearing will work — including
    future PremiumSavingsAccount types registered via AccountTypeRegistry.
    """

    def __init__(self, registry: AccountRepositoryPort) -> None:
        self._registry = registry

    def execute(self, command: ApplyInterestCommand) -> UseCaseResult:
        account = self._registry.find_by_id(command.account_id)

        if account is None:
            return UseCaseResult.fail(
                f"Account {command.account_id} not found.",
                code="ACCOUNT_NOT_FOUND",
            )

        # ISP (Day 09): use the InterestBearing interface, not SavingsAccount
        if not isinstance(account, InterestBearing):
            return UseCaseResult.fail(
                f"Account {command.account_id} ({account.account_type}) "
                "does not support interest.",
                code="NOT_INTEREST_BEARING",
            )

        credited = account.apply_interest()
        self._registry.save(account)

        return UseCaseResult.ok(
            account_id=command.account_id,
            interest_credited=credited,
            new_balance=account.balance,
            interest_rate=account.interest_rate,
            initiated_by=command.initiated_by,
        )


class BankApplicationService:
    """
    Facade over all Use Cases — the single entry point to BankCore.

    The Presentation layer (CLI, API — Day 15) calls this service.
    It never instantiates Use Cases directly. This is the Application
    layer's public API.

    Layered Architecture: Presentation → ApplicationService → UseCases
                                                             → Domain
                                                             → Infrastructure
    """

    def __init__(
        self,
        container: "BankContainer",
        registry: Optional[AccountRepositoryPort] = None,
    ) -> None:
        self._registry = registry if registry is not None else AccountRegistry()
        self._container = container

        # Wire up all use cases with shared registry
        self._transfer = TransferUseCase(container, self._registry)
        self._deposit  = DepositUseCase(container, self._registry)
        self._withdraw = WithdrawUseCase(container, self._registry)
        self._create   = CreateAccountUseCase(container, self._registry)
        self._interest = ApplyInterestUseCase(self._registry)

    def transfer(self, command: TransferCommand) -> UseCaseResult:
        return self._transfer.execute(command)

    def deposit(self, command: DepositCommand) -> UseCaseResult:
        return self._deposit.execute(command)

    def withdraw(self, command: WithdrawCommand) -> UseCaseResult:
        return self._withdraw.execute(command)

    def create_account(self, command: CreateAccountCommand) -> UseCaseResult:
        return self._create.execute(command)

    def apply_interest(self, command: ApplyInterestCommand) -> UseCaseResult:
        return self._interest.execute(command)

    def get_account(self, account_id: str) -> Optional[dict]:
        account = self._registry.find_by_id(account_id)
        return account.get_info() if account else None

    def list_accounts(self) -> list[dict]:
        return [a.get_info() for a in self._registry.find_all()]

    @property
    def registry(self) -> AccountRegistry:
        return self._registry
