"""
BankCore — Day 07: FeeStrategyRegistry
========================================
Formalizes the extension point for fee strategies.

Before Day 07: FeeCalculator.compare_strategies() hardcoded the list
of known strategies. Adding a new strategy = modifying that method.

After Day 07: strategies register themselves. FeeCalculator discovers
them from the registry — zero modification when a new strategy is added.

OCP proof:
  - Open  : register() accepts any FeeStrategy subclass
  - Closed : FeeCalculator, TransactionService, all decorators unchanged

Usage — adding a new strategy without modifying existing code:
    from bankcore.fee_strategy import FeeStrategy
    from bankcore.fee_strategy_registry import FeeStrategyRegistry

    class CryptoFeeStrategy(FeeStrategy):
        def calculate(self, amount, account_type): return 0.005 * amount
        def description(self): return "Crypto: 0.5% flat"

    FeeStrategyRegistry.register("crypto", CryptoFeeStrategy)
    # FeeCalculator, compare_strategies: inchangés
"""

from __future__ import annotations

import threading
from typing import Type

from bankcore.fee_strategy import (
    FeeStrategy,
    StandardFeeStrategy,
    ZeroFeeStrategy,
    TieredFeeStrategy,
    InternationalFeeStrategy,
)
from bankcore.fee_calculator import FeeCalculator


class FeeStrategyRegistry:
    """
    Registry of all fee strategies known to BankCore.

    Strategies are stored as classes (not instances) so each call to
    create_calculator() produces a fresh, independent FeeCalculator.

    Thread-safe: registration uses a lock; reads are safe post-startup.
    """

    _lock: threading.Lock = threading.Lock()
    _strategies: dict[str, Type[FeeStrategy]] = {}

    @classmethod
    def register(cls, name: str, strategy_class: Type[FeeStrategy]) -> None:
        """
        Register a new fee strategy by name.

        Args:
            name           : unique identifier (e.g. "crypto", "premium")
            strategy_class : a FeeStrategy subclass (not an instance)
        """
        if not name or not name.strip():
            raise ValueError("Strategy name cannot be empty.")
        if not (isinstance(strategy_class, type)
                and issubclass(strategy_class, FeeStrategy)):
            raise TypeError(f"{strategy_class} must be a FeeStrategy subclass.")

        with cls._lock:
            cls._strategies[name] = strategy_class

    @classmethod
    def get(cls, name: str) -> FeeStrategy:
        """
        Return a new instance of the named strategy.
        Raises ValueError if not registered.
        """
        cls_ = cls._strategies.get(name)
        if cls_ is None:
            available = ", ".join(sorted(cls._strategies.keys()))
            raise ValueError(
                f"Unknown fee strategy: '{name}'. Available: {available}"
            )
        return cls_()

    @classmethod
    def create_calculator(cls, name: str) -> FeeCalculator:
        """
        Return a FeeCalculator pre-configured with the named strategy.
        Convenience method — avoids two-step instantiation in callers.
        """
        return FeeCalculator(cls.get(name))

    @classmethod
    def available(cls) -> list[str]:
        """Return all registered strategy names, sorted."""
        return sorted(cls._strategies.keys())

    @classmethod
    def is_registered(cls, name: str) -> bool:
        return name in cls._strategies

    @classmethod
    def all_instances(cls) -> list[FeeStrategy]:
        """
        Return one instance of each registered strategy.
        Used by FeeCalculator.compare_strategies() — no hardcoded list needed.
        """
        return [cls_() for cls_ in cls._strategies.values()]

    @classmethod
    def _reset(cls) -> None:
        """For testing only."""
        with cls._lock:
            cls._strategies.clear()

    @classmethod
    def _register_defaults(cls) -> None:
        """Register the four built-in strategies."""
        cls.register("standard",      StandardFeeStrategy)
        cls.register("zero",          ZeroFeeStrategy)
        cls.register("tiered",        TieredFeeStrategy)
        cls.register("international", InternationalFeeStrategy)


# Initialize on import
FeeStrategyRegistry._register_defaults()
