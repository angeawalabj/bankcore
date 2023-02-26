"""
BankCore — Day 12: Domain Value Objects
=========================================
Value Objects are immutable domain concepts with no identity.
Two Money(100, "EUR") objects are equal — they represent the same value.

Design decisions:
  - frozen=True: immutability enforced by the runtime
  - Rich operators: +, -, comparison — Money feels natural to use
  - Currency validation: you cannot add EUR to USD — silent bugs prevented
  - No infrastructure imports: this file has ZERO external dependencies

These are the innermost circle of Clean Architecture.
They express domain concepts in the language of banking.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Money:
    """
    Represents a monetary amount with its currency.

    Value Object: defined by its value, not its identity.
    Two Money(100, "EUR") instances are equal and interchangeable.

    Invariants:
      - amount >= 0 (use negative operations, not negative amounts)
      - currency is a 3-letter ISO code (EUR, USD, GBP...)
      - arithmetic only between same-currency Money objects
    """
    amount:   float
    currency: str

    def __post_init__(self):
        if self.amount < 0:
            raise ValueError(
                f"Money amount cannot be negative: {self.amount}. "
                "Use subtraction instead of negative amounts."
            )
        if not self.currency or len(self.currency) != 3:
            raise ValueError(
                f"Currency must be a 3-letter ISO code, got: {self.currency!r}"
            )
        # Normalize currency to uppercase
        object.__setattr__(self, "currency", self.currency.upper())

    def __add__(self, other: "Money") -> "Money":
        self._assert_same_currency(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: "Money") -> "Money":
        self._assert_same_currency(other)
        result = self.amount - other.amount
        if result < 0:
            raise ValueError(
                f"Subtraction would result in negative Money: "
                f"{self} - {other} = {result:.2f} {self.currency}"
            )
        return Money(result, self.currency)

    def __mul__(self, factor: float) -> "Money":
        if factor < 0:
            raise ValueError(f"Cannot multiply Money by negative factor: {factor}")
        return Money(round(self.amount * factor, 2), self.currency)

    def __lt__(self, other: "Money") -> bool:
        self._assert_same_currency(other)
        return self.amount < other.amount

    def __le__(self, other: "Money") -> bool:
        self._assert_same_currency(other)
        return self.amount <= other.amount

    def __gt__(self, other: "Money") -> bool:
        self._assert_same_currency(other)
        return self.amount > other.amount

    def __ge__(self, other: "Money") -> bool:
        self._assert_same_currency(other)
        return self.amount >= other.amount

    def is_zero(self) -> bool:
        return self.amount == 0.0

    def is_positive(self) -> bool:
        return self.amount > 0.0

    def percentage(self, pct: float) -> "Money":
        """Return pct% of this amount (e.g. money.percentage(2.5) = 2.5%)."""
        return Money(round(self.amount * pct / 100, 2), self.currency)

    def _assert_same_currency(self, other: "Money") -> None:
        if self.currency != other.currency:
            raise ValueError(
                f"Cannot operate on different currencies: "
                f"{self.currency} vs {other.currency}"
            )

    def __str__(self) -> str:
        return f"{self.amount:,.2f} {self.currency}"

    def __repr__(self) -> str:
        return f"Money({self.amount}, {self.currency!r})"

    @classmethod
    def zero(cls, currency: str = "EUR") -> "Money":
        """Convenience: Money.zero() instead of Money(0.0, 'EUR')."""
        return cls(0.0, currency)

    @classmethod
    def eur(cls, amount: float) -> "Money":
        """Convenience: Money.eur(100) instead of Money(100, 'EUR')."""
        return cls(amount, "EUR")


@dataclass(frozen=True)
class AccountId:
    """
    Strongly-typed account identifier.

    Using a plain string for account IDs creates subtle bugs:
      transfer("ACC-001", "ACC-001", 500)  ← no compiler error, logic error

    With AccountId:
      transfer(AccountId("ACC-001"), AccountId("ACC-001"), ...)
      ← still a logic error, but the type makes it explicit

    Day 13 (Database Schema) will use AccountId as the primary key type.
    """
    value: str

    def __post_init__(self):
        if not self.value or not self.value.strip():
            raise ValueError("AccountId cannot be empty.")
        object.__setattr__(self, "value", self.value.strip().upper())

    def __str__(self) -> str:
        return self.value

    def __hash__(self) -> int:
        return hash(self.value)

    def __eq__(self, other) -> bool:
        if isinstance(other, AccountId):
            return self.value == other.value
        if isinstance(other, str):
            return self.value == other.upper()
        return NotImplemented

    @classmethod
    def generate(cls) -> "AccountId":
        """Generate a new unique AccountId."""
        import uuid
        return cls(str(uuid.uuid4())[:8].upper())
