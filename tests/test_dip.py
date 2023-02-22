"""
Tests — Day 10: Dependency Inversion Principle
================================================
Core assertion: high-level modules depend on abstractions (protocols),
not on concrete implementations. Dependencies are injected, not created.

Test strategy:
  1. Protocol satisfaction — ConfigManager and AlertSystem satisfy protocols
  2. FakeConfig / SpyAlertSystem — test doubles work as drop-in replacements
  3. TransactionService with injected fakes — no global state touched
  4. AccountConfigResolver with injected config
  5. BankContainer — wires everything correctly
  6. Isolation proof — tests run with zero Singleton access
  7. Backward compatibility — zero-arg constructors still work
"""

import sys
import pytest

sys.path.insert(0, "src")

from bankcore.config_manager import ConfigManager
from bankcore.account_factory import AccountFactory
from bankcore.alert_system import AlertSystem
from bankcore.account_type_registry import AccountTypeRegistry
from bankcore.transaction_service import TransactionService
from bankcore.account_config import AccountConfigResolver
from bankcore.protocols import (
    ConfigProtocol, AlertProtocol,
    FakeConfig, SpyAlertSystem,
)
from bankcore.container import BankContainer
from bankcore.events import EventType
from bankcore.fee_calculator import FeeCalculator
from bankcore.fee_strategy import ZeroFeeStrategy


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
# Protocol satisfaction — real implementations satisfy protocols
# ---------------------------------------------------------------------------

class TestProtocolSatisfaction:

    def test_config_manager_satisfies_config_protocol(self):
        config = ConfigManager.get_instance()
        assert isinstance(config, ConfigProtocol)

    def test_alert_system_satisfies_alert_protocol(self):
        alerts = AlertSystem.get_instance()
        assert isinstance(alerts, AlertProtocol)

    def test_fake_config_satisfies_config_protocol(self):
        assert isinstance(FakeConfig(), ConfigProtocol)

    def test_spy_alert_system_satisfies_alert_protocol(self):
        assert isinstance(SpyAlertSystem(), AlertProtocol)

    def test_fake_config_get_returns_value(self):
        config = FakeConfig({"database.url": "sqlite://test"})
        assert config.get("database.url") == "sqlite://test"

    def test_fake_config_get_returns_default(self):
        config = FakeConfig()
        assert config.get("nonexistent.key", "fallback") == "fallback"

    def test_fake_config_set_persists(self):
        config = FakeConfig()
        config.set("custom.key", 42)
        assert config.get("custom.key") == 42

    def test_fake_config_has_sensible_defaults(self):
        config = FakeConfig()
        assert config.get("limits.max_transfer_amount") == 50_000.0
        assert config.get("environment") == "test"

    def test_spy_alert_system_records_published_events(self):
        from bankcore.events import BankEvent, EventType
        spy = SpyAlertSystem()
        event = BankEvent(EventType.TRANSFER, "ACC-001", 500.0)
        spy.publish(event)
        assert spy.event_count() == 1
        assert spy.was_published(EventType.TRANSFER)

    def test_spy_alert_system_events_of_type(self):
        from bankcore.events import BankEvent, EventType
        spy = SpyAlertSystem()
        spy.publish(BankEvent(EventType.TRANSFER, "ACC-001", 100.0))
        spy.publish(BankEvent(EventType.DEPOSIT,  "ACC-001", 200.0))
        spy.publish(BankEvent(EventType.TRANSFER, "ACC-002", 300.0))
        transfers = spy.events_of_type(EventType.TRANSFER)
        assert len(transfers) == 2

    def test_spy_alert_system_clear(self):
        from bankcore.events import BankEvent, EventType
        spy = SpyAlertSystem()
        spy.publish(BankEvent(EventType.TRANSFER, "ACC-001", 100.0))
        spy.clear()
        assert spy.event_count() == 0


# ---------------------------------------------------------------------------
# TransactionService with injected dependencies
# ---------------------------------------------------------------------------

class TestTransactionServiceDIP:

    def test_transaction_service_accepts_injected_config(self):
        config = FakeConfig({"limits.max_transfer_amount": 200.0})
        spy    = SpyAlertSystem()
        service = TransactionService(config=config, alert_system=spy)

        alice = AccountFactory.create("current", "Alice", 1_000.0)
        bob   = AccountFactory.create("savings", "Bob",   500.0)

        # Should be blocked by injected config limit of 200
        result = service.transfer(alice, bob, 300.0)
        assert result["success"] is False
        assert "limit" in result["reason"].lower()

    def test_transaction_service_uses_injected_alert_system(self):
        spy     = SpyAlertSystem()
        service = TransactionService(alert_system=spy)

        alice = AccountFactory.create("current", "Alice", 1_000.0)
        bob   = AccountFactory.create("savings", "Bob",   500.0)

        service.transfer(alice, bob, 300.0)

        # Spy captures the event — no real AlertSystem accessed
        assert spy.was_published(EventType.TRANSFER)

    def test_deposit_publishes_to_injected_alert_system(self):
        spy     = SpyAlertSystem()
        service = TransactionService(alert_system=spy)
        alice   = AccountFactory.create("current", "Alice", 0.0)

        service.deposit(alice, 500.0)
        assert spy.was_published(EventType.DEPOSIT)

    def test_withdrawal_publishes_to_injected_alert_system(self):
        spy     = SpyAlertSystem()
        service = TransactionService(alert_system=spy)
        alice   = AccountFactory.create("current", "Alice", 1_000.0)

        service.withdraw(alice, 200.0)
        assert spy.was_published(EventType.WITHDRAWAL)

    def test_no_global_state_accessed_with_full_injection(self):
        """
        DIP proof: TransactionService works without any Singleton access.
        We reset all Singletons first — the service still functions correctly.
        """
        config  = FakeConfig()
        spy     = SpyAlertSystem()
        service = TransactionService(config=config, alert_system=spy)

        # Reset globals AFTER creating the service
        ConfigManager._reset()
        AlertSystem._reset()

        alice = AccountFactory.create("current", "Alice", 1_000.0)
        bob   = AccountFactory.create("savings", "Bob",   500.0)

        # Should work — service has its own injected dependencies
        result = service.transfer(alice, bob, 200.0)
        assert result["success"] is True
        assert spy.event_count() == 1

    def test_backward_compat_zero_arg_constructor(self):
        """
        Existing tests use TransactionService() — must still work.
        DIP refactoring is backward compatible.
        """
        service = TransactionService()   # falls back to Singletons
        alice   = AccountFactory.create("current", "Alice", 500.0)
        result  = service.deposit(alice, 100.0)
        assert result["success"] is True

    def test_different_config_limits_different_services(self):
        """
        Two services with different injected configs behave differently.
        This was impossible before DIP — both would use the same Singleton.
        """
        strict  = TransactionService(config=FakeConfig({"limits.max_transfer_amount": 100.0}))
        lenient = TransactionService(config=FakeConfig({"limits.max_transfer_amount": 10_000.0}))

        alice1 = AccountFactory.create("current", "Alice1", 5_000.0)
        alice2 = AccountFactory.create("current", "Alice2", 5_000.0)
        bob    = AccountFactory.create("savings", "Bob",    1_000.0)

        result_strict  = strict.transfer(alice1, bob, 500.0)
        result_lenient = lenient.transfer(alice2, bob, 500.0)

        assert result_strict["success"]  is False   # 500 > 100 limit
        assert result_lenient["success"] is True    # 500 < 10_000 limit


# ---------------------------------------------------------------------------
# AccountConfigResolver with injected config
# ---------------------------------------------------------------------------

class TestAccountConfigResolverDIP:

    def test_resolver_accepts_injected_config(self):
        config   = FakeConfig({"limits.max_transfer_amount": 2_000.0})
        resolver = AccountConfigResolver(config=config)
        # For current accounts, daily_limit = min(config_limit, type_default)
        # min(2000, 10000) = 2000
        assert resolver.resolve_daily_limit("current") == 2_000.0

    def test_resolver_without_injection_uses_singleton(self):
        ConfigManager.get_instance().set("limits.max_transfer_amount", 3_000.0)
        resolver = AccountConfigResolver()
        assert resolver.resolve_daily_limit("current") == 3_000.0

    def test_two_resolvers_different_configs(self):
        config_a = FakeConfig({"limits.max_transfer_amount": 1_000.0})
        config_b = FakeConfig({"limits.max_transfer_amount": 5_000.0})

        resolver_a = AccountConfigResolver(config=config_a)
        resolver_b = AccountConfigResolver(config=config_b)

        assert resolver_a.resolve_daily_limit("current") == 1_000.0
        assert resolver_b.resolve_daily_limit("current") == 5_000.0


# ---------------------------------------------------------------------------
# BankContainer
# ---------------------------------------------------------------------------

class TestBankContainer:

    def test_build_returns_container(self):
        container = BankContainer.build()
        assert isinstance(container, BankContainer)

    def test_build_for_testing_uses_fakes(self):
        container = BankContainer.build_for_testing()
        assert isinstance(container.config, FakeConfig)
        assert isinstance(container.alert_system, SpyAlertSystem)

    def test_container_provides_transaction_service(self):
        container = BankContainer.build_for_testing()
        service   = container.transaction_service
        assert isinstance(service, TransactionService)

    def test_container_transaction_service_uses_injected_deps(self):
        container = BankContainer.build_for_testing()
        service   = container.transaction_service
        alice     = AccountFactory.create("current", "Alice", 1_000.0)

        container.transaction_service.deposit(alice, 200.0)

        spy = container.alert_system
        assert isinstance(spy, SpyAlertSystem)
        assert spy.was_published(EventType.DEPOSIT)

    def test_container_builds_pipeline(self):
        from bankcore.transaction_processor import TransactionProcessor
        container = BankContainer.build_for_testing()
        pipeline  = container.build_pipeline(
            validate=True, log=False, rate_limit=False, apply_fees=False
        )
        assert isinstance(pipeline, TransactionProcessor)

    def test_container_pipeline_uses_injected_config(self):
        config    = FakeConfig({"limits.max_transfer_amount": 50.0})
        spy       = SpyAlertSystem()
        container = BankContainer.build(config=config, alert_system=spy)
        pipeline  = container.build_pipeline(apply_fees=False, rate_limit=False)

        alice = AccountFactory.create("current", "Alice", 1_000.0)
        bob   = AccountFactory.create("savings", "Bob",   500.0)

        result = pipeline.transfer(alice, bob, 100.0)
        # 100 > 50 limit → should be rejected
        assert result["success"] is False

    def test_build_with_override_config(self):
        custom    = FakeConfig({"limits.max_transfer_amount": 999.0})
        container = BankContainer.build(config=custom)
        assert container.config.get("limits.max_transfer_amount") == 999.0

    def test_container_repr(self):
        container = BankContainer.build_for_testing()
        r = repr(container)
        assert "FakeConfig" in r
        assert "SpyAlertSystem" in r


# ---------------------------------------------------------------------------
# DIP Isolation proof — full test with zero Singleton usage
# ---------------------------------------------------------------------------

class TestFullIsolation:
    """
    These tests use ONLY injected dependencies.
    No ConfigManager, no AlertSystem Singleton is touched.
    This is the ultimate DIP proof.
    """

    def test_complete_transfer_with_pure_injection(self):
        config  = FakeConfig({"limits.max_transfer_amount": 10_000.0})
        spy     = SpyAlertSystem()
        service = TransactionService(config=config, alert_system=spy)

        alice = AccountFactory.create("current", "Alice", 5_000.0)
        bob   = AccountFactory.create("savings", "Bob",   1_000.0)

        result = service.transfer(alice, bob, 1_000.0)

        assert result["success"] is True
        assert alice.balance == 4_000.0
        assert bob.balance   == 2_000.0
        assert spy.was_published(EventType.TRANSFER)

    def test_config_change_affects_injected_service_only(self):
        """
        Changing FakeConfig does NOT affect the real ConfigManager.
        Injected state is completely isolated from global state.
        """
        fake    = FakeConfig({"limits.max_transfer_amount": 100.0})
        service = TransactionService(config=fake)

        # Change injected config
        fake.set("limits.max_transfer_amount", 500.0)

        # Real ConfigManager unchanged
        real_limit = ConfigManager.get_instance().get("limits.max_transfer_amount")
        assert real_limit == 50_000.0   # default, not 500.0

        # Injected service sees the new value
        alice = AccountFactory.create("current", "Alice", 5_000.0)
        bob   = AccountFactory.create("savings", "Bob",   500.0)
        result = service.transfer(alice, bob, 400.0)
        assert result["success"] is True   # 400 < 500 new limit

    def test_spy_captures_all_events_in_multi_step_flow(self):
        spy     = SpyAlertSystem()
        service = TransactionService(alert_system=spy)

        alice = AccountFactory.create("current", "Alice", 5_000.0)
        bob   = AccountFactory.create("savings", "Bob",   1_000.0)

        service.deposit(alice, 500.0)
        service.withdraw(alice, 200.0)
        service.transfer(alice, bob, 300.0)

        assert spy.event_count() == 3
        assert spy.was_published(EventType.DEPOSIT)
        assert spy.was_published(EventType.WITHDRAWAL)
        assert spy.was_published(EventType.TRANSFER)
