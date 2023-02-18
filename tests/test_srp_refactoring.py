"""
Tests — Day 06: SRP Refactoring
=================================
These tests verify the three new classes extracted for SRP:
  1. TransactionHistory — complete isolation from Account
  2. AccountConfigResolver — reads ConfigManager correctly
  3. EventBuilder — produces well-formed BankEvents

Key assertion: the refactoring is transparent.
All 148 existing tests pass. These 30+ new tests add coverage
for the extracted responsibilities specifically.
"""

import sys
import pytest
from datetime import date

sys.path.insert(0, "src")

from bankcore.config_manager import ConfigManager
from bankcore.account_factory import AccountFactory
from bankcore.alert_system import AlertSystem
from bankcore.transaction_history import TransactionHistory, TransactionRecord
from bankcore.account_config import AccountConfigResolver
from bankcore.event_builder import EventBuilder
from bankcore.events import EventType


@pytest.fixture(autouse=True)
def reset_state():
    ConfigManager._reset()
    AlertSystem._reset()
    AccountFactory._reset_registry()
    yield
    ConfigManager._reset()
    AlertSystem._reset()
    AccountFactory._reset_registry()


# ---------------------------------------------------------------------------
# TransactionHistory — isolated unit tests
# ---------------------------------------------------------------------------

class TestTransactionHistory:

    def test_starts_empty(self):
        h = TransactionHistory()
        assert h.count() == 0
        assert h.get_all() == []

    def test_record_appends_entry(self):
        h = TransactionHistory()
        h.record(500.0, "Salary", 500.0)
        assert h.count() == 1

    def test_record_returns_transaction_record(self):
        h = TransactionHistory()
        rec = h.record(100.0, "Test", 100.0)
        assert isinstance(rec, TransactionRecord)
        assert rec.amount == 100.0
        assert rec.description == "Test"
        assert rec.balance_after == 100.0

    def test_get_all_returns_dicts(self):
        h = TransactionHistory()
        h.record(100.0, "Deposit", 100.0)
        records = h.get_all()
        assert isinstance(records[0], dict)
        assert "id" in records[0]
        assert "amount" in records[0]
        assert "description" in records[0]
        assert "date" in records[0]
        assert "balance_after" in records[0]

    def test_get_all_returns_copy(self):
        h = TransactionHistory()
        h.record(100.0, "Deposit", 100.0)
        records = h.get_all()
        records.clear()
        assert h.count() == 1  # internal list unchanged

    def test_last_returns_most_recent(self):
        h = TransactionHistory()
        h.record(100.0, "First",  100.0)
        h.record(200.0, "Second", 300.0)
        assert h.last().description == "Second"

    def test_last_returns_none_when_empty(self):
        assert TransactionHistory().last() is None

    def test_total_credits_sums_positive_amounts(self):
        h = TransactionHistory()
        h.record(500.0,  "Salary",      500.0)
        h.record(200.0,  "Transfer in", 700.0)
        h.record(-150.0, "Rent",        550.0)
        assert h.total_credits() == 700.0

    def test_total_debits_sums_negative_amounts(self):
        h = TransactionHistory()
        h.record(500.0,  "Salary", 500.0)
        h.record(-200.0, "Rent",   300.0)
        h.record(-50.0,  "Fee",    250.0)
        assert h.total_debits() == 250.0  # returned as positive

    def test_filter_by_description(self):
        h = TransactionHistory()
        h.record(1000.0, "Monthly Salary", 1000.0)
        h.record(-200.0, "Rent payment",    800.0)
        h.record(-50.0,  "Transfer fee",    750.0)
        results = h.filter_by_description("salary")
        assert len(results) == 1
        assert results[0].description == "Monthly Salary"

    def test_records_are_immutable(self):
        h = TransactionHistory()
        rec = h.record(100.0, "Test", 100.0)
        with pytest.raises(Exception):
            rec.amount = 999.0

    def test_len_dunder(self):
        h = TransactionHistory()
        h.record(100.0, "A", 100.0)
        h.record(200.0, "B", 300.0)
        assert len(h) == 2


# ---------------------------------------------------------------------------
# Account integration — TransactionHistory delegated correctly
# ---------------------------------------------------------------------------

class TestAccountUsesTransactionHistory:

    def test_initial_deposit_recorded(self):
        account = AccountFactory.create("current", "Alice", 500.0)
        txs = account.get_transactions()
        assert len(txs) == 1
        assert txs[0]["description"] == "Initial deposit"
        assert txs[0]["balance_after"] == 500.0

    def test_deposit_recorded(self):
        account = AccountFactory.create("current", "Alice", 0.0)
        account.deposit(300.0, "Salary")
        txs = account.get_transactions()
        assert any(t["description"] == "Salary" for t in txs)

    def test_withdrawal_recorded(self):
        account = AccountFactory.create("current", "Alice", 500.0)
        account.withdraw(100.0, "Groceries")
        txs = account.get_transactions()
        assert any(t["description"] == "Groceries" for t in txs)

    def test_transaction_count_in_get_info(self):
        account = AccountFactory.create("current", "Alice", 500.0)
        account.deposit(100.0)
        account.withdraw(50.0)
        info = account.get_info()
        assert info["transaction_count"] == 3  # initial + deposit + withdrawal

    def test_balance_after_accurate_in_history(self):
        account = AccountFactory.create("current", "Alice", 0.0)
        account.deposit(500.0)
        account.withdraw(200.0)
        txs = account.get_transactions()
        assert txs[-1]["balance_after"] == 300.0


# ---------------------------------------------------------------------------
# AccountConfigResolver
# ---------------------------------------------------------------------------

class TestAccountConfigResolver:

    def test_resolves_current_daily_limit(self):
        resolver = AccountConfigResolver()
        limit = resolver.resolve_daily_limit("current")
        assert limit == 10_000.0

    def test_resolves_savings_min_balance(self):
        resolver = AccountConfigResolver()
        assert resolver.resolve_min_balance("savings") == 50.0

    def test_resolves_pro_overdraft(self):
        resolver = AccountConfigResolver()
        assert resolver.resolve_overdraft("pro") == -5_000.0

    def test_resolves_savings_interest_rate(self):
        resolver = AccountConfigResolver()
        assert resolver.resolve_interest_rate("savings") == 0.025

    def test_global_config_caps_daily_limit(self):
        ConfigManager.get_instance().set("limits.max_transfer_amount", 5_000.0)
        resolver = AccountConfigResolver()
        # Current default is 10k but global cap is 5k
        limit = resolver.resolve_daily_limit("current")
        assert limit == 5_000.0

    def test_resolve_all_returns_complete_dict(self):
        resolver = AccountConfigResolver()
        params = resolver.resolve_all("savings")
        assert "daily_limit"   in params
        assert "overdraft"     in params
        assert "min_balance"   in params
        assert "monthly_fee"   in params
        assert "interest_rate" in params

    def test_unknown_type_returns_current_defaults(self):
        resolver = AccountConfigResolver()
        limit = resolver.resolve_daily_limit("unknown_future_type")
        assert limit == 10_000.0

    def test_supported_types(self):
        resolver = AccountConfigResolver()
        types = resolver.supported_types()
        assert "current" in types
        assert "savings" in types
        assert "pro" in types

    def test_factory_uses_resolver_limits(self):
        """Verify AccountFactory correctly applies resolver limits to new accounts."""
        ConfigManager.get_instance().set("limits.max_transfer_amount", 2_000.0)
        AccountFactory._reset_registry()

        account = AccountFactory.create("current", "Alice", 5_000.0)
        # Should refuse amounts above the 2000 EUR limit set via config
        assert account.withdraw(2_001.0) is False
        assert account.withdraw(2_000.0) is True


# ---------------------------------------------------------------------------
# EventBuilder
# ---------------------------------------------------------------------------

class TestEventBuilder:

    def test_transfer_event_type(self):
        alice = AccountFactory.create("current", "Alice", 1_000.0)
        bob   = AccountFactory.create("savings", "Bob",   1_000.0)
        alice.withdraw(200.0)  # simulate balance change
        event = EventBuilder.transfer_event(alice, bob, 200.0)
        assert event.event_type == EventType.TRANSFER

    def test_transfer_event_account_id(self):
        alice = AccountFactory.create("current", "Alice", 1_000.0)
        bob   = AccountFactory.create("savings", "Bob",   1_000.0)
        event = EventBuilder.transfer_event(alice, bob, 300.0)
        assert event.account_id == alice.account_id

    def test_transfer_event_metadata_keys(self):
        alice = AccountFactory.create("current", "Alice", 1_000.0)
        bob   = AccountFactory.create("savings", "Bob",   1_000.0)
        event = EventBuilder.transfer_event(alice, bob, 300.0)
        assert "from_account"  in event.metadata
        assert "to_account"    in event.metadata
        assert "balance_after" in event.metadata

    def test_deposit_event_type(self):
        alice = AccountFactory.create("current", "Alice", 0.0)
        alice.deposit(500.0)
        event = EventBuilder.deposit_event(alice, 500.0)
        assert event.event_type == EventType.DEPOSIT

    def test_deposit_event_amount(self):
        alice = AccountFactory.create("current", "Alice", 0.0)
        event = EventBuilder.deposit_event(alice, 750.0)
        assert event.amount == 750.0

    def test_withdrawal_event_type(self):
        alice = AccountFactory.create("current", "Alice", 1_000.0)
        event = EventBuilder.withdrawal_event(alice, 200.0)
        assert event.event_type == EventType.WITHDRAWAL

    def test_account_created_event(self):
        alice = AccountFactory.create("current", "Alice", 500.0)
        event = EventBuilder.account_created_event(alice)
        assert event.event_type == EventType.ACCOUNT_CREATED
        assert event.metadata["account_type"] == "current"
        assert event.metadata["owner"] == "Alice"

    def test_events_are_immutable(self):
        alice = AccountFactory.create("current", "Alice", 500.0)
        event = EventBuilder.deposit_event(alice, 100.0)
        with pytest.raises(Exception):
            event.amount = 999.0
