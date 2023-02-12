"""
Tests — Day 02: AccountFactory & Account types
================================================
Test strategy:
  1. Factory behavior  — correct type created, errors on bad input
  2. Account rules     — each type enforces its own business rules
  3. Extensibility     — new types can be registered without modifying Factory
  4. Config integration — Factory reads limits from ConfigManager (Day 01)

Note: we reset both ConfigManager and AccountFactory between tests
to ensure complete isolation.
"""

import sys
import pytest

sys.path.insert(0, "src")

from bankcore.config_manager import ConfigManager
from bankcore.account_factory import AccountFactory
from bankcore.account import Account, CurrentAccount, SavingsAccount, ProAccount


@pytest.fixture(autouse=True)
def reset_state():
    """Reset Singleton and Factory registry before every test."""
    ConfigManager._reset()
    AccountFactory._reset_registry()
    yield
    ConfigManager._reset()
    AccountFactory._reset_registry()


# ---------------------------------------------------------------------------
# Factory behavior
# ---------------------------------------------------------------------------

class TestAccountFactoryCreation:

    def test_creates_current_account(self):
        account = AccountFactory.create("current", "Alice", 1000.0)
        assert isinstance(account, CurrentAccount)
        assert account.account_type == "current"

    def test_creates_savings_account(self):
        account = AccountFactory.create("savings", "Bob", 500.0)
        assert isinstance(account, SavingsAccount)
        assert account.account_type == "savings"

    def test_creates_pro_account(self):
        account = AccountFactory.create("pro", "Acme Corp", 10_000.0)
        assert isinstance(account, ProAccount)
        assert account.account_type == "pro"

    def test_client_receives_abstract_type(self):
        """The factory returns an Account — callers should not depend on concrete type."""
        account = AccountFactory.create("savings", "Alice", 500.0)
        assert isinstance(account, Account)

    def test_raises_on_unknown_type(self):
        with pytest.raises(ValueError, match="Unknown account type"):
            AccountFactory.create("crypto", "Alice")

    def test_raises_on_empty_owner(self):
        with pytest.raises(ValueError, match="Owner name"):
            AccountFactory.create("current", "")

    def test_raises_on_whitespace_owner(self):
        with pytest.raises(ValueError, match="Owner name"):
            AccountFactory.create("current", "   ")

    def test_raises_on_negative_deposit(self):
        with pytest.raises(ValueError):
            AccountFactory.create("current", "Alice", -100.0)

    def test_initial_balance_is_set(self):
        account = AccountFactory.create("current", "Alice", 750.0)
        assert account.balance == 750.0

    def test_zero_initial_deposit_is_valid(self):
        account = AccountFactory.create("current", "Alice", 0.0)
        assert account.balance == 0.0

    def test_each_account_has_unique_id(self):
        a = AccountFactory.create("current", "Alice", 100.0)
        b = AccountFactory.create("current", "Alice", 100.0)
        assert a.account_id != b.account_id

    def test_available_types_returns_all_defaults(self):
        types = AccountFactory.available_types()
        assert "current" in types
        assert "savings" in types
        assert "pro" in types


# ---------------------------------------------------------------------------
# CurrentAccount business rules
# ---------------------------------------------------------------------------

class TestCurrentAccount:

    def test_deposit_increases_balance(self):
        account = AccountFactory.create("current", "Alice", 500.0)
        result = account.deposit(200.0)
        assert result is True
        assert account.balance == 700.0

    def test_withdraw_decreases_balance(self):
        account = AccountFactory.create("current", "Alice", 500.0)
        result = account.withdraw(200.0)
        assert result is True
        assert account.balance == 300.0

    def test_withdraw_refuses_overdraft(self):
        account = AccountFactory.create("current", "Alice", 100.0)
        result = account.withdraw(150.0)
        assert result is False
        assert account.balance == 100.0  # unchanged

    def test_withdraw_refuses_above_daily_limit(self):
        account = CurrentAccount("Alice", initial_deposit=50_000.0, daily_limit=10_000.0)
        result = account.withdraw(10_001.0)
        assert result is False

    def test_withdraw_allows_at_daily_limit(self):
        account = CurrentAccount("Alice", initial_deposit=50_000.0, daily_limit=10_000.0)
        result = account.withdraw(10_000.0)
        assert result is True

    def test_deposit_refuses_zero(self):
        account = AccountFactory.create("current", "Alice", 100.0)
        assert account.deposit(0) is False

    def test_deposit_refuses_negative(self):
        account = AccountFactory.create("current", "Alice", 100.0)
        assert account.deposit(-50.0) is False


# ---------------------------------------------------------------------------
# SavingsAccount business rules
# ---------------------------------------------------------------------------

class TestSavingsAccount:

    def test_withdraw_respects_minimum_balance(self):
        """Cannot withdraw if balance would drop below 50 EUR minimum."""
        account = AccountFactory.create("savings", "Bob", 200.0)
        result = account.withdraw(160.0)   # would leave 40 EUR < 50 EUR min
        assert result is False
        assert account.balance == 200.0

    def test_withdraw_allows_up_to_minimum(self):
        account = AccountFactory.create("savings", "Bob", 200.0)
        result = account.withdraw(150.0)   # leaves exactly 50 EUR
        assert result is True
        assert account.balance == 50.0

    def test_apply_interest_credits_balance(self):
        account = SavingsAccount("Bob", initial_deposit=1_000.0, interest_rate=0.025)
        interest = account.apply_interest()
        assert interest == 25.0
        assert account.balance == 1_025.0

    def test_apply_interest_recorded_as_transaction(self):
        account = SavingsAccount("Bob", initial_deposit=1_000.0)
        account.apply_interest()
        txs = account.get_transactions()
        descriptions = [t["description"] for t in txs]
        assert "Annual interest" in descriptions

    def test_no_daily_limit_on_withdrawals(self):
        """Savings accounts have no daily transfer cap."""
        account = SavingsAccount("Bob", initial_deposit=100_000.0)
        result = account.withdraw(80_000.0)   # leaves 20k > 50 min
        assert result is True


# ---------------------------------------------------------------------------
# ProAccount business rules
# ---------------------------------------------------------------------------

class TestProAccount:

    def test_overdraft_is_allowed(self):
        account = AccountFactory.create("pro", "Acme Corp", 0.0)
        result = account.withdraw(4_000.0)   # goes to -4000, within -5000 limit
        assert result is True
        assert account.balance == -4_000.0

    def test_overdraft_limit_enforced(self):
        account = AccountFactory.create("pro", "Acme Corp", 0.0)
        result = account.withdraw(5_001.0)   # would exceed -5000 limit
        assert result is False

    def test_daily_limit_enforced(self):
        account = ProAccount("Acme Corp", initial_deposit=100_000.0, daily_limit=50_000.0)
        result = account.withdraw(50_001.0)
        assert result is False

    def test_daily_limit_respected(self):
        account = ProAccount("Acme Corp", initial_deposit=100_000.0, daily_limit=50_000.0)
        result = account.withdraw(50_000.0)
        assert result is True


# ---------------------------------------------------------------------------
# Extensibility — registering new account types
# ---------------------------------------------------------------------------

class TestFactoryExtensibility:

    def test_register_new_type(self):
        class YouthAccount(CurrentAccount):
            @property
            def account_type(self): return "youth"

        AccountFactory.register("youth", lambda o, d: YouthAccount(o, d, daily_limit=500.0))
        account = AccountFactory.create("youth", "Charlie", 100.0)

        assert account.account_type == "youth"
        assert "youth" in AccountFactory.available_types()

    def test_registered_type_enforces_its_own_rules(self):
        class YouthAccount(CurrentAccount):
            @property
            def account_type(self): return "youth"

        AccountFactory.register("youth", lambda o, d: YouthAccount(o, d, daily_limit=500.0))
        account = AccountFactory.create("youth", "Charlie", 1_000.0)

        # Youth account has 500 EUR daily limit
        assert account.withdraw(600.0) is False
        assert account.withdraw(500.0) is True


# ---------------------------------------------------------------------------
# Config integration (Day 01 + Day 02)
# ---------------------------------------------------------------------------

class TestConfigIntegration:

    def test_factory_reads_transfer_limit_from_config(self):
        """
        If ConfigManager sets a custom limit, newly created accounts respect it.
        This tests the connection between Day 01 and Day 02.
        """
        config = ConfigManager.get_instance()
        config.set("limits.max_transfer_amount", 1_000.0)

        # Re-initialize factory so it picks up the updated config
        AccountFactory._reset_registry()

        account = AccountFactory.create("current", "Alice", 5_000.0)
        # Should refuse amounts above the new 1000 EUR limit
        assert account.withdraw(1_001.0) is False
        assert account.withdraw(1_000.0) is True


# ---------------------------------------------------------------------------
# Account info and transaction history
# ---------------------------------------------------------------------------

class TestAccountReporting:

    def test_get_info_returns_required_fields(self):
        account = AccountFactory.create("current", "Alice", 500.0)
        info = account.get_info()

        assert "account_id" in info
        assert "owner_name" in info
        assert "account_type" in info
        assert "balance" in info
        assert "created_at" in info
        assert "transaction_count" in info

    def test_transaction_history_records_deposit(self):
        account = AccountFactory.create("current", "Alice", 0.0)
        account.deposit(300.0, "Salary")
        txs = account.get_transactions()
        assert any(t["description"] == "Salary" for t in txs)

    def test_transaction_history_records_withdrawal(self):
        account = AccountFactory.create("current", "Alice", 500.0)
        account.withdraw(100.0, "Rent")
        txs = account.get_transactions()
        assert any(t["description"] == "Rent" for t in txs)

    def test_balance_after_is_accurate(self):
        account = AccountFactory.create("current", "Alice", 0.0)
        account.deposit(500.0)
        account.withdraw(200.0)
        txs = account.get_transactions()
        last_tx = txs[-1]
        assert last_tx["balance_after"] == 300.0
