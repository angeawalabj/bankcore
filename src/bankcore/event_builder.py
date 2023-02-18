"""
BankCore — Day 06: EventBuilder
=================================
Extracted from TransactionService as part of the SRP refactoring.

Before Day 06: TransactionService built BankEvent objects inline,
               knowing every field name and expected value.
After  Day 06: EventBuilder owns event construction.
               TransactionService calls builder.transfer_event(...).

Single responsibility: construct well-formed BankEvent instances.
If a new field is added to BankEvent, only EventBuilder changes —
not every service that publishes events.

This also makes events testable in isolation:
    event = EventBuilder().transfer_event(alice, bob, 500.0)
    assert event.event_type == EventType.TRANSFER
"""

from bankcore.events import BankEvent, EventType


class EventBuilder:
    """
    Constructs BankEvent instances for all standard bank operations.

    Centralizes the knowledge of what fields each event carries.
    TransactionService, and any future service that publishes events,
    delegates event construction here.
    """

    @staticmethod
    def transfer_event(from_account, to_account, amount: float) -> BankEvent:
        """Build a TRANSFER event after a successful fund movement."""
        return BankEvent(
            event_type=EventType.TRANSFER,
            account_id=from_account.account_id,
            amount=amount,
            metadata={
                "from_account":  from_account.account_id,
                "to_account":    to_account.account_id,
                "from_owner":    from_account.owner_name,
                "to_owner":      to_account.owner_name,
                "balance_after": from_account.balance,
            },
        )

    @staticmethod
    def deposit_event(account, amount: float) -> BankEvent:
        """Build a DEPOSIT event after a successful credit."""
        return BankEvent(
            event_type=EventType.DEPOSIT,
            account_id=account.account_id,
            amount=amount,
            metadata={
                "owner":         account.owner_name,
                "balance_after": account.balance,
            },
        )

    @staticmethod
    def withdrawal_event(account, amount: float) -> BankEvent:
        """Build a WITHDRAWAL event after a successful debit."""
        return BankEvent(
            event_type=EventType.WITHDRAWAL,
            account_id=account.account_id,
            amount=amount,
            metadata={
                "owner":         account.owner_name,
                "balance_after": account.balance,
            },
        )

    @staticmethod
    def account_created_event(account) -> BankEvent:
        """Build an ACCOUNT_CREATED event when AccountFactory creates a new account."""
        return BankEvent(
            event_type=EventType.ACCOUNT_CREATED,
            account_id=account.account_id,
            amount=account.balance,
            metadata={
                "owner":        account.owner_name,
                "account_type": account.account_type,
            },
        )
