"""
BankCore — Day 11: Commands (Application Layer)
================================================
Commands are immutable input DTOs for Use Cases.

Design decision: separate the "what to do" (command) from
"how to do it" (use case). Commands are plain dataclasses —
no logic, no dependencies, no methods beyond validation.

This pattern enables:
  - CLI, API, and tests to express intent in a common language
  - Use Cases to be called from any entry point without adaptation
  - Command validation at the boundary, before any service is invoked

Commands belong to the Application layer — they describe operations
in business terms, not in technical terms.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class TransferCommand:
    """
    Command to move funds between two accounts.

    Immutable: once created, a command is a fact — "this was requested".
    The Use Case decides whether to execute it.
    """
    from_account_id: str
    to_account_id:   str
    amount:          float
    initiated_by:    str              # user ID or system component
    description:     str = "Transfer"
    reference:       str = ""        # external reference (e.g. payment ID)
    timestamp:       datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        if not self.from_account_id or not self.from_account_id.strip():
            raise ValueError("from_account_id is required.")
        if not self.to_account_id or not self.to_account_id.strip():
            raise ValueError("to_account_id is required.")
        if self.amount <= 0:
            raise ValueError(f"Amount must be positive, got {self.amount}.")
        if self.from_account_id == self.to_account_id:
            raise ValueError("Source and destination accounts must differ.")


@dataclass(frozen=True)
class DepositCommand:
    """Command to credit an account."""
    account_id:   str
    amount:       float
    initiated_by: str
    description:  str = "Deposit"
    timestamp:    datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        if not self.account_id or not self.account_id.strip():
            raise ValueError("account_id is required.")
        if self.amount <= 0:
            raise ValueError(f"Amount must be positive, got {self.amount}.")


@dataclass(frozen=True)
class WithdrawCommand:
    """Command to debit an account."""
    account_id:   str
    amount:       float
    initiated_by: str
    description:  str = "Withdrawal"
    timestamp:    datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        if not self.account_id or not self.account_id.strip():
            raise ValueError("account_id is required.")
        if self.amount <= 0:
            raise ValueError(f"Amount must be positive, got {self.amount}.")


@dataclass(frozen=True)
class CreateAccountCommand:
    """Command to open a new bank account."""
    owner_name:      str
    account_type:    str      # 'current', 'savings', 'pro'
    initial_deposit: float
    initiated_by:    str
    timestamp:       datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        if not self.owner_name or not self.owner_name.strip():
            raise ValueError("owner_name is required.")
        if self.initial_deposit < 0:
            raise ValueError("initial_deposit cannot be negative.")


@dataclass(frozen=True)
class ApplyInterestCommand:
    """Command to apply annual interest to a savings account."""
    account_id:   str
    initiated_by: str
    timestamp:    datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        if not self.account_id or not self.account_id.strip():
            raise ValueError("account_id is required.")


# ---------------------------------------------------------------------------
# Use Case Results — structured output from use cases
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class UseCaseResult:
    """
    Standardized result from any Use Case.

    Use Cases never raise exceptions for business failures —
    they return a UseCaseResult with success=False and an error message.
    Only truly unexpected errors (infrastructure failure) bubble up.
    """
    success:    bool
    data:       dict = field(default_factory=dict)
    error:      Optional[str] = None
    error_code: Optional[str] = None

    @classmethod
    def ok(cls, **data) -> "UseCaseResult":
        """Create a successful result with optional data."""
        return cls(success=True, data=data)

    @classmethod
    def fail(cls, error: str, code: str = "BUSINESS_ERROR") -> "UseCaseResult":
        """Create a failed result with error details."""
        return cls(success=False, error=error, error_code=code)

    def __bool__(self) -> bool:
        return self.success
