"""
BankCore — Day 04: Strategy Pattern — Fee Strategies
======================================================
Each fee rule is a self-contained strategy.
FeeCalculator (fee_calculator.py) uses these without knowing their details.

Design decision: strategies are stateless where possible — easier to test
and safe to share across instances. TieredFeeStrategy carries its tier
configuration as immutable data.

PromoFeeStrategy wraps another strategy (Decorator on Strategy) to apply
a discount percentage. This demonstrates that patterns compose naturally
without forcing artificial separation.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class FeeResult:
    """Immutable result of a fee calculation."""
    amount: float           # original transaction amount
    fee: float              # fee charged
    net: float              # amount - fee
    strategy_name: str      # which strategy was used
    account_type: str

    @property
    def fee_pct(self) -> float:
        if self.amount == 0:
            return 0.0
        return (self.fee / self.amount) * 100


# ---------------------------------------------------------------------------
# Abstract strategy
# ---------------------------------------------------------------------------

class FeeStrategy(ABC):
    """
    Contract for all fee calculation strategies.

    Every strategy receives the raw transaction amount and the account type,
    and returns a float representing the fee in EUR.

    Strategies must be pure functions of their inputs — no side effects,
    no state mutation during calculate().
    """

    @abstractmethod
    def calculate(self, amount: float, account_type: str) -> float:
        """Return the fee in EUR for this amount and account type."""

    @abstractmethod
    def description(self) -> str:
        """Human-readable description of this fee strategy."""

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.description()})"


# ---------------------------------------------------------------------------
# Concrete strategies
# ---------------------------------------------------------------------------

class StandardFeeStrategy(FeeStrategy):
    """
    Default bank fee structure:
      - current: 0.1% per transfer
      - pro:     0.05% (preferred rate)
      - savings: no transfer fees
    """

    RATES: dict[str, float] = {
        "current": 0.001,
        "pro":     0.0005,
        "savings": 0.0,
    }
    DEFAULT_RATE: float = 0.001

    def calculate(self, amount: float, account_type: str) -> float:
        rate = self.RATES.get(account_type, self.DEFAULT_RATE)
        return round(amount * rate, 2)

    def description(self) -> str:
        return "Standard: 0.1% current, 0.05% pro, 0% savings"


class ZeroFeeStrategy(FeeStrategy):
    """
    No fees — used for internal transfers, test accounts,
    promotional periods, or regulatory waivers.
    """

    def calculate(self, amount: float, account_type: str) -> float:
        return 0.0

    def description(self) -> str:
        return "Zero fee — all transactions free"


class TieredFeeStrategy(FeeStrategy):
    """
    Tiered pricing: lower percentage for larger amounts.

    Default tiers (configurable at construction):
      - 0     → 500    EUR : 0.20%
      - 500   → 5 000  EUR : 0.10%
      - 5 000 → 50 000 EUR : 0.05%
      - 50 000+        EUR : 0.02%

    Designed for premium accounts or high-volume clients.
    """

    DEFAULT_TIERS: list[tuple[float, float]] = [
        (500.0,    0.0020),
        (5_000.0,  0.0010),
        (50_000.0, 0.0005),
        (float("inf"), 0.0002),
    ]

    def __init__(self, tiers: list[tuple[float, float]] | None = None) -> None:
        # tiers: list of (upper_bound, rate) sorted ascending by upper_bound
        self._tiers = tiers or self.DEFAULT_TIERS

    def calculate(self, amount: float, account_type: str) -> float:
        for upper_bound, rate in self._tiers:
            if amount <= upper_bound:
                return round(amount * rate, 2)
        # Fallback to last tier rate
        return round(amount * self._tiers[-1][1], 2)

    def description(self) -> str:
        return "Tiered: 0.2% < 500, 0.1% < 5k, 0.05% < 50k, 0.02% above"


class InternationalFeeStrategy(FeeStrategy):
    """
    Fee structure for international transfers (SWIFT/SEPA out of zone).
      - Base rate: 2%
      - Minimum flat fee: 5.00 EUR
      - Pro accounts: 1% with 2.00 EUR minimum
    """

    RATES: dict[str, float] = {
        "current": 0.02,
        "savings": 0.02,
        "pro":     0.01,
    }
    MIN_FEES: dict[str, float] = {
        "current": 5.00,
        "savings": 5.00,
        "pro":     2.00,
    }

    def calculate(self, amount: float, account_type: str) -> float:
        rate    = self.RATES.get(account_type, 0.02)
        min_fee = self.MIN_FEES.get(account_type, 5.00)
        return round(max(amount * rate, min_fee), 2)

    def description(self) -> str:
        return "International: 2% (min 5€), Pro: 1% (min 2€)"


class PromoFeeStrategy(FeeStrategy):
    """
    Wraps another strategy and applies a discount percentage.

    This is a Strategy that decorates another Strategy — patterns compose.
    Example: 50% discount on StandardFeeStrategy during a promotional period.

    Usage:
        base  = StandardFeeStrategy()
        promo = PromoFeeStrategy(base, discount=0.5)  # 50% off
        fee   = promo.calculate(1000, "current")      # 0.50 instead of 1.00
    """

    def __init__(self, wrapped: FeeStrategy, discount: float) -> None:
        if not 0.0 <= discount <= 1.0:
            raise ValueError("Discount must be between 0.0 and 1.0.")
        self._wrapped  = wrapped
        self._discount = discount

    def calculate(self, amount: float, account_type: str) -> float:
        base_fee = self._wrapped.calculate(amount, account_type)
        return round(base_fee * (1 - self._discount), 2)

    def description(self) -> str:
        pct = int(self._discount * 100)
        return f"Promo {pct}% off — wraps: {self._wrapped.description()}"
