"""
Tests — Day 15: Hexagonal Architecture
========================================
Test strategy:
  1. TestDriver — fluent integration testing API
  2. BankAPIHandler — REST-style adapter (status codes, request/response)
  3. InterestScheduler — scheduled job adapter (report, dry_run, pagination)
  4. Hexagonal isolation — adapters contain no business logic
  5. Same core, multiple drivers — identical results regardless of adapter
  6. Full integration scenarios through each adapter
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
from bankcore.application.use_cases import BankApplicationService
from bankcore.infrastructure.persistence.in_memory_repository import (
    InMemoryAccountRepository,
)
from bankcore.presentation.test_driver import TestDriver
from bankcore.presentation.scheduler import InterestScheduler, SchedulerReport
from bankcore.presentation.api_handler import BankAPIHandler, HTTPResponse


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
def driver():
    return TestDriver.create()


@pytest.fixture
def app_and_repo():
    container = BankContainer.build_for_testing()
    repo      = InMemoryAccountRepository()
    app       = BankApplicationService(container, registry=repo)
    return app, repo


@pytest.fixture
def api(app_and_repo):
    app, _ = app_and_repo
    return BankAPIHandler(app)


# ---------------------------------------------------------------------------
# TestDriver — fluent integration testing
# ---------------------------------------------------------------------------

class TestTestDriver:

    def test_create_account(self, driver):
        result = driver.create_account("Alice", "current", 1_000.0)
        assert result.success is True

    def test_balance_after_creation(self, driver):
        driver.create_account("Alice", "current", 1_000.0)
        assert driver.balance("Alice") == 1_000.0

    def test_deposit(self, driver):
        driver.create_account("Alice", "current", 500.0)
        driver.deposit("Alice", 300.0)
        assert driver.balance("Alice") == 800.0

    def test_withdraw(self, driver):
        driver.create_account("Alice", "current", 1_000.0)
        driver.withdraw("Alice", 200.0)
        assert driver.balance("Alice") == 800.0

    def test_transfer(self, driver):
        driver.create_account("Alice", "current", 1_000.0)
        driver.create_account("Bob",   "savings",   500.0)
        driver.transfer("Alice", "Bob", 300.0)
        assert driver.balance("Alice") == 700.0
        assert driver.balance("Bob")   == 800.0

    def test_apply_interest(self, driver):
        driver.create_account("Bob", "savings", 1_000.0)
        driver.apply_interest("Bob")
        assert driver.balance("Bob") == pytest.approx(1_025.0)

    def test_fluent_assert_balance(self, driver):
        driver.create_account("Alice", "current", 1_000.0)
        driver.deposit("Alice", 500.0)
        driver.assert_balance("Alice", 1_500.0)

    def test_fluent_assert_last_success(self, driver):
        driver.create_account("Alice", "current", 1_000.0)
        driver.assert_last_success()

    def test_fluent_assert_last_failure(self, driver):
        driver.create_account("Alice", "current", 100.0)
        driver.withdraw("Alice", 9_999.0)   # should fail
        driver.assert_last_failure()

    def test_fluent_assert_last_failure_with_code(self, driver):
        driver.create_account("Alice", "current", 100.0)
        driver.withdraw("Alice", 9_999.0)
        driver.assert_last_failure("WITHDRAWAL_REJECTED")

    def test_fluent_assert_account_count(self, driver):
        driver.create_account("Alice", "current", 100.0)
        driver.create_account("Bob",   "savings",  200.0)
        driver.assert_account_count(2)

    def test_unknown_name_raises(self, driver):
        with pytest.raises(ValueError, match="No account registered"):
            driver.balance("Ghost")

    def test_chained_fluent_assertions(self, driver):
        driver.create_account("Alice", "current", 2_000.0)
        driver.create_account("Bob",   "savings",   500.0)
        driver.transfer("Alice", "Bob", 500.0)
        (driver
         .assert_last_success()
         .assert_balance("Alice", 1_500.0)
         .assert_balance("Bob",   1_000.0)
         .assert_account_count(2))

    def test_operation_count(self, driver):
        driver.create_account("Alice", "current", 1_000.0)
        driver.deposit("Alice", 100.0)
        driver.withdraw("Alice", 50.0)
        assert driver.operation_count == 3

    def test_account_info(self, driver):
        driver.create_account("Alice", "current", 500.0)
        info = driver.account_info("Alice")
        assert info is not None
        assert info["owner_name"] == "Alice"
        assert info["account_type"] == "current"

    def test_each_driver_is_isolated(self):
        """Two TestDrivers share no state — complete isolation."""
        d1 = TestDriver.create()
        d2 = TestDriver.create()

        d1.create_account("Alice", "current", 1_000.0)
        d2.create_account("Alice", "current", 5_000.0)

        # Different drivers, same name, different balances
        assert d1.balance("Alice") == 1_000.0
        assert d2.balance("Alice") == 5_000.0

    def test_full_banking_scenario(self, driver):
        """Complete scenario through TestDriver."""
        # Setup
        driver.create_account("Alice",  "current", 5_000.0)
        driver.create_account("Bob",    "savings",   500.0)
        driver.create_account("CorpX",  "pro",    20_000.0)

        # Operations
        driver.deposit("Alice", 3_000.0)            # Alice gets salary
        driver.transfer("Alice", "Bob", 1_000.0)    # Alice pays Bob
        driver.transfer("CorpX", "Alice", 2_000.0)  # CorpX pays Alice
        driver.apply_interest("Bob")                 # Bob earns interest

        # Assertions
        driver.assert_balance("Alice", 9_000.0)          # 5000+3000-1000+2000
        driver.assert_balance("Bob",   1_537.5, tolerance=0.1)  # (500+1000)*1.025
        driver.assert_balance("CorpX", 18_000.0)         # 20000-2000


# ---------------------------------------------------------------------------
# BankAPIHandler — REST adapter
# ---------------------------------------------------------------------------

class TestBankAPIHandler:

    def test_create_account_returns_201(self, api):
        response = api.create_account({
            "owner_name": "Alice", "account_type": "current", "initial_deposit": 500.0
        })
        assert response.status_code == 201
        assert response.ok is True
        assert "account_id" in response.body

    def test_get_account_returns_200(self, api):
        r = api.create_account({"owner_name": "Alice", "account_type": "current"})
        account_id = r.body["account_id"]
        response = api.get_account(account_id)
        assert response.status_code == 200
        assert response.body["owner_name"] == "Alice"

    def test_get_unknown_account_returns_404(self, api):
        response = api.get_account("GHOST")
        assert response.status_code == 404
        assert response.body["code"] == "ACCOUNT_NOT_FOUND"

    def test_list_accounts_returns_200(self, api):
        api.create_account({"owner_name": "Alice", "account_type": "current"})
        api.create_account({"owner_name": "Bob",   "account_type": "savings"})
        response = api.list_accounts()
        assert response.status_code == 200
        assert response.body["count"] == 2

    def test_deposit_returns_200(self, api):
        r = api.create_account({"owner_name": "Alice", "account_type": "current"})
        account_id = r.body["account_id"]
        response = api.deposit(account_id, {"amount": 300.0})
        assert response.status_code == 200
        assert response.body["balance_after"] == 300.0

    def test_deposit_invalid_amount_returns_422(self, api):
        r = api.create_account({"owner_name": "Alice", "account_type": "current"})
        account_id = r.body["account_id"]
        response = api.deposit(account_id, {"amount": -100.0})
        assert response.status_code == 422

    def test_withdraw_returns_200(self, api):
        r = api.create_account({
            "owner_name": "Alice", "account_type": "current", "initial_deposit": 500.0
        })
        account_id = r.body["account_id"]
        response = api.withdraw(account_id, {"amount": 200.0})
        assert response.status_code == 200

    def test_withdraw_insufficient_funds_returns_422(self, api):
        r = api.create_account({
            "owner_name": "Alice", "account_type": "current", "initial_deposit": 100.0
        })
        account_id = r.body["account_id"]
        response = api.withdraw(account_id, {"amount": 999.0})
        assert response.status_code == 422
        assert response.body["code"] == "WITHDRAWAL_REJECTED"

    def test_transfer_returns_200(self, api):
        r1 = api.create_account({
            "owner_name": "Alice", "account_type": "current", "initial_deposit": 1_000.0
        })
        r2 = api.create_account({
            "owner_name": "Bob", "account_type": "savings", "initial_deposit": 0.0
        })
        response = api.transfer({
            "from_account_id": r1.body["account_id"],
            "to_account_id":   r2.body["account_id"],
            "amount": 400.0,
        })
        assert response.status_code == 200
        assert response.body["from_balance_after"] == 600.0

    def test_transfer_unknown_account_returns_404(self, api):
        r = api.create_account({
            "owner_name": "Alice", "account_type": "current", "initial_deposit": 500.0
        })
        response = api.transfer({
            "from_account_id": r.body["account_id"],
            "to_account_id":   "GHOST",
            "amount": 100.0,
        })
        assert response.status_code == 404

    def test_create_invalid_type_returns_422(self, api):
        response = api.create_account({
            "owner_name": "Alice", "account_type": "crypto", "initial_deposit": 100.0
        })
        assert response.status_code == 422

    def test_create_missing_owner_returns_422(self, api):
        response = api.create_account({
            "owner_name": "", "account_type": "current"
        })
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# InterestScheduler — scheduled job adapter
# ---------------------------------------------------------------------------

class TestInterestScheduler:

    @pytest.fixture
    def scheduler_setup(self, app_and_repo):
        app, repo = app_and_repo
        return app, repo, InterestScheduler(app, repo)

    def test_run_applies_interest_to_eligible_accounts(self, scheduler_setup):
        app, repo, scheduler = scheduler_setup

        # Create savings accounts
        from bankcore.application.commands import CreateAccountCommand
        r1 = app.create_account(CreateAccountCommand("Bob",   "savings", 1_000.0, "sys"))
        r2 = app.create_account(CreateAccountCommand("Carol", "savings", 2_000.0, "sys"))
        r3 = app.create_account(CreateAccountCommand("Alice", "current", 5_000.0, "sys"))

        report = scheduler.run()

        assert report.accounts_processed == 2   # only savings
        assert report.total_credited == pytest.approx(75.0)   # 25 + 50
        assert len(report.errors) == 0

    def test_dry_run_does_not_apply_interest(self, scheduler_setup):
        app, repo, scheduler = scheduler_setup
        from bankcore.application.commands import CreateAccountCommand
        app.create_account(CreateAccountCommand("Bob", "savings", 1_000.0, "sys"))

        report = scheduler.run(dry_run=True)

        assert report.accounts_processed == 0
        assert report.accounts_skipped == 1
        assert report.total_credited == 0.0

        # Balance unchanged
        from bankcore.application.specifications import TypeSpec
        page = repo.find(TypeSpec("savings"), page_size=10)
        assert page.items[0].balance == 1_000.0

    def test_empty_repo_produces_empty_report(self, scheduler_setup):
        _, _, scheduler = scheduler_setup
        report = scheduler.run()
        assert report.accounts_processed == 0
        assert report.total_credited == 0.0

    def test_preview_returns_eligible_accounts(self, scheduler_setup):
        app, repo, scheduler = scheduler_setup
        from bankcore.application.commands import CreateAccountCommand
        app.create_account(CreateAccountCommand("Bob",   "savings", 1_000.0, "sys"))
        app.create_account(CreateAccountCommand("Alice", "current", 5_000.0, "sys"))

        preview = scheduler.preview()

        assert preview["eligible_count"] == 1
        assert preview["total_to_credit"] == pytest.approx(25.0)
        assert len(preview["accounts"]) == 1
        assert preview["accounts"][0]["owner"] == "Bob"

    def test_report_summary_is_readable(self, scheduler_setup):
        _, _, scheduler = scheduler_setup
        report = scheduler.run()
        summary = report.summary()
        assert "InterestScheduler" in summary
        assert "Processed" in summary
        assert "Credited" in summary

    def test_success_rate_all_processed(self, scheduler_setup):
        app, repo, scheduler = scheduler_setup
        from bankcore.application.commands import CreateAccountCommand
        app.create_account(CreateAccountCommand("Bob", "savings", 1_000.0, "sys"))
        report = scheduler.run()
        assert report.success_rate == 1.0

    def test_duration_is_recorded(self, scheduler_setup):
        _, _, scheduler = scheduler_setup
        report = scheduler.run()
        assert report.duration_ms >= 0


# ---------------------------------------------------------------------------
# Hexagonal isolation — adapters contain no business logic
# ---------------------------------------------------------------------------

class TestHexagonalIsolation:

    def test_test_driver_has_no_business_logic(self):
        """
        TestDriver must not contain domain concepts like fee calculation,
        interest rates, overdraft limits, or validation rules.
        """
        import importlib
        module = importlib.import_module("bankcore.presentation.test_driver")
        source = open(module.__file__).read()

        forbidden = [
            "interest_rate", "overdraft_limit", "min_balance",
            "calculate_fee", "0.025", "monthly_fee",
        ]
        for term in forbidden:
            assert term not in source, \
                f"TestDriver contains business logic: '{term}'"

    def test_api_handler_has_no_business_logic(self):
        """BankAPIHandler must not contain business rules."""
        import importlib
        module = importlib.import_module("bankcore.presentation.api_handler")
        source = open(module.__file__).read()

        forbidden = ["interest_rate", "overdraft_limit", "0.025"]
        for term in forbidden:
            assert term not in source, \
                f"BankAPIHandler contains business logic: '{term}'"

    def test_same_core_multiple_adapters_same_result(self, app_and_repo):
        """
        The core BankApplicationService produces identical results
        regardless of which adapter drives it.
        """
        app, repo = app_and_repo

        # Drive via TestDriver
        driver = TestDriver(app)
        driver.create_account("Alice", "current", 1_000.0)
        driver.deposit("Alice", 500.0)
        balance_via_driver = driver.balance("Alice")

        # Read via API adapter (same underlying app)
        api = BankAPIHandler(app)
        alice_id  = driver.account_id("Alice")
        response  = api.get_account(alice_id)
        balance_via_api = response.body["balance"]

        assert balance_via_driver == balance_via_api == 1_500.0

    def test_scheduler_uses_same_core_as_api(self, app_and_repo):
        """
        InterestScheduler and BankAPIHandler drive the same Application core.
        Changes made via API are visible to the scheduler.
        """
        app, repo = app_and_repo

        # Create savings account via API
        api = BankAPIHandler(app)
        r   = api.create_account({
            "owner_name": "Bob", "account_type": "savings", "initial_deposit": 2_000.0
        })
        account_id = r.body["account_id"]

        # Apply interest via scheduler
        scheduler = InterestScheduler(app, repo)
        report    = scheduler.run()

        # Verify via API
        info = api.get_account(account_id)
        assert info.body["balance"] == pytest.approx(2_050.0)
        assert report.accounts_processed == 1
        assert report.total_credited == pytest.approx(50.0)
