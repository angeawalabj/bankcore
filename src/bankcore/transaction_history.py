"""
BankCore — Day 06: TransactionHistory
=======================================
Extracted from Account as part of the SRP refactoring.

Before Day 06: Account managed its own transaction history inline.
After  Day 06: TransactionHistory owns that responsibility entirely.

Single responsibility: store, retrieve, and query transaction records
for one account. Nothing else.

Account delegates to TransactionHistory — its public API is unchanged,
so all existing code continues to work without modification.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Optional
import uuid


@dataclass(frozen=True)
class TransactionRecord:
    """
    Immutable record of a single financial operation.

    frozen=True: once created, a transaction record cannot be altered.
    This is a financial system — immutability is a correctness requirement,
    not just a style preference.
    """
    transaction_id: str
    amount: float          # positive = credit, negative = debit
    description: str
    date: date
    balance_after: float

    def to_dict(self) -> dict:
        return {
            "id":            self.transaction_id,
            "amount":        self.amount,
            "description":   self.description,
            "date":          self.date.isoformat(),
            "balance_after": self.balance_after,
        }


class TransactionHistory:
    """
    Manages the transaction record for a single account.

    Responsibilities:
      - Append new records
      - Retrieve records (all, last, filtered)
      - Aggregate queries (count, total credits, total debits)

    NOT responsible for:
      - Validating whether a transaction is allowed (that's Account's job)
      - Persisting records to a database (that's Repository's job — Day 14)
      - Formatting records for the API (that's the serializer's job)
    """

    def __init__(self) -> None:
        self._records: list[TransactionRecord] = []

    def record(
        self,
        amount: float,
        description: str,
        balance_after: float,
    ) -> TransactionRecord:
        """
        Append a new transaction record and return it.
        Called by Account after every successful deposit or withdrawal.
        """
        entry = TransactionRecord(
            transaction_id=str(uuid.uuid4())[:8].upper(),
            amount=amount,
            description=description,
            date=date.today(),
            balance_after=balance_after,
        )
        self._records.append(entry)
        return entry

    def get_all(self) -> list[dict]:
        """Return all records as dicts (read-only snapshot)."""
        return [r.to_dict() for r in self._records]

    def last(self) -> Optional[TransactionRecord]:
        """Return the most recent record, or None if empty."""
        return self._records[-1] if self._records else None

    def count(self) -> int:
        return len(self._records)

    def total_credits(self) -> float:
        """Sum of all positive amounts (deposits, interest)."""
        return sum(r.amount for r in self._records if r.amount > 0)

    def total_debits(self) -> float:
        """Sum of all negative amounts (withdrawals, fees) as a positive number."""
        return abs(sum(r.amount for r in self._records if r.amount < 0))

    def filter_by_description(self, keyword: str) -> list[TransactionRecord]:
        """Find records whose description contains the keyword (case-insensitive)."""
        kw = keyword.lower()
        return [r for r in self._records if kw in r.description.lower()]

    def __len__(self) -> int:
        return len(self._records)

    def __repr__(self) -> str:
        return f"TransactionHistory({len(self._records)} records)"
