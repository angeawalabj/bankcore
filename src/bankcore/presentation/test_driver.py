"""
BankCore — Day 15: TestDriver (Primary Adapter)
=================================================
A fluent API for integration testing BankCore without HTTP or CLI.

The TestDriver is a primary adapter (driving adapter) in Hexagonal Architecture.
It translates test-friendly method calls into Commands, passes them to
BankApplicationService, and provides assertion helpers.

Benefits:
  - Tests express INTENT, not implementation details
  - Zero HTTP, zero CLI parsing, zero mocking of internals
  - Full stack exercised: Commands → Use Cases → Domain → Repository
  - Readable test code that doubles as documentation

Usage:
    driver = TestDriver.create()
    driver.create_account("Alice", "current", 1_000.0)
    driver.create_account("Bob",   "savings", 500.0)
    driver.transfer("Alice", "Bob", 300.0)
    assert driver.balance("Alice") == 700.0
    assert driver.balance("Bob")   == 800.0

Hexagonal Architecture rule:
    TestDriver contains ZERO business logic.
    It translates method calls to Commands — nothing more.
"""

from __future__ import annotations
from typing import Optional

from bankcore.application.commands import (
    CreateAccountCommand, DepositCommand, WithdrawCommand,
    TransferCommand, ApplyInterestCommand, UseCaseResult,
)
from bankcore.application.use_cases import BankApplicationService
from bankcore.protocols import FakeConfig, SpyAlertSystem
from bankcore.container import BankContainer
from bankcore.infrastructure.persistence.in_memory_repository import (
    InMemoryAccountRepository,
)


class TestDriver:
    """
    Primary adapter for integration testing.

    Maintains a name→account_id registry so tests can use
    human-readable names ("Alice", "Bob") instead of UUIDs.
    """

    def __init__(self, app: BankApplicationService) -> None:
        self._app      = app
        self._registry: dict[str, str] = {}   # name → account_id
        self._results:  list[UseCaseResult] = []

    @classmethod
    def create(
        cls,
        config: Optional[object] = None,
        spy: Optional[SpyAlertSystem] = None,
    ) -> "TestDriver":
        """
        Create a fully-wired TestDriver with in-memory infrastructure.
        Zero global state — each TestDriver is completely isolated.
        """
        spy       = spy or SpyAlertSystem()
        container = BankContainer.build(
            config=config or FakeConfig(),
            alert_system=spy,
        )
        repo = InMemoryAccountRepository()
        app  = BankApplicationService(container, registry=repo)
        return cls(app)

    # ------------------------------------------------------------------
    # Account operations (translate name → account_id automatically)
    # ------------------------------------------------------------------

    def create_account(
        self,
        name: str,
        account_type: str = "current",
        initial_deposit: float = 0.0,
        initiated_by: str = "test",
    ) -> UseCaseResult:
        cmd    = CreateAccountCommand(name, account_type, initial_deposit, initiated_by)
        result = self._app.create_account(cmd)
        if result.success:
            self._registry[name] = result.data["account_id"]
        self._results.append(result)
        return result

    def deposit(
        self,
        name: str,
        amount: float,
        description: str = "Test deposit",
    ) -> UseCaseResult:
        account_id = self._resolve(name)
        cmd    = DepositCommand(account_id, amount, "test", description)
        result = self._app.deposit(cmd)
        self._results.append(result)
        return result

    def withdraw(
        self,
        name: str,
        amount: float,
        description: str = "Test withdrawal",
    ) -> UseCaseResult:
        account_id = self._resolve(name)
        cmd    = WithdrawCommand(account_id, amount, "test", description)
        result = self._app.withdraw(cmd)
        self._results.append(result)
        return result

    def transfer(
        self,
        from_name: str,
        to_name: str,
        amount: float,
        description: str = "Test transfer",
    ) -> UseCaseResult:
        from_id = self._resolve(from_name)
        to_id   = self._resolve(to_name)
        cmd    = TransferCommand(from_id, to_id, amount, "test", description)
        result = self._app.transfer(cmd)
        self._results.append(result)
        return result

    def apply_interest(self, name: str) -> UseCaseResult:
        account_id = self._resolve(name)
        cmd    = ApplyInterestCommand(account_id, "test-scheduler")
        result = self._app.apply_interest(cmd)
        self._results.append(result)
        return result

    # ------------------------------------------------------------------
    # Query helpers (for assertions)
    # ------------------------------------------------------------------

    def balance(self, name: str) -> float:
        info = self._app.get_account(self._resolve(name))
        if info is None:
            raise ValueError(f"Account for '{name}' not found.")
        return info["balance"]

    def account_info(self, name: str) -> Optional[dict]:
        return self._app.get_account(self._resolve(name))

    def all_accounts(self) -> list[dict]:
        return self._app.list_accounts()

    def account_id(self, name: str) -> str:
        return self._resolve(name)

    # ------------------------------------------------------------------
    # Assertion helpers (fluent)
    # ------------------------------------------------------------------

    def assert_balance(self, name: str, expected: float, tolerance: float = 0.01) -> "TestDriver":
        actual = self.balance(name)
        assert abs(actual - expected) <= tolerance, (
            f"Expected {name}'s balance to be {expected:.2f}, got {actual:.2f}"
        )
        return self

    def assert_last_success(self) -> "TestDriver":
        assert self._results, "No operations performed yet."
        assert self._results[-1].success, (
            f"Last operation failed: {self._results[-1].error}"
        )
        return self

    def assert_last_failure(self, code: Optional[str] = None) -> "TestDriver":
        assert self._results, "No operations performed yet."
        assert not self._results[-1].success, "Expected last operation to fail."
        if code:
            assert self._results[-1].error_code == code, (
                f"Expected error code {code!r}, got {self._results[-1].error_code!r}"
            )
        return self

    def assert_account_count(self, expected: int) -> "TestDriver":
        actual = len(self.all_accounts())
        assert actual == expected, f"Expected {expected} accounts, got {actual}."
        return self

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _resolve(self, name: str) -> str:
        if name in self._registry:
            return self._registry[name]
        raise ValueError(
            f"No account registered for '{name}'. "
            f"Call create_account('{name}', ...) first."
        )

    @property
    def last_result(self) -> Optional[UseCaseResult]:
        return self._results[-1] if self._results else None

    @property
    def operation_count(self) -> int:
        return len(self._results)
