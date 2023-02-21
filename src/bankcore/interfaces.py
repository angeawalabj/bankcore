"""
BankCore — Day 09: Segregated Interfaces (ISP)
================================================
All BankCore interfaces defined in one place.

Design decision: co-locate interfaces in one file rather than scattering
them across modules. This makes the contract landscape visible at a glance
and avoids circular imports.

Each interface is minimal — it contains only what its specific clients need.
Clients import the exact interface they depend on, not a superset.

Interface hierarchy:
  Account capabilities:
    Readable       — read account state (balance, info, history)
    Transactable   — deposit and withdraw
    InterestBearing — apply and query interest (SavingsAccount only)
    Overdraftable  — declare overdraft capability (ProAccount only)

  Transaction processing:
    Depositable    — can process a deposit operation
    Withdrawable   — can process a withdrawal operation
    Transferable   — can process a transfer operation

  Event system:
    EventHandler   — mandatory: react to a BankEvent
    EventFilter    — optional mixin: declare which events to receive
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bankcore.events import BankEvent


# ===========================================================================
# Account capability interfaces
# ===========================================================================

class Readable(ABC):
    """
    Read-only view of an account.

    Clients that only need to read account state (reporting services,
    audit loggers, dashboards) depend on this interface — not on Account.
    They cannot accidentally call deposit() or withdraw().

    Note: account_id, owner_name, balance, account_type are instance
    attributes on Account — they satisfy this interface structurally.
    Only the methods need @abstractmethod here to avoid conflicts with
    Account's concrete attribute definitions.
    """

    @abstractmethod
    def get_info(self) -> dict:
        """
        Standardized account snapshot.
        Must always contain: account_id, owner_name, account_type,
        balance, created_at, transaction_count.
        """

    @abstractmethod
    def get_transactions(self) -> list[dict]:
        """Full transaction history as list of dicts."""


class Transactable(ABC):
    """
    Write interface for single-account operations.

    TransactionService, decorators, and fee processors depend on this.
    They don't need get_info() or get_transactions() — only the ability
    to move money in and out of one account.
    """

    @abstractmethod
    def deposit(self, amount: float, description: str = "Deposit") -> bool:
        """
        Credit the account.
        Contract (LSP Day 08): amount > 0 must always succeed.
        """

    @abstractmethod
    def withdraw(self, amount: float, description: str = "Withdrawal") -> bool:
        """
        Debit the account.
        Contract: returns False (no side effect) if rules prevent it.
        """

    def can_withdraw(self, amount: float) -> bool:
        """
        Feasibility check — no side effects. Default implementation.
        Subclasses override for type-specific rules (Day 08 — LSP).
        """
        return amount > 0


class InterestBearing(ABC):
    """
    Capability interface for interest-bearing accounts.

    Only SavingsAccount (and future premium variants) implement this.
    InterestService depends on InterestBearing — not on SavingsAccount directly.
    This eliminates isinstance(account, SavingsAccount) checks (LSP violation).

    ISP benefit: CurrentAccount and ProAccount are NOT forced to implement
    apply_interest() with a meaningless stub.
    """

    @property
    @abstractmethod
    def interest_rate(self) -> float:
        """Annual interest rate as a decimal (e.g. 0.025 = 2.5%)."""

    @abstractmethod
    def apply_interest(self) -> float:
        """
        Apply the annual interest rate to the current balance.
        Returns the interest amount credited.
        """


class Overdraftable(ABC):
    """
    Capability interface for accounts that allow negative balances.

    Only ProAccount implements this. Fraud detection and risk services
    can check overdraft exposure without knowing the concrete type.
    """

    @property
    @abstractmethod
    def overdraft_limit(self) -> float:
        """Maximum overdraft allowed (negative number, e.g. -5000.0)."""

    @abstractmethod
    def overdraft_used(self) -> float:
        """Amount currently used from the overdraft facility (>= 0)."""


# ===========================================================================
# Transaction processing interfaces
# ===========================================================================

class Depositable(ABC):
    """
    Interface for services that can process deposit operations.
    BatchDepositService depends on this — not on TransactionProcessor.
    """

    @abstractmethod
    def deposit(self, account: "Transactable", amount: float) -> dict:
        """Process a deposit. Returns result dict with success status."""


class Withdrawable(ABC):
    """
    Interface for services that can process withdrawal operations.
    """

    @abstractmethod
    def withdraw(self, account: "Transactable", amount: float) -> dict:
        """Process a withdrawal. Returns result dict with success status."""


class Transferable(ABC):
    """
    Interface for services that can process transfer operations.
    Most business logic only needs transfers — not deposits or withdrawals.
    """

    @abstractmethod
    def transfer(
        self,
        from_account: "Transactable",
        to_account: "Transactable",
        amount: float,
    ) -> dict:
        """Move funds between two accounts. Returns result dict."""


# ===========================================================================
# Event system interfaces
# ===========================================================================

class EventHandler(ABC):
    """
    Mandatory interface for AlertSystem observers.
    Every observer must implement on_event().

    Separated from EventFilter so observers that receive all events
    don't need to implement supported_events() — they just inherit
    the wildcard default from AlertObserver.
    """

    @abstractmethod
    def on_event(self, event: "BankEvent") -> None:
        """
        React to a bank event. Must not raise exceptions.
        Errors are silenced by AlertSystem to protect other observers.
        """


class EventFilter(ABC):
    """
    Optional mixin for observers that want to filter events by type.
    Observers that don't implement this receive all events (wildcard).

    ISP benefit: observers that genuinely want all events (AuditLogger)
    don't need to implement supported_events() returning ["*"] — they
    just don't implement EventFilter at all.
    """

    @abstractmethod
    def supported_events(self) -> list[str]:
        """
        Return the list of event types this observer handles.
        Use ["*"] for all events (but prefer not implementing EventFilter).
        """
