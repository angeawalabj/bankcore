"""
BankCore — Day 03: Bank Events
================================
Defines the events that flow through BankCore's AlertSystem.

Design decision: events are immutable dataclasses — once created, they
cannot be modified. Observers receive a snapshot of the moment, not a
live reference. This prevents one observer from corrupting another's view.

Event types follow a "domain.action" convention:
  - "transaction.transfer"
  - "transaction.deposit"
  - "transaction.withdrawal"
  - "account.created"
  - "alert.low_balance"
  - "alert.large_transaction"
  - "alert.fraud_suspected"
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class BankEvent:
    """
    Immutable event emitted by BankCore services.

    frozen=True means no observer can accidentally mutate the event
    while another is processing it — thread safety for free.

    Usage:
        event = BankEvent(
            event_type="transaction.transfer",
            account_id="A1B2C3D4",
            amount=6_000.0,
            metadata={"to_account": "E5F6G7H8"}
        )
    """
    event_type: str
    account_id: str
    amount: float = 0.0
    metadata: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)

    def is_type(self, *event_types: str) -> bool:
        """Convenience check: event.is_type('transaction.transfer', 'transaction.deposit')"""
        return self.event_type in event_types

    def __str__(self) -> str:
        return (
            f"BankEvent({self.event_type} | "
            f"account={self.account_id} | "
            f"amount={self.amount:.2f} | "
            f"at={self.timestamp.strftime('%H:%M:%S')})"
        )


# ---------------------------------------------------------------------------
# Event type constants — use these instead of raw strings
# ---------------------------------------------------------------------------

class EventType:
    """
    Centralized event type registry.
    Using constants prevents typos like "transcation.transfer".
    """
    # Transaction events
    TRANSFER    = "transaction.transfer"
    DEPOSIT     = "transaction.deposit"
    WITHDRAWAL  = "transaction.withdrawal"

    # Account lifecycle events
    ACCOUNT_CREATED = "account.created"
    ACCOUNT_CLOSED  = "account.closed"

    # Alert events (published by observers, not by TransactionService)
    LOW_BALANCE        = "alert.low_balance"
    LARGE_TRANSACTION  = "alert.large_transaction"
    FRAUD_SUSPECTED    = "alert.fraud_suspected"

    # Fee events (Day 04)
    FEE_APPLIED = "fee.applied"
