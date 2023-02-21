"""
Tests — Day 09: Interface Segregation Principle
================================================
Core assertion: clients depend only on the interface they actually use.

Test strategy:
  1. isinstance() checks — correct interface satisfaction
  2. InterestBearing — only SavingsAccount satisfies it
  3. Overdraftable — only ProAccount satisfies it
  4. Readable / Transactable — all Account subtypes satisfy both
  5. Depositable / Withdrawable / Transferable — TransactionProcessor satisfies all
  6. ISP in action — service functions typed to minimal interface
  7. Negative cases — CurrentAccount does NOT satisfy InterestBearing
"""

import sys
import pytest

sys.path.insert(0, "src")

from bankcore.config_manager import ConfigManager
from bankcore.account_factory import AccountFactory
from bankcore.alert_system import AlertSystem
from bankcore.account_type_registry import AccountTypeRegistry
from bankcore.account import Account, CurrentAccount, SavingsAccount, ProAccount
from bankcore.interfaces import (
    Readable, Transactable, InterestBearing, Overdraftable,
    Depositable, Withdrawable, Transferable,
    EventHandler, EventFilter,
)
from bankcore.transaction_service import TransactionService
from bankcore.transaction_processor import TransactionProcessor
from bankcore.alert_system import AlertObserver, AuditLogger, FraudDetector


@pytest.fixture(autouse=True)
def reset_state():
    ConfigManager._reset()
    AlertSystem._reset()
    AccountTypeRegistry._reset()
    AccountTypeRegistry._register_defaults()
    AccountFactory._reset_registry()
    yield
    ConfigManager._reset()
    AlertSystem._reset()
    AccountTypeRegistry._reset()
    AccountTypeRegistry._register_defaults()
    AccountFactory._reset_registry()


# ---------------------------------------------------------------------------
# Readable — all account types
# ---------------------------------------------------------------------------

class TestReadableInterface:

    @pytest.mark.parametrize("account_type", ["current", "savings", "pro"])
    def test_all_accounts_are_readable(self, account_type):
        account = AccountFactory.create(account_type, "Test", 500.0)
        assert isinstance(account, Readable)

    @pytest.mark.parametrize("account_type", ["current", "savings", "pro"])
    def test_readable_get_info_works(self, account_type):
        account: Readable = AccountFactory.create(account_type, "Test", 500.0)
        info = account.get_info()
        assert isinstance(info, dict)
        assert "balance" in info

    @pytest.mark.parametrize("account_type", ["current", "savings", "pro"])
    def test_readable_get_transactions_works(self, account_type):
        account: Readable = AccountFactory.create(account_type, "Test", 500.0)
        txs = account.get_transactions()
        assert isinstance(txs, list)

    def test_read_only_service_works_with_any_account(self):
        """
        ISP in action: a reporting service typed to Readable cannot
        accidentally call deposit() or withdraw().
        """
        def generate_statement(account: Readable) -> str:
            info = account.get_info()
            return (f"Statement for {info['owner_name']}: "
                    f"{info['balance']:.2f} EUR | "
                    f"{info['transaction_count']} transactions")

        for t in ["current", "savings", "pro"]:
            account = AccountFactory.create(t, "Alice", 1_000.0)
            statement = generate_statement(account)
            assert "Alice" in statement
            assert "1000" in statement


# ---------------------------------------------------------------------------
# Transactable — all account types
# ---------------------------------------------------------------------------

class TestTransactableInterface:

    @pytest.mark.parametrize("account_type", ["current", "savings", "pro"])
    def test_all_accounts_are_transactable(self, account_type):
        account = AccountFactory.create(account_type, "Test", 500.0)
        assert isinstance(account, Transactable)

    @pytest.mark.parametrize("account_type", ["current", "savings", "pro"])
    def test_transactable_deposit_works(self, account_type):
        account: Transactable = AccountFactory.create(account_type, "Test", 0.0)
        result = account.deposit(200.0)
        assert result is True

    @pytest.mark.parametrize("account_type", ["current", "savings", "pro"])
    def test_transactable_withdraw_works(self, account_type):
        account: Transactable = AccountFactory.create(account_type, "Test", 1_000.0)
        result = account.withdraw(100.0)
        assert result is True

    def test_fee_service_only_needs_transactable(self):
        """
        A fee processor only needs Transactable — not get_info() or history.
        ISP: it doesn't even know Account exists.
        """
        def deduct_fee(account: Transactable, fee: float) -> bool:
            return account.withdraw(fee, description="Monthly fee")

        for t in ["current", "savings", "pro"]:
            account = AccountFactory.create(t, "Test", 500.0)
            result = deduct_fee(account, 2.0)
            assert result is True


# ---------------------------------------------------------------------------
# InterestBearing — ONLY SavingsAccount
# ---------------------------------------------------------------------------

class TestInterestBearingInterface:

    def test_savings_account_is_interest_bearing(self):
        account = AccountFactory.create("savings", "Bob", 1_000.0)
        assert isinstance(account, InterestBearing)

    def test_current_account_is_NOT_interest_bearing(self):
        account = AccountFactory.create("current", "Alice", 1_000.0)
        assert not isinstance(account, InterestBearing)

    def test_pro_account_is_NOT_interest_bearing(self):
        account = AccountFactory.create("pro", "Acme", 10_000.0)
        assert not isinstance(account, InterestBearing)

    def test_interest_service_typed_to_interface(self):
        """
        ISP: InterestService depends on InterestBearing, not SavingsAccount.
        No isinstance(account, SavingsAccount) anywhere.
        """
        def apply_all_interest(accounts: list[InterestBearing]) -> dict:
            results = {}
            for acc in accounts:
                interest = acc.apply_interest()
                results[acc.account_id] = interest
            return results

        savings1 = AccountFactory.create("savings", "Bob",   1_000.0)
        savings2 = AccountFactory.create("savings", "Carol", 5_000.0)

        # Only savings accounts passed — type system enforces this
        results = apply_all_interest([savings1, savings2])

        assert len(results) == 2
        assert results[savings1.account_id] == pytest.approx(25.0)
        assert results[savings2.account_id] == pytest.approx(125.0)

    def test_interest_bearing_has_interest_rate(self):
        account: InterestBearing = AccountFactory.create("savings", "Bob", 1_000.0)
        assert account.interest_rate == 0.025

    def test_apply_interest_returns_credited_amount(self):
        account: InterestBearing = AccountFactory.create("savings", "Bob", 1_000.0)
        credited = account.apply_interest()
        assert credited == pytest.approx(25.0)
        assert account.balance == pytest.approx(1_025.0)

    def test_filtering_interest_bearing_from_mixed_list(self):
        """
        ISP eliminates isinstance(account, SavingsAccount) checks.
        Use isinstance(account, InterestBearing) instead — more extensible.
        """
        accounts: list[Account] = [
            AccountFactory.create("current", "Alice", 1_000.0),
            AccountFactory.create("savings", "Bob",   2_000.0),
            AccountFactory.create("pro",     "Acme",  5_000.0),
            AccountFactory.create("savings", "Carol", 3_000.0),
        ]

        # Filter without knowing concrete types
        interest_bearing = [a for a in accounts if isinstance(a, InterestBearing)]
        assert len(interest_bearing) == 2

        # Apply interest to all that support it
        for acc in interest_bearing:
            acc.apply_interest()

        assert accounts[1].balance == pytest.approx(2_050.0)
        assert accounts[3].balance == pytest.approx(3_075.0)


# ---------------------------------------------------------------------------
# Overdraftable — ONLY ProAccount
# ---------------------------------------------------------------------------

class TestOverdraftableInterface:

    def test_pro_account_is_overdraftable(self):
        account = AccountFactory.create("pro", "Acme", 0.0)
        assert isinstance(account, Overdraftable)

    def test_current_account_is_NOT_overdraftable(self):
        account = AccountFactory.create("current", "Alice", 500.0)
        assert not isinstance(account, Overdraftable)

    def test_savings_account_is_NOT_overdraftable(self):
        account = AccountFactory.create("savings", "Bob", 500.0)
        assert not isinstance(account, Overdraftable)

    def test_overdraft_used_zero_when_positive_balance(self):
        account: Overdraftable = AccountFactory.create("pro", "Acme", 1_000.0)
        assert account.overdraft_used() == 0.0

    def test_overdraft_used_reflects_negative_balance(self):
        account: Overdraftable = AccountFactory.create("pro", "Acme", 0.0)
        account.withdraw(3_000.0)
        assert account.overdraft_used() == pytest.approx(3_000.0)

    def test_risk_service_typed_to_overdraftable(self):
        """
        ISP: a risk monitoring service depends on Overdraftable, not ProAccount.
        """
        def check_overdraft_exposure(accounts: list[Overdraftable]) -> float:
            return sum(acc.overdraft_used() for acc in accounts)

        pro1 = AccountFactory.create("pro", "Acme",  0.0)
        pro2 = AccountFactory.create("pro", "Globo", 0.0)
        pro1.withdraw(2_000.0)
        pro2.withdraw(1_500.0)

        exposure = check_overdraft_exposure([pro1, pro2])
        assert exposure == pytest.approx(3_500.0)


# ---------------------------------------------------------------------------
# Depositable / Withdrawable / Transferable — TransactionProcessor
# ---------------------------------------------------------------------------

class TestTransactionProcessorInterfaces:

    def test_transaction_service_is_depositable(self):
        assert isinstance(TransactionService(), Depositable)

    def test_transaction_service_is_withdrawable(self):
        assert isinstance(TransactionService(), Withdrawable)

    def test_transaction_service_is_transferable(self):
        assert isinstance(TransactionService(), Transferable)

    def test_transaction_processor_is_all_three(self):
        service = TransactionService()
        assert isinstance(service, Depositable)
        assert isinstance(service, Withdrawable)
        assert isinstance(service, Transferable)

    def test_batch_deposit_service_typed_to_depositable(self):
        """
        ISP: a batch deposit system only needs Depositable.
        It cannot accidentally call transfer().
        """
        def batch_deposit(
            processor: Depositable,
            account,
            amounts: list[float],
        ) -> int:
            return sum(1 for amt in amounts
                       if processor.deposit(account, amt)["success"])

        service = TransactionService()
        account = AccountFactory.create("current", "Alice", 0.0)
        count   = batch_deposit(service, account, [100.0, 200.0, 300.0])
        assert count == 3

    def test_transfer_only_service_typed_to_transferable(self):
        """
        A wire transfer service only needs Transferable.
        """
        def wire_transfer(
            processor: Transferable,
            from_acc,
            to_acc,
            amount: float,
        ) -> bool:
            return processor.transfer(from_acc, to_acc, amount)["success"]

        service = TransactionService()
        alice   = AccountFactory.create("current", "Alice", 1_000.0)
        bob     = AccountFactory.create("savings", "Bob",   500.0)
        result  = wire_transfer(service, alice, bob, 200.0)
        assert result is True


# ---------------------------------------------------------------------------
# EventHandler / EventFilter — AlertSystem observers
# ---------------------------------------------------------------------------

class TestEventInterfaces:

    def test_alert_observer_is_event_handler(self):
        class SimpleObserver(AlertObserver):
            def on_event(self, event): pass
            def supported_events(self): return ["*"]

        obs = SimpleObserver()
        assert isinstance(obs, EventHandler)

    def test_audit_logger_is_event_handler(self):
        assert isinstance(AuditLogger(), EventHandler)

    def test_audit_logger_receives_all_events_without_filter(self):
        """
        AuditLogger subscribes to '*' — it uses supported_events() as
        a convention, not as a formal EventFilter implementation.
        ISP: it's fine that AuditLogger doesn't formally implement EventFilter.
        """
        audit = AuditLogger()
        assert audit.supported_events() == ["*"]

    def test_fraud_detector_implements_event_filter(self):
        """
        FraudDetector only cares about specific events — it's a natural EventFilter.
        """
        detector = FraudDetector()
        assert isinstance(detector, EventFilter)
        assert EventFilter in type(detector).__mro__ or hasattr(detector, "supported_events")


# ---------------------------------------------------------------------------
# ISP violation prevention — key negative tests
# ---------------------------------------------------------------------------

class TestISPViolationPrevention:

    def test_no_apply_interest_on_current_account(self):
        """The most important ISP test: CurrentAccount has no apply_interest()."""
        account = AccountFactory.create("current", "Alice", 1_000.0)
        assert not hasattr(account, "apply_interest"), \
            "CurrentAccount must NOT have apply_interest() — ISP violation"

    def test_no_apply_interest_on_pro_account(self):
        account = AccountFactory.create("pro", "Acme", 1_000.0)
        assert not hasattr(account, "apply_interest"), \
            "ProAccount must NOT have apply_interest() — ISP violation"

    def test_no_overdraft_methods_on_current_account(self):
        account = AccountFactory.create("current", "Alice", 500.0)
        assert not hasattr(account, "overdraft_used"), \
            "CurrentAccount must NOT have overdraft_used() — ISP violation"

    def test_interest_service_cannot_receive_current_account(self):
        """
        Formal ISP proof: a function typed to InterestBearing
        cannot be called with CurrentAccount — isinstance check fails.
        """
        current = AccountFactory.create("current", "Alice", 1_000.0)
        savings = AccountFactory.create("savings", "Bob",   1_000.0)

        def interest_service(account: InterestBearing) -> float:
            return account.apply_interest()

        # savings: passes isinstance check → works
        assert isinstance(savings, InterestBearing)
        result = interest_service(savings)
        assert result == pytest.approx(25.0)

        # current: fails isinstance check → service should not be called
        assert not isinstance(current, InterestBearing)
