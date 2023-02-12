"""
BankCore — Day 02/06: Account models
======================================
Day 06 SRP update: TransactionHistory extracted from Account.
Account's single responsibility: enforce business rules for money movement.
"""

import uuid
from abc import ABC, abstractmethod
from datetime import date
from typing import Optional

from bankcore.transaction_history import TransactionHistory
from bankcore.interfaces import Readable, Transactable


class Account(Readable, Transactable, ABC):
    """
    Abstract base class for all BankCore account types.
    Day 06: delegates transaction history to TransactionHistory.
    """

    def __init__(self, owner_name: str, initial_deposit: float = 0.0) -> None:
        if initial_deposit < 0:
            raise ValueError("Initial deposit cannot be negative.")

        self.account_id: str  = str(uuid.uuid4())[:8].upper()
        self.owner_name: str  = owner_name
        self._balance: float  = initial_deposit
        self.created_at: date = date.today()
        self._history         = TransactionHistory()

        if initial_deposit > 0:
            self._record("Initial deposit", initial_deposit)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def balance(self) -> float:
        return self._balance

    @property
    @abstractmethod
    def account_type(self) -> str:
        """String identifier: 'current', 'savings', 'pro'."""

    @property
    @abstractmethod
    def min_possible_balance(self) -> float:
        """
        The lowest balance this account can legally reach.
        LSP contract (Day 08): every subtype must declare this.
          - CurrentAccount: 0.0 (no overdraft)
          - SavingsAccount: min_balance (50.0 by default)
          - ProAccount: overdraft_limit (e.g. -5000.0)
        Invariant: self.balance >= self.min_possible_balance always holds.
        """

    def can_withdraw(self, amount: float) -> bool:
        """
        Check whether a withdrawal is feasible without executing it.
        No side effects — safe to call for UI validation or fee checks.
        Subclasses may override for type-specific logic (Day 08 — LSP).
        """
        if amount <= 0:
            return False
        return self._balance - amount >= self.min_possible_balance

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def deposit(self, amount: float, description: str = "Deposit") -> bool:
        """
        Credit the account.
        Returns True on success, False if amount is invalid.
        """
        if amount <= 0:
            return False
        self._balance += amount
        self._record(description, amount)
        return True

    @abstractmethod
    def withdraw(self, amount: float, description: str = "Withdrawal") -> bool:
        """
        Debit the account.
        Each account type enforces its own rules here.
        Returns True on success, False if rules prevent the withdrawal.
        """

    def _record(self, description: str, amount: float) -> None:
        """Delegate recording to TransactionHistory (Day 06 SRP)."""
        self._history.record(amount, description, self._balance)

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def get_info(self) -> dict:
        """Standardized account snapshot. Foundation for Repository (Day 14)."""
        return {
            "account_id":        self.account_id,
            "owner_name":        self.owner_name,
            "account_type":      self.account_type,
            "balance":           self._balance,
            "created_at":        self.created_at.isoformat(),
            "transaction_count": self._history.count(),
        }

    def get_transactions(self) -> list[dict]:
        """Delegate to TransactionHistory (Day 06 SRP)."""
        return self._history.get_all()

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"id={self.account_id}, "
            f"owner={self.owner_name!r}, "
            f"balance={self._balance:.2f})"
        )


# ---------------------------------------------------------------------------
# Concrete account types
# ---------------------------------------------------------------------------

class CurrentAccount(Account):
    """
    Standard checking account.
    - Monthly fee: 2.00 EUR (applied externally by FeeService — Day 04)
    - Daily transfer limit: 10,000 EUR
    - No minimum balance, no overdraft
    """

    MONTHLY_FEE: float = 2.00
    DAILY_LIMIT: float = 10_000.0

    def __init__(
        self,
        owner_name: str,
        initial_deposit: float = 0.0,
        daily_limit: Optional[float] = None,
    ) -> None:
        super().__init__(owner_name, initial_deposit)
        self.daily_limit = daily_limit or self.DAILY_LIMIT
        self.monthly_fee = self.MONTHLY_FEE

    @property
    def account_type(self) -> str:
        return "current"

    @property
    def min_possible_balance(self) -> float:
        return 0.0   # No overdraft: balance cannot go below zero

    def withdraw(self, amount: float, description: str = "Withdrawal") -> bool:
        if amount <= 0:
            return False
        if amount > self._balance:
            return False   # No overdraft for current accounts
        if amount > self.daily_limit:
            return False   # Daily limit enforced
        self._balance -= amount
        self._record(description, -amount)
        return True


class SavingsAccount(Account):
    # Implements InterestBearing (Day 09 — ISP) declared below class definition
    """
    Interest-bearing savings account.
    - Interest rate: 2.5% annually (applied via apply_interest())
    - Minimum balance: 50.00 EUR must remain after withdrawal
    - No daily limit on withdrawals (but minimum balance enforced)
    """

    INTEREST_RATE: float = 0.025   # 2.5% per year
    MIN_BALANCE: float = 50.0

    def __init__(
        self,
        owner_name: str,
        initial_deposit: float = 0.0,
        interest_rate: Optional[float] = None,
        min_balance: Optional[float] = None,
    ) -> None:
        super().__init__(owner_name, initial_deposit)
        self.interest_rate = interest_rate or self.INTEREST_RATE
        self.min_balance = min_balance or self.MIN_BALANCE

    @property
    def account_type(self) -> str:
        return "savings"

    @property
    def min_possible_balance(self) -> float:
        return self.min_balance   # Must always keep at least min_balance

    def can_withdraw(self, amount: float) -> bool:
        """Override: savings account must maintain min_balance."""
        if amount <= 0:
            return False
        return self._balance - amount >= self.min_balance

    def withdraw(self, amount: float, description: str = "Withdrawal") -> bool:
        if amount <= 0:
            return False
        if self._balance - amount < self.min_balance:
            return False   # Minimum balance must be maintained
        self._balance -= amount
        self._record(description, -amount)
        return True

    def apply_interest(self) -> float:
        """
        Apply annual interest to the balance.
        Returns the interest amount credited.
        Called by a scheduled job (Day 04 — Strategy will determine frequency).
        """
        interest = self._balance * self.interest_rate
        self._balance += interest
        self._record("Annual interest", interest)
        return interest


class ProAccount(Account):
    # Implements Overdraftable (Day 09 — ISP) declared below class definition
    """
    Business / professional account.
    - Monthly fee: 15.00 EUR
    - Daily transfer limit: 50,000 EUR
    - Overdraft allowed up to -5,000 EUR
    """

    MONTHLY_FEE: float = 15.00
    DAILY_LIMIT: float = 50_000.0
    OVERDRAFT_LIMIT: float = -5_000.0

    def __init__(
        self,
        owner_name: str,
        initial_deposit: float = 0.0,
        overdraft_limit: Optional[float] = None,
        daily_limit: Optional[float] = None,
    ) -> None:
        super().__init__(owner_name, initial_deposit)
        self.monthly_fee = self.MONTHLY_FEE
        self.overdraft_limit = overdraft_limit or self.OVERDRAFT_LIMIT
        self.daily_limit = daily_limit or self.DAILY_LIMIT

    @property
    def account_type(self) -> str:
        return "pro"

    @property
    def min_possible_balance(self) -> float:
        return self.overdraft_limit   # Can go negative down to overdraft limit

    def can_withdraw(self, amount: float) -> bool:
        """Override: pro accounts allow overdraft down to overdraft_limit."""
        if amount <= 0:
            return False
        if amount > self.daily_limit:
            return False
        return self._balance - amount >= self.overdraft_limit

    def overdraft_used(self) -> float:
        """Amount currently drawn from overdraft facility (>= 0)."""
        return max(0.0, -self._balance)

    def withdraw(self, amount: float, description: str = "Withdrawal") -> bool:
        if amount <= 0:
            return False
        if amount > self.daily_limit:
            return False
        if self._balance - amount < self.overdraft_limit:
            return False   # Would exceed overdraft limit
        self._balance -= amount
        self._record(description, -amount)
        return True


# ---------------------------------------------------------------------------
# Interface registrations (Day 09 — ISP)
# Uses ABC.register() so isinstance(savings, InterestBearing) returns True
# without requiring multiple inheritance — keeps the class hierarchy clean.
# ---------------------------------------------------------------------------
from bankcore.interfaces import InterestBearing, Overdraftable
InterestBearing.register(SavingsAccount)
Overdraftable.register(ProAccount)
