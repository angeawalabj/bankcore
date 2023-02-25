"""
Tests — Day 11: Layered Architecture & Use Cases
=================================================
Test strategy:
  1. Commands — validation at the boundary
  2. UseCaseResult — structured output
  3. Each Use Case in isolation with injected fakes
  4. BankApplicationService — integration through the full application layer
  5. Layer isolation — domain doesn't know use cases, use cases don't know CLI
  6. Full flow: create → deposit → transfer → interest
"""

import sys
import pytest

sys.path.insert(0, "src")

from bankcore.config_manager import ConfigManager
from bankcore.account_factory import AccountFactory
from bankcore.alert_system import AlertSystem
from bankcore.account_type_registry import AccountTypeRegistry
from bankcore.protocols import FakeConfig, SpyAlertSystem
from bankcore.container import BankContainer
from bankcore.application.commands import (
    TransferCommand, DepositCommand, WithdrawCommand,
    CreateAccountCommand, ApplyInterestCommand,
    UseCaseResult,
)
from bankcore.application.use_cases import (
    AccountRegistry,
    TransferUseCase, DepositUseCase, WithdrawUseCase,
    CreateAccountUseCase, ApplyInterestUseCase,
    BankApplicationService,
)


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


@pytest.fixture
def container():
    return BankContainer.build_for_testing()


@pytest.fixture
def registry():
    return AccountRegistry()


@pytest.fixture
def app_service(container):
    return BankApplicationService(container)


@pytest.fixture
def alice(app_service):
    cmd = CreateAccountCommand("Alice Martin", "current", 2_000.0, "system")
    result = app_service.create_account(cmd)
    return result.data["account_id"]


@pytest.fixture
def bob(app_service):
    cmd = CreateAccountCommand("Bob Dupont", "savings", 1_000.0, "system")
    result = app_service.create_account(cmd)
    return result.data["account_id"]


# ---------------------------------------------------------------------------
# Commands — validation at the boundary
# ---------------------------------------------------------------------------

class TestCommands:

    def test_transfer_command_validates_positive_amount(self):
        with pytest.raises(ValueError, match="positive"):
            TransferCommand("A", "B", -100.0, "user")

    def test_transfer_command_validates_different_accounts(self):
        with pytest.raises(ValueError, match="differ"):
            TransferCommand("A", "A", 100.0, "user")

    def test_transfer_command_requires_from_account(self):
        with pytest.raises(ValueError):
            TransferCommand("", "B", 100.0, "user")

    def test_transfer_command_is_immutable(self):
        cmd = TransferCommand("A", "B", 100.0, "user")
        with pytest.raises(Exception):
            cmd.amount = 999.0

    def test_deposit_command_validates_amount(self):
        with pytest.raises(ValueError):
            DepositCommand("A", 0.0, "user")

    def test_deposit_command_requires_account_id(self):
        with pytest.raises(ValueError):
            DepositCommand("", 100.0, "user")

    def test_withdraw_command_validates_amount(self):
        with pytest.raises(ValueError):
            WithdrawCommand("A", -50.0, "user")

    def test_create_account_command_requires_owner(self):
        with pytest.raises(ValueError):
            CreateAccountCommand("", "current", 100.0, "system")

    def test_create_account_command_rejects_negative_deposit(self):
        with pytest.raises(ValueError):
            CreateAccountCommand("Alice", "current", -100.0, "system")

    def test_apply_interest_requires_account_id(self):
        with pytest.raises(ValueError):
            ApplyInterestCommand("", "scheduler")


# ---------------------------------------------------------------------------
# UseCaseResult
# ---------------------------------------------------------------------------

class TestUseCaseResult:

    def test_ok_result_is_truthy(self):
        result = UseCaseResult.ok(amount=100.0)
        assert bool(result) is True
        assert result.success is True

    def test_fail_result_is_falsy(self):
        result = UseCaseResult.fail("Something went wrong")
        assert bool(result) is False
        assert result.success is False

    def test_ok_result_carries_data(self):
        result = UseCaseResult.ok(account_id="A1", balance=500.0)
        assert result.data["account_id"] == "A1"
        assert result.data["balance"] == 500.0

    def test_fail_result_carries_error(self):
        result = UseCaseResult.fail("Account not found", code="ACCOUNT_NOT_FOUND")
        assert result.error == "Account not found"
        assert result.error_code == "ACCOUNT_NOT_FOUND"

    def test_ok_result_has_no_error(self):
        result = UseCaseResult.ok()
        assert result.error is None
        assert result.error_code is None


# ---------------------------------------------------------------------------
# CreateAccountUseCase
# ---------------------------------------------------------------------------

class TestCreateAccountUseCase:

    def test_creates_account_successfully(self, app_service):
        cmd    = CreateAccountCommand("Alice", "current", 500.0, "teller-01")
        result = app_service.create_account(cmd)
        assert result.success is True
        assert result.data["owner_name"] == "Alice"
        assert result.data["account_type"] == "current"
        assert result.data["initial_balance"] == 500.0

    def test_returns_account_id(self, app_service):
        cmd    = CreateAccountCommand("Bob", "savings", 0.0, "system")
        result = app_service.create_account(cmd)
        assert "account_id" in result.data
        assert len(result.data["account_id"]) > 0

    def test_rejects_unknown_account_type(self, app_service):
        cmd    = CreateAccountCommand("Alice", "crypto", 500.0, "system")
        result = app_service.create_account(cmd)
        assert result.success is False
        assert result.error_code == "INVALID_ACCOUNT_TYPE"

    def test_account_persisted_in_registry(self, app_service):
        cmd    = CreateAccountCommand("Alice", "current", 500.0, "system")
        result = app_service.create_account(cmd)
        account_id = result.data["account_id"]
        found = app_service.get_account(account_id)
        assert found is not None
        assert found["owner_name"] == "Alice"

    def test_publishes_account_created_event(self, container):
        spy     = container.alert_system
        service = BankApplicationService(container)
        service.create_account(CreateAccountCommand("Alice", "current", 100.0, "sys"))
        from bankcore.events import EventType
        assert spy.was_published(EventType.ACCOUNT_CREATED)


# ---------------------------------------------------------------------------
# DepositUseCase
# ---------------------------------------------------------------------------

class TestDepositUseCase:

    def test_deposit_increases_balance(self, app_service, alice):
        before = app_service.get_account(alice)["balance"]
        cmd    = DepositCommand(alice, 300.0, "teller-01")
        result = app_service.deposit(cmd)
        assert result.success is True
        assert result.data["balance_after"] == before + 300.0

    def test_deposit_unknown_account_fails(self, app_service):
        cmd    = DepositCommand("NONEXISTENT", 100.0, "system")
        result = app_service.deposit(cmd)
        assert result.success is False
        assert result.error_code == "ACCOUNT_NOT_FOUND"

    def test_deposit_persists_balance(self, app_service, alice):
        app_service.deposit(DepositCommand(alice, 200.0, "sys"))
        info = app_service.get_account(alice)
        assert info["balance"] == 2_200.0   # initial 2000 + 200


# ---------------------------------------------------------------------------
# WithdrawUseCase
# ---------------------------------------------------------------------------

class TestWithdrawUseCase:

    def test_withdraw_decreases_balance(self, app_service, alice):
        cmd    = WithdrawCommand(alice, 500.0, "atm-01")
        result = app_service.withdraw(cmd)
        assert result.success is True
        assert result.data["balance_after"] == 1_500.0

    def test_withdraw_unknown_account_fails(self, app_service):
        cmd    = WithdrawCommand("NONEXISTENT", 100.0, "atm")
        result = app_service.withdraw(cmd)
        assert result.success is False
        assert result.error_code == "ACCOUNT_NOT_FOUND"

    def test_withdraw_insufficient_funds_fails(self, app_service, alice):
        cmd    = WithdrawCommand(alice, 99_999.0, "atm")
        result = app_service.withdraw(cmd)
        assert result.success is False
        assert result.error_code == "WITHDRAWAL_REJECTED"

    def test_withdraw_saves_updated_balance(self, app_service, alice):
        app_service.withdraw(WithdrawCommand(alice, 100.0, "atm"))
        info = app_service.get_account(alice)
        assert info["balance"] == 1_900.0


# ---------------------------------------------------------------------------
# TransferUseCase
# ---------------------------------------------------------------------------

class TestTransferUseCase:

    def test_transfer_moves_funds(self, app_service, alice, bob):
        cmd    = TransferCommand(alice, bob, 500.0, "user-42")
        result = app_service.transfer(cmd)
        assert result.success is True
        assert result.data["from_balance_after"] == 1_500.0
        assert result.data["to_balance_after"]   == 1_500.0

    def test_transfer_unknown_sender_fails(self, app_service, bob):
        cmd    = TransferCommand("GHOST", bob, 100.0, "user")
        result = app_service.transfer(cmd)
        assert result.success is False
        assert result.error_code == "ACCOUNT_NOT_FOUND"

    def test_transfer_unknown_receiver_fails(self, app_service, alice):
        cmd    = TransferCommand(alice, "GHOST", 100.0, "user")
        result = app_service.transfer(cmd)
        assert result.success is False
        assert result.error_code == "ACCOUNT_NOT_FOUND"

    def test_transfer_insufficient_funds_fails(self, app_service, alice, bob):
        cmd    = TransferCommand(alice, bob, 50_000.0, "user")
        result = app_service.transfer(cmd)
        assert result.success is False
        assert result.error_code == "TRANSFER_REJECTED"

    def test_transfer_balances_persist(self, app_service, alice, bob):
        app_service.transfer(TransferCommand(alice, bob, 300.0, "user"))
        alice_info = app_service.get_account(alice)
        bob_info   = app_service.get_account(bob)
        assert alice_info["balance"] == 1_700.0
        assert bob_info["balance"]   == 1_300.0


# ---------------------------------------------------------------------------
# ApplyInterestUseCase
# ---------------------------------------------------------------------------

class TestApplyInterestUseCase:

    def test_applies_interest_to_savings(self, app_service, bob):
        cmd    = ApplyInterestCommand(bob, "scheduler")
        result = app_service.apply_interest(cmd)
        assert result.success is True
        assert result.data["interest_credited"] == pytest.approx(25.0)
        assert result.data["new_balance"]        == pytest.approx(1_025.0)

    def test_rejects_non_savings_account(self, app_service, alice):
        cmd    = ApplyInterestCommand(alice, "scheduler")
        result = app_service.apply_interest(cmd)
        assert result.success is False
        assert result.error_code == "NOT_INTEREST_BEARING"

    def test_rejects_unknown_account(self, app_service):
        cmd    = ApplyInterestCommand("GHOST", "scheduler")
        result = app_service.apply_interest(cmd)
        assert result.success is False
        assert result.error_code == "ACCOUNT_NOT_FOUND"

    def test_interest_persists_in_registry(self, app_service, bob):
        app_service.apply_interest(ApplyInterestCommand(bob, "scheduler"))
        info = app_service.get_account(bob)
        assert info["balance"] == pytest.approx(1_025.0)


# ---------------------------------------------------------------------------
# BankApplicationService integration
# ---------------------------------------------------------------------------

class TestBankApplicationServiceIntegration:

    def test_list_accounts_empty_initially(self, app_service):
        assert app_service.list_accounts() == []

    def test_list_accounts_after_creation(self, app_service):
        app_service.create_account(CreateAccountCommand("Alice", "current", 100.0, "sys"))
        app_service.create_account(CreateAccountCommand("Bob",   "savings", 200.0, "sys"))
        accounts = app_service.list_accounts()
        assert len(accounts) == 2

    def test_get_account_returns_none_for_unknown(self, app_service):
        assert app_service.get_account("GHOST") is None

    def test_full_banking_flow(self, app_service):
        """
        End-to-end flow through the Application layer:
        create → deposit → transfer → interest → verify balances.
        """
        # Create accounts
        r1 = app_service.create_account(
            CreateAccountCommand("Alice", "current", 5_000.0, "system"))
        r2 = app_service.create_account(
            CreateAccountCommand("Bob",   "savings", 1_000.0, "system"))
        alice_id = r1.data["account_id"]
        bob_id   = r2.data["account_id"]

        # Alice receives salary
        app_service.deposit(DepositCommand(alice_id, 3_000.0, "payroll"))

        # Alice pays Bob
        app_service.transfer(TransferCommand(alice_id, bob_id, 500.0, "alice"))

        # Bob earns interest
        app_service.apply_interest(ApplyInterestCommand(bob_id, "scheduler"))

        # Verify final state
        alice_info = app_service.get_account(alice_id)
        bob_info   = app_service.get_account(bob_id)

        assert alice_info["balance"] == 7_500.0   # 5000 + 3000 - 500
        assert bob_info["balance"]   == pytest.approx(1_537.5)  # (1000+500)*1.025

    def test_use_cases_do_not_import_presentation_layer(self):
        """
        Layer isolation: use cases must not import from presentation.
        This test verifies the layered architecture rule programmatically.
        """
        import importlib, sys
        # Import the use_cases module
        uc_module = importlib.import_module("bankcore.application.use_cases")
        source = open(uc_module.__file__).read()

        # Use Cases must not reference CLI or HTTP-layer concerns
        forbidden = ["flask", "fastapi", "click.command", "argparse", "http.server"]
        for term in forbidden:
            assert term not in source.lower(), \
                f"Use Case imports presentation concern: '{term}'"

    def test_domain_does_not_import_use_cases(self):
        """
        Layer isolation: domain (Account) must not import application layer.
        """
        import importlib
        account_module = importlib.import_module("bankcore.account")
        source = open(account_module.__file__).read()

        forbidden = ["use_cases", "commands", "application"]
        for term in forbidden:
            assert term not in source, \
                f"Domain module imports application concern: '{term}'"
