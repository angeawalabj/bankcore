"""
BankCore — Day 10: Dependency Injection Container
===================================================
The Container is the single place where all dependencies are wired together.

Before Day 10: each class created its own dependencies internally.
After  Day 10: the Container creates everything once and injects it.

This is the "Composition Root" pattern — all wiring happens at the
application boundary, not inside business logic classes.

Design decision: a simple manual DI container rather than a framework
(like dependency_injector or injector). Reasons:
  1. No new dependency added — stdlib only
  2. Explicit and readable — you can trace any dependency
  3. Educational: understanding DI doesn't require a framework

The Container is NOT a Singleton itself — you can create multiple
containers with different configurations for testing.

Usage:
    # Production
    container = BankCoreContainer()
    pipeline  = container.transaction_pipeline()
    result    = pipeline.transfer(alice, bob, 500.0)

    # Testing — inject mocks
    container = BankCoreContainer(
        config=test_config,
        alert_system=mock_alerts,
    )
    service = container.transaction_service()
"""

from __future__ import annotations
from typing import TYPE_CHECKING

from bankcore.config_manager import ConfigManager
from bankcore.alert_system import AlertSystem, AuditLogger, FraudDetector
from bankcore.alert_system import NotificationService, BalanceMonitor
from bankcore.event_builder import EventBuilder
from bankcore.fee_calculator import FeeCalculator
from bankcore.fee_strategy import StandardFeeStrategy
from bankcore.fee_strategy_registry import FeeStrategyRegistry
from bankcore.transaction_service import TransactionService
from bankcore.transaction_decorators import build_pipeline
from bankcore.transaction_processor import TransactionProcessor

if TYPE_CHECKING:
    from bankcore.fee_strategy import FeeStrategy


class BankCoreContainer:
    """
    Assembles and wires all BankCore dependencies.

    Each dependency is created lazily (on first access) and cached.
    This avoids unnecessary instantiation while ensuring single instances
    within one container's lifetime.

    For tests: create a fresh container per test with mock dependencies.
    For production: create one container at startup.
    """

    def __init__(
        self,
        config: ConfigManager | None = None,
        alert_system: AlertSystem | None = None,
        builder: EventBuilder | None = None,
    ) -> None:
        # Accept overrides for testing; fall back to production Singletons
        self._config       = config       or ConfigManager.get_instance()
        self._alert_system = alert_system or AlertSystem.get_instance()
        self._builder      = builder      or EventBuilder()

        # Lazy cache for services
        self._transaction_service: TransactionService | None = None
        self._fee_calculator: FeeCalculator | None = None

    # ------------------------------------------------------------------
    # Core services
    # ------------------------------------------------------------------

    def transaction_service(self) -> TransactionService:
        """
        Return the core TransactionService with all dependencies injected.
        Cached — same instance returned on repeated calls.
        """
        if self._transaction_service is None:
            self._transaction_service = TransactionService(
                config=self._config,
                alert_system=self._alert_system,
                event_builder=self._builder,
            )
        return self._transaction_service

    def fee_calculator(self, strategy_name: str = "standard") -> FeeCalculator:
        """
        Return a FeeCalculator with the named strategy.
        Uses FeeStrategyRegistry (Day 07 — OCP) to resolve the strategy.
        """
        strategy = FeeStrategyRegistry.get(strategy_name)
        return FeeCalculator(strategy)

    def transaction_pipeline(
        self,
        *,
        fee_strategy: str = "standard",
        validate: bool = True,
        log: bool = True,
        rate_limit: bool = True,
        apply_fees: bool = True,
        max_per_window: int | None = None,
    ) -> TransactionProcessor:
        """
        Assemble and return the full transaction pipeline.

        Wires: TransactionService → FeeDecorator → ValidationDecorator
               → LoggingDecorator → RateLimitDecorator

        All decorator dependencies are resolved here — not inside the decorators.
        """
        service    = self.transaction_service()
        calculator = self.fee_calculator(fee_strategy) if apply_fees else None

        return build_pipeline(
            service,
            validate=validate,
            log=log,
            rate_limit=rate_limit,
            apply_fees=apply_fees,
            fee_calculator=calculator,
            max_per_window=max_per_window,
        )

    # ------------------------------------------------------------------
    # Observer wiring
    # ------------------------------------------------------------------

    def wire_default_observers(self) -> None:
        """
        Register the standard set of AlertSystem observers.

        In production, call this once at startup.
        In tests, wire only the observers you need — or none.
        """
        alerts = self._alert_system
        alerts.subscribe_all(FraudDetector())
        alerts.subscribe_all(NotificationService())
        alerts.subscribe_all(BalanceMonitor())
        alerts.subscribe_all(AuditLogger())

    # ------------------------------------------------------------------
    # Accessors for shared infrastructure
    # ------------------------------------------------------------------

    @property
    def config(self) -> ConfigManager:
        return self._config

    @property
    def alert_system(self) -> AlertSystem:
        return self._alert_system

    def __repr__(self) -> str:
        return (
            f"BankCoreContainer("
            f"env={self._config.get('environment', 'unknown')}, "
            f"cached_services={sum(1 for s in [self._transaction_service] if s)})"
        )



# ---------------------------------------------------------------------------
# BankContainer — Day 10 DIP (thin wrapper for clean DI testing)
# ---------------------------------------------------------------------------

class BankContainer:
    """
    Dependency Injection Container — Day 10 (DIP).
    Clean constructor injection: config, alert_system are abstractions.
    Uses BankCoreContainer internally for service wiring.
    """

    def __init__(self, config=None, alert_system=None) -> None:
        from bankcore.config_manager import ConfigManager
        from bankcore.alert_system import AlertSystem
        self._config       = config       or ConfigManager.get_instance()
        self._alert_system = alert_system or AlertSystem.get_instance()
        self._core         = BankCoreContainer(
            config=self._config,
            alert_system=self._alert_system,
        )

    @property
    def config(self):
        return self._config

    @property
    def alert_system(self):
        return self._alert_system

    @property
    def transaction_service(self):
        return self._core.transaction_service()

    def build_pipeline(self, validate=True, log=True, rate_limit=True,
                       apply_fees=True, max_per_window=None):
        from bankcore.transaction_decorators import build_pipeline
        from bankcore.fee_calculator import FeeCalculator
        from bankcore.fee_strategy import ZeroFeeStrategy
        svc  = self._core.transaction_service()
        calc = FeeCalculator(ZeroFeeStrategy()) if not apply_fees else self._core.fee_calculator()
        return build_pipeline(
            svc,
            validate=validate,
            log=log,
            rate_limit=rate_limit,
            apply_fees=apply_fees,
            fee_calculator=calc,
            max_per_window=max_per_window,
        )

    def register_standard_observers(self):
        from bankcore.alert_system import (
            FraudDetector, NotificationService, BalanceMonitor, AuditLogger,
        )
        if hasattr(self._alert_system, "subscribe_all"):
            for obs in [FraudDetector(), NotificationService(),
                        BalanceMonitor(), AuditLogger()]:
                self._alert_system.subscribe_all(obs)

    @classmethod
    def build(cls, config=None, alert_system=None, **kwargs) -> "BankContainer":
        return cls(config=config, alert_system=alert_system)

    @classmethod
    def build_for_testing(cls) -> "BankContainer":
        from bankcore.protocols import FakeConfig, SpyAlertSystem
        return cls(config=FakeConfig(), alert_system=SpyAlertSystem())

    def __repr__(self):
        return (f"BankContainer("
                f"config={self._config.__class__.__name__}, "
                f"alerts={self._alert_system.__class__.__name__})")
