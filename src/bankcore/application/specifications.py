"""
BankCore — Day 14: Specification Pattern
==========================================
Composable, reusable query objects for AccountRepository.

Problem solved: without Specifications, every new query type requires
a new method on AccountRepositoryPort. With 5 account attributes and
3 logical operators, that's potentially dozens of methods — and that's
before adding pagination and sorting.

With Specifications:
  - Each business rule is a first-class object (testable in isolation)
  - Queries compose with &, |, ~ (AND, OR, NOT)
  - In-memory and SQLite implementations both use the same specs
  - Adding a new filter = adding a class, not modifying the port

Design: pure Python, no SQLAlchemy, no imports from infrastructure.
Specifications belong to the Application layer.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass   # avoid circular imports


# ---------------------------------------------------------------------------
# Base Specification
# ---------------------------------------------------------------------------

class AccountSpec(ABC):
    """
    Abstract base for all account specifications.

    Supports boolean composition:
        spec_a & spec_b  → AndSpec(spec_a, spec_b)
        spec_a | spec_b  → OrSpec(spec_a, spec_b)
        ~spec_a          → NotSpec(spec_a)
    """

    @abstractmethod
    def is_satisfied_by(self, account) -> bool:
        """Return True if account satisfies this specification."""

    def __and__(self, other: "AccountSpec") -> "AndSpec":
        return AndSpec(self, other)

    def __or__(self, other: "AccountSpec") -> "OrSpec":
        return OrSpec(self, other)

    def __invert__(self) -> "NotSpec":
        return NotSpec(self)

    def __repr__(self) -> str:
        return self.__class__.__name__


# ---------------------------------------------------------------------------
# Composite Specifications (boolean operators)
# ---------------------------------------------------------------------------

class AndSpec(AccountSpec):
    """Both specifications must be satisfied."""

    def __init__(self, left: AccountSpec, right: AccountSpec) -> None:
        self._left  = left
        self._right = right

    def is_satisfied_by(self, account) -> bool:
        return self._left.is_satisfied_by(account) and self._right.is_satisfied_by(account)

    def __repr__(self) -> str:
        return f"({self._left} AND {self._right})"


class OrSpec(AccountSpec):
    """At least one specification must be satisfied."""

    def __init__(self, left: AccountSpec, right: AccountSpec) -> None:
        self._left  = left
        self._right = right

    def is_satisfied_by(self, account) -> bool:
        return self._left.is_satisfied_by(account) or self._right.is_satisfied_by(account)

    def __repr__(self) -> str:
        return f"({self._left} OR {self._right})"


class NotSpec(AccountSpec):
    """The wrapped specification must NOT be satisfied."""

    def __init__(self, spec: AccountSpec) -> None:
        self._spec = spec

    def is_satisfied_by(self, account) -> bool:
        return not self._spec.is_satisfied_by(account)

    def __repr__(self) -> str:
        return f"NOT({self._spec})"


class AllSpec(AccountSpec):
    """Matches every account — useful as a default."""

    def is_satisfied_by(self, account) -> bool:
        return True


# ---------------------------------------------------------------------------
# Concrete Specifications
# ---------------------------------------------------------------------------

class OwnerSpec(AccountSpec):
    """Account belongs to the named owner (case-insensitive)."""

    def __init__(self, owner_name: str) -> None:
        self._name = owner_name.strip().lower()

    def is_satisfied_by(self, account) -> bool:
        return account.owner_name.strip().lower() == self._name

    def __repr__(self) -> str:
        return f"OwnerSpec({self._name!r})"


class TypeSpec(AccountSpec):
    """Account is of the specified type."""

    def __init__(self, account_type: str) -> None:
        self._type = account_type.strip().lower()

    def is_satisfied_by(self, account) -> bool:
        return account.account_type.lower() == self._type

    def __repr__(self) -> str:
        return f"TypeSpec({self._type!r})"


class BalanceSpec(AccountSpec):
    """
    Account balance is within the specified range.
    Both min and max are optional (inclusive).
    """

    def __init__(
        self,
        min: float | None = None,
        max: float | None = None,
    ) -> None:
        self._min = min
        self._max = max

    def is_satisfied_by(self, account) -> bool:
        if self._min is not None and account.balance < self._min:
            return False
        if self._max is not None and account.balance > self._max:
            return False
        return True

    def __repr__(self) -> str:
        parts = []
        if self._min is not None:
            parts.append(f"min={self._min}")
        if self._max is not None:
            parts.append(f"max={self._max}")
        return f"BalanceSpec({', '.join(parts)})"


class InterestEligibleSpec(AccountSpec):
    """
    Account is eligible for interest application.
    Uses InterestBearing interface (ISP Day 09) — not isinstance(SavingsAccount).
    """

    def is_satisfied_by(self, account) -> bool:
        from bankcore.interfaces import InterestBearing
        return (
            isinstance(account, InterestBearing)
            and account.balance >= account.min_possible_balance
        )

    def __repr__(self) -> str:
        return "InterestEligibleSpec"


class OverdraftSpec(AccountSpec):
    """Account is currently using its overdraft facility."""

    def is_satisfied_by(self, account) -> bool:
        return account.balance < 0

    def __repr__(self) -> str:
        return "OverdraftSpec"


class LowBalanceSpec(AccountSpec):
    """Account balance is below the configured alert threshold."""

    def __init__(self, threshold: float = 100.0) -> None:
        self._threshold = threshold

    def is_satisfied_by(self, account) -> bool:
        return account.balance < self._threshold and account.balance >= account.min_possible_balance

    def __repr__(self) -> str:
        return f"LowBalanceSpec(threshold={self._threshold})"


# ---------------------------------------------------------------------------
# Page — paginated result
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Page:
    """
    Paginated result from AccountRepository.find().

    Immutable: a Page is a snapshot, not a live view.
    """
    items:     list
    total:     int
    page:      int
    page_size: int

    @property
    def has_next(self) -> bool:
        return self.page * self.page_size < self.total

    @property
    def has_prev(self) -> bool:
        return self.page > 1

    @property
    def total_pages(self) -> int:
        if self.page_size == 0:
            return 0
        import math
        return math.ceil(self.total / self.page_size)

    def __len__(self) -> int:
        return len(self.items)

    def __iter__(self):
        return iter(self.items)
