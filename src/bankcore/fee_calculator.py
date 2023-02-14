"""
BankCore — Day 04: FeeCalculator (Strategy Context)
=====================================================
FeeCalculator applies a FeeStrategy to BankCore transactions.

It is the "context" in Strategy pattern terminology:
  - It holds a reference to a FeeStrategy
  - It calls the strategy's calculate() method
  - It publishes a fee.applied event to AlertSystem (Day 03)
  - It knows nothing about HOW fees are calculated

Swapping the fee structure = one call to set_strategy().
No other code changes.
"""

from bankcore.config_manager import ConfigManager
from bankcore.events import BankEvent, EventType
from bankcore.fee_strategy import (
    FeeResult, FeeStrategy, StandardFeeStrategy,
    ZeroFeeStrategy, TieredFeeStrategy, InternationalFeeStrategy,
)


class FeeCalculator:
    """
    Applies a configurable FeeStrategy to BankCore transactions.

    Usage:
        calculator = FeeCalculator()                      # default: Standard
        calculator.set_strategy(TieredFeeStrategy())      # switch at runtime

        result = calculator.apply_fee(account, 1000.0, "transfer")
        print(result.fee)    # 1.00 EUR (Standard, current account)
        print(result.net)    # 999.00 EUR
    """

    def __init__(self, strategy: FeeStrategy | None = None) -> None:
        self._strategy: FeeStrategy = strategy or StandardFeeStrategy()
        self._config   = ConfigManager.get_instance()

    @property
    def strategy(self) -> FeeStrategy:
        return self._strategy

    def set_strategy(self, strategy: FeeStrategy) -> None:
        """
        Replace the active fee strategy at runtime.
        All subsequent fee calculations use the new strategy.
        """
        self._strategy = strategy

    def apply_fee(
        self,
        account,               # Account instance (Day 02)
        amount: float,
        operation: str = "transfer",
    ) -> FeeResult:
        """
        Calculate and return the fee for a transaction.

        The fee is NOT automatically debited here — that's TransactionService's
        responsibility. FeeCalculator only computes; it doesn't execute.

        Publishes a fee.applied event to AlertSystem for analytics.
        """
        from bankcore.alert_system import AlertSystem

        fee = self._strategy.calculate(amount, account.account_type)
        result = FeeResult(
            amount=amount,
            fee=fee,
            net=amount - fee,
            strategy_name=self._strategy.__class__.__name__,
            account_type=account.account_type,
        )

        # Notify analytics / audit (Day 03 Observer)
        AlertSystem.get_instance().publish(BankEvent(
            event_type=EventType.FEE_APPLIED,
            account_id=account.account_id,
            amount=fee,
            metadata={
                "operation": operation,
                "original_amount": amount,
                "strategy": self._strategy.__class__.__name__,
                "account_type": account.account_type,
            },
        ))

        return result

    def estimate(self, amount: float, account_type: str) -> float:
        """
        Estimate fee without touching any account or publishing events.
        Used by the UI to show fees before confirming a transaction.
        """
        return self._strategy.calculate(amount, account_type)

    def compare_strategies(
        self,
        amount: float,
        account_type: str,
        strategies: list[FeeStrategy] | None = None,
    ) -> list[dict]:
        """
        Compare multiple strategies for a given amount and account type.
        Day 07 (OCP): discovers strategies from FeeStrategyRegistry —
        no hardcoded list. New strategies appear automatically after registration.
        """
        from bankcore.fee_strategy_registry import FeeStrategyRegistry
        targets = strategies or FeeStrategyRegistry.all_instances()
        return [
            {
                "strategy":    s.__class__.__name__,
                "description": s.description(),
                "fee":         s.calculate(amount, account_type),
                "net":         amount - s.calculate(amount, account_type),
            }
            for s in targets
        ]


# ---------------------------------------------------------------------------
# Quick demo
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    from bankcore.account_factory import AccountFactory
    from bankcore.fee_strategy import PromoFeeStrategy

    print("=== BankCore — Day 04: FeeCalculator Demo ===\n")

    alice = AccountFactory.create("current", "Alice Martin", 10_000.0)
    bob   = AccountFactory.create("pro",     "Acme Corp",    50_000.0)

    calculator = FeeCalculator()

    print("--- Standard Strategy ---")
    for account, name in [(alice, "Alice (current)"), (bob, "Bob (pro)")]:
        result = calculator.apply_fee(account, 1_000.0)
        print(f"  {name:20} fee={result.fee:.4f} EUR  ({result.fee_pct:.3f}%)")

    print("\n--- Switch to Tiered Strategy ---")
    calculator.set_strategy(TieredFeeStrategy())
    for amount in [200, 1_000, 10_000, 60_000]:
        fee = calculator.estimate(amount, "current")
        pct = (fee / amount * 100) if amount else 0
        print(f"  {amount:>8,.0f} EUR  →  fee={fee:.2f} EUR  ({pct:.3f}%)")

    print("\n--- Promo: 50% off Standard ---")
    calculator.set_strategy(PromoFeeStrategy(StandardFeeStrategy(), discount=0.5))
    result = calculator.apply_fee(alice, 1_000.0)
    print(f"  Promo fee: {result.fee:.4f} EUR  (normally 1.00 EUR)")

    print("\n--- Strategy comparison for 5 000 EUR ---")
    for row in calculator.compare_strategies(5_000.0, "current"):
        print(f"  {row['strategy']:28} fee={row['fee']:7.2f} EUR")
