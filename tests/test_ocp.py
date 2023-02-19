"""
Tests — Day 07: Open/Closed Principle
========================================
Core assertion: new account types and fee strategies can be added
WITHOUT modifying any existing file.

These tests prove OCP by:
  1. Creating a new account type (YouthAccount) via registration only
  2. Creating a new fee strategy (PremiumFeeStrategy) via registration only
  3. Verifying the whole system (AccountFactory, FeeCalculator,
     AccountConfigResolver) automatically supports the new additions
  4. Verifying existing behavior is completely unaffected
"""

import sys
import pytest

sys.path.insert(0, "src")

from bankcore.config_manager import ConfigManager
from bankcore.account_factory import AccountFactory
from bankcore.alert_system import AlertSystem
from bankcore.account import CurrentAccount, SavingsAccount
from bankcore.account_type_registry import AccountTypeRegistry, ConfigProfile
from bankcore.fee_strategy_registry import FeeStrategyRegistry
from bankcore.fee_strategy import FeeStrategy, StandardFeeStrategy
from bankcore.fee_calculator import FeeCalculator
from bankcore.account_config import AccountConfigResolver


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_state():
    ConfigManager._reset()
    AlertSystem._reset()
    AccountTypeRegistry._reset()
    AccountTypeRegistry._register_defaults()
    FeeStrategyRegistry._reset()
    FeeStrategyRegistry._register_defaults()
    AccountFactory._reset_registry()
    yield
    ConfigManager._reset()
    AlertSystem._reset()
    AccountTypeRegistry._reset()
    AccountTypeRegistry._register_defaults()
    FeeStrategyRegistry._reset()
    FeeStrategyRegistry._register_defaults()
    AccountFactory._reset_registry()


# ---------------------------------------------------------------------------
# New account type WITHOUT modifying any existing file
# ---------------------------------------------------------------------------

class YouthAccount(CurrentAccount):
    """
    New account type added by registration — zero existing files modified.
    Demonstrates OCP: the system is open to extension via the registry.
    """
    DAILY_LIMIT = 500.0
    MONTHLY_FEE = 0.0

    def __init__(self, owner_name: str, initial_deposit: float = 0.0) -> None:
        super().__init__(owner_name, initial_deposit, daily_limit=self.DAILY_LIMIT)
        self.monthly_fee = self.MONTHLY_FEE

    @property
    def account_type(self) -> str:
        return "youth"


YOUTH_PROFILE = ConfigProfile(
    account_type="youth",
    daily_limit=500.0,
    monthly_fee=0.0,
    min_balance=0.0,
    interest_rate=0.0,
)


class TestAccountTypeRegistryOCP:

    def test_register_new_type_without_modifying_existing_code(self):
        """
        OCP proof: YouthAccount is registered without touching
        AccountFactory, AccountConfigResolver, or any service.
        """
        AccountTypeRegistry.register(
            name="youth",
            creator=lambda owner, deposit: YouthAccount(owner, deposit),
            profile=YOUTH_PROFILE,
        )
        assert AccountTypeRegistry.is_registered("youth")

    def test_factory_creates_new_type_after_registration(self):
        AccountTypeRegistry.register(
            "youth",
            lambda owner, deposit: YouthAccount(owner, deposit),
            YOUTH_PROFILE,
        )
        AccountFactory.register(
            "youth",
            lambda owner, deposit: YouthAccount(owner, deposit),
        )
        account = AccountFactory.create("youth", "Charlie", 200.0)
        assert account.account_type == "youth"
        assert account.balance == 200.0

    def test_new_type_enforces_its_own_rules(self):
        AccountTypeRegistry.register(
            "youth",
            lambda owner, deposit: YouthAccount(owner, deposit),
            YOUTH_PROFILE,
        )
        AccountFactory.register(
            "youth",
            lambda owner, deposit: YouthAccount(owner, deposit),
        )
        account = AccountFactory.create("youth", "Charlie", 1_000.0)
        assert account.withdraw(600.0) is False   # exceeds 500 EUR daily limit
        assert account.withdraw(500.0) is True

    def test_config_resolver_sees_new_type_automatically(self):
        AccountTypeRegistry.register(
            "youth",
            lambda owner, deposit: YouthAccount(owner, deposit),
            YOUTH_PROFILE,
        )
        resolver = AccountConfigResolver()
        assert "youth" in resolver.supported_types()

    def test_config_resolver_returns_correct_profile_for_new_type(self):
        AccountTypeRegistry.register(
            "youth",
            lambda owner, deposit: YouthAccount(owner, deposit),
            YOUTH_PROFILE,
        )
        resolver = AccountConfigResolver()
        assert resolver.resolve_daily_limit("youth") == 500.0
        assert resolver.resolve_monthly_fee("youth") == 0.0

    def test_available_types_includes_new_type(self):
        AccountTypeRegistry.register(
            "youth",
            lambda owner, deposit: YouthAccount(owner, deposit),
            YOUTH_PROFILE,
        )
        assert "youth" in AccountTypeRegistry.available()

    def test_existing_types_unaffected_after_new_registration(self):
        AccountTypeRegistry.register(
            "youth",
            lambda owner, deposit: YouthAccount(owner, deposit),
            YOUTH_PROFILE,
        )
        # Existing types still work exactly as before
        current = AccountFactory.create("current", "Alice", 1_000.0)
        savings = AccountFactory.create("savings", "Bob",   2_000.0)
        assert current.account_type == "current"
        assert savings.account_type == "savings"
        assert current.withdraw(500.0) is True
        assert savings.withdraw(1_950.0) is True   # leaves 50 = min → OK
        assert savings.withdraw(10.0) is False      # would go below 50 min


# ---------------------------------------------------------------------------
# New fee strategy WITHOUT modifying FeeCalculator
# ---------------------------------------------------------------------------

class PremiumFeeStrategy(FeeStrategy):
    """
    New fee strategy registered without modifying FeeCalculator.
    Flat 0.05% rate for all account types — premium service pricing.
    """
    RATE = 0.0005

    def calculate(self, amount: float, account_type: str) -> float:
        return round(amount * self.RATE, 2)

    def description(self) -> str:
        return "Premium: 0.05% flat all account types"


class TestFeeStrategyRegistryOCP:

    def test_register_new_strategy_without_modifying_calculator(self):
        FeeStrategyRegistry.register("premium", PremiumFeeStrategy)
        assert FeeStrategyRegistry.is_registered("premium")

    def test_get_returns_instance_of_registered_strategy(self):
        FeeStrategyRegistry.register("premium", PremiumFeeStrategy)
        strategy = FeeStrategyRegistry.get("premium")
        assert isinstance(strategy, PremiumFeeStrategy)

    def test_create_calculator_uses_registered_strategy(self):
        FeeStrategyRegistry.register("premium", PremiumFeeStrategy)
        calc = FeeStrategyRegistry.create_calculator("premium")
        account = AccountFactory.create("current", "Alice", 5_000.0)
        result = calc.apply_fee(account, 1_000.0)
        assert result.fee == 0.50   # 0.05% of 1000

    def test_compare_strategies_includes_new_strategy(self):
        FeeStrategyRegistry.register("premium", PremiumFeeStrategy)
        calc    = FeeCalculator()
        results = calc.compare_strategies(1_000.0, "current")
        names   = [r["strategy"] for r in results]
        assert "PremiumFeeStrategy" in names

    def test_existing_strategies_unaffected(self):
        FeeStrategyRegistry.register("premium", PremiumFeeStrategy)
        standard = FeeStrategyRegistry.get("standard")
        assert isinstance(standard, StandardFeeStrategy)
        assert standard.calculate(1_000.0, "current") == 1.0

    def test_get_unknown_strategy_raises(self):
        with pytest.raises(ValueError, match="Unknown fee strategy"):
            FeeStrategyRegistry.get("nonexistent")

    def test_register_non_strategy_class_raises(self):
        with pytest.raises(TypeError):
            FeeStrategyRegistry.register("bad", str)

    def test_available_includes_new_strategy(self):
        FeeStrategyRegistry.register("premium", PremiumFeeStrategy)
        assert "premium" in FeeStrategyRegistry.available()
        assert "standard" in FeeStrategyRegistry.available()
        assert "tiered" in FeeStrategyRegistry.available()


# ---------------------------------------------------------------------------
# AccountTypeRegistry internals
# ---------------------------------------------------------------------------

class TestAccountTypeRegistryInternals:

    def test_register_empty_name_raises(self):
        with pytest.raises(ValueError):
            AccountTypeRegistry.register("", lambda o, d: None)

    def test_default_types_registered_on_import(self):
        for t in ["current", "savings", "pro"]:
            assert AccountTypeRegistry.is_registered(t)

    def test_get_profile_current(self):
        profile = AccountTypeRegistry.get_profile("current")
        assert profile.daily_limit == 10_000.0
        assert profile.monthly_fee == 2.0

    def test_get_profile_savings(self):
        profile = AccountTypeRegistry.get_profile("savings")
        assert profile.min_balance == 50.0
        assert profile.interest_rate == 0.025

    def test_get_profile_pro(self):
        profile = AccountTypeRegistry.get_profile("pro")
        assert profile.overdraft == -5_000.0
        assert profile.daily_limit == 50_000.0

    def test_get_profile_unknown_raises(self):
        with pytest.raises(ValueError):
            AccountTypeRegistry.get_profile("nonexistent")

    def test_reset_clears_all_types(self):
        AccountTypeRegistry._reset()
        assert AccountTypeRegistry.available() == []

    def test_register_defaults_restores_three_types(self):
        AccountTypeRegistry._reset()
        AccountTypeRegistry._register_defaults()
        assert len(AccountTypeRegistry.available()) == 3


# ---------------------------------------------------------------------------
# OCP proof: the invariant stated in the ADR
# ---------------------------------------------------------------------------

class TestOCPInvariant:

    def test_adding_youth_account_touches_zero_existing_files(self):
        """
        Formal proof of the OCP invariant.
        YouthAccount added by calling register() only — no existing file modified.
        """
        class YouthAccount(CurrentAccount):
            @property
            def account_type(self): return "youth"

        youth_profile = ConfigProfile("youth", daily_limit=500.0, monthly_fee=0.0)
        youth_creator = lambda o, d: YouthAccount(o, d, daily_limit=500.0)

        # Single registration point — OCP: extend without modifying
        AccountTypeRegistry.register("youth", youth_creator, youth_profile)

        # Step 3: Verify the whole system supports it
        account  = AccountTypeRegistry.create("youth", "Charlie", 300.0)
        resolver = AccountConfigResolver()
        calc     = FeeCalculator(StandardFeeStrategy())

        assert account.account_type == "youth"
        assert "youth" in AccountTypeRegistry.available()
        assert "youth" in resolver.supported_types()
        assert resolver.resolve_daily_limit("youth") == 500.0
        result = calc.apply_fee(account, 100.0)
        assert result is not None

    def test_adding_premium_strategy_touches_zero_existing_files(self):
        """
        Formal proof for fee strategies.
        PremiumFeeStrategy added by registration — FeeCalculator unchanged.
        """
        FeeStrategyRegistry.register("premium", PremiumFeeStrategy)

        calc    = FeeCalculator()
        results = calc.compare_strategies(1_000.0, "current")
        premium = next(r for r in results if r["strategy"] == "PremiumFeeStrategy")

        assert premium["fee"] == 0.50
        assert premium["net"] == 999.50
