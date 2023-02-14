"""
Tests — Day 04: FeeStrategy & FeeCalculator
============================================
Test strategy:
  1. Each concrete FeeStrategy in isolation
  2. FeeCalculator as a context — strategy swapping
  3. FeeResult immutability and derived properties
  4. PromoFeeStrategy composition
  5. AlertSystem integration — fee.applied event published
  6. Cross-day: ConfigManager + AccountFactory + FeeCalculator
"""

import sys
import pytest

sys.path.insert(0, "src")

from bankcore.config_manager import ConfigManager
from bankcore.account_factory import AccountFactory
from bankcore.alert_system import AlertSystem
from bankcore.fee_strategy import (
    StandardFeeStrategy, ZeroFeeStrategy, TieredFeeStrategy,
    InternationalFeeStrategy, PromoFeeStrategy, FeeResult,
)
from bankcore.fee_calculator import FeeCalculator
from bankcore.events import EventType


@pytest.fixture(autouse=True)
def reset_state():
    ConfigManager._reset()
    AlertSystem._reset()
    AccountFactory._reset_registry()
    yield
    ConfigManager._reset()
    AlertSystem._reset()
    AccountFactory._reset_registry()


# ---------------------------------------------------------------------------
# StandardFeeStrategy
# ---------------------------------------------------------------------------

class TestStandardFeeStrategy:

    def test_current_account_rate(self):
        strategy = StandardFeeStrategy()
        fee = strategy.calculate(1_000.0, "current")
        assert fee == 1.0   # 0.1%

    def test_pro_account_preferred_rate(self):
        strategy = StandardFeeStrategy()
        fee = strategy.calculate(1_000.0, "pro")
        assert fee == 0.5   # 0.05%

    def test_savings_account_zero_fee(self):
        strategy = StandardFeeStrategy()
        fee = strategy.calculate(1_000.0, "savings")
        assert fee == 0.0

    def test_unknown_account_type_uses_default(self):
        strategy = StandardFeeStrategy()
        fee = strategy.calculate(1_000.0, "unknown_type")
        assert fee == 1.0   # falls back to default rate 0.1%

    def test_zero_amount_produces_zero_fee(self):
        strategy = StandardFeeStrategy()
        assert strategy.calculate(0.0, "current") == 0.0

    def test_fee_is_rounded_to_two_decimals(self):
        strategy = StandardFeeStrategy()
        fee = strategy.calculate(333.33, "current")
        assert fee == round(333.33 * 0.001, 2)

    def test_description_is_non_empty(self):
        assert StandardFeeStrategy().description() != ""


# ---------------------------------------------------------------------------
# ZeroFeeStrategy
# ---------------------------------------------------------------------------

class TestZeroFeeStrategy:

    def test_always_returns_zero(self):
        strategy = ZeroFeeStrategy()
        for account_type in ["current", "savings", "pro", "youth"]:
            assert strategy.calculate(1_000.0, account_type) == 0.0

    def test_zero_for_large_amounts(self):
        assert ZeroFeeStrategy().calculate(999_999.0, "pro") == 0.0


# ---------------------------------------------------------------------------
# TieredFeeStrategy
# ---------------------------------------------------------------------------

class TestTieredFeeStrategy:

    def test_first_tier_small_amount(self):
        strategy = TieredFeeStrategy()
        fee = strategy.calculate(200.0, "current")
        assert fee == round(200.0 * 0.002, 2)   # 0.40 EUR

    def test_second_tier_medium_amount(self):
        strategy = TieredFeeStrategy()
        fee = strategy.calculate(1_000.0, "current")
        assert fee == round(1_000.0 * 0.001, 2)  # 1.00 EUR

    def test_third_tier_large_amount(self):
        strategy = TieredFeeStrategy()
        fee = strategy.calculate(10_000.0, "current")
        assert fee == round(10_000.0 * 0.0005, 2)  # 5.00 EUR

    def test_fourth_tier_very_large_amount(self):
        strategy = TieredFeeStrategy()
        fee = strategy.calculate(100_000.0, "current")
        assert fee == round(100_000.0 * 0.0002, 2)  # 20.00 EUR

    def test_boundary_exactly_at_tier_limit(self):
        strategy = TieredFeeStrategy()
        fee = strategy.calculate(500.0, "current")
        assert fee == round(500.0 * 0.002, 2)   # first tier applies at boundary

    def test_custom_tiers(self):
        custom = TieredFeeStrategy(tiers=[
            (100.0, 0.05),          # 5% up to 100
            (float("inf"), 0.01),   # 1% above
        ])
        assert custom.calculate(50.0, "current") == 2.50
        assert custom.calculate(200.0, "current") == 2.00

    def test_tiered_cheaper_than_standard_for_large_amounts(self):
        standard = StandardFeeStrategy()
        tiered   = TieredFeeStrategy()
        amount   = 10_000.0
        assert tiered.calculate(amount, "current") < standard.calculate(amount, "current")


# ---------------------------------------------------------------------------
# InternationalFeeStrategy
# ---------------------------------------------------------------------------

class TestInternationalFeeStrategy:

    def test_minimum_fee_enforced_for_small_amounts(self):
        strategy = InternationalFeeStrategy()
        fee = strategy.calculate(10.0, "current")   # 2% = 0.20, min = 5.00
        assert fee == 5.00

    def test_percentage_applied_for_large_amounts(self):
        strategy = InternationalFeeStrategy()
        fee = strategy.calculate(1_000.0, "current")  # 2% = 20.00 > 5.00
        assert fee == 20.00

    def test_pro_account_lower_rate_and_minimum(self):
        strategy = InternationalFeeStrategy()
        fee_pro     = strategy.calculate(1_000.0, "pro")      # 1% = 10.00
        fee_current = strategy.calculate(1_000.0, "current")  # 2% = 20.00
        assert fee_pro < fee_current

    def test_pro_minimum_fee(self):
        strategy = InternationalFeeStrategy()
        fee = strategy.calculate(5.0, "pro")  # 1% = 0.05, min = 2.00
        assert fee == 2.00


# ---------------------------------------------------------------------------
# PromoFeeStrategy (composition)
# ---------------------------------------------------------------------------

class TestPromoFeeStrategy:

    def test_fifty_percent_discount(self):
        base  = StandardFeeStrategy()
        promo = PromoFeeStrategy(base, discount=0.5)
        base_fee  = base.calculate(1_000.0, "current")   # 1.00
        promo_fee = promo.calculate(1_000.0, "current")  # 0.50
        assert promo_fee == round(base_fee * 0.5, 2)

    def test_hundred_percent_discount_is_zero(self):
        promo = PromoFeeStrategy(StandardFeeStrategy(), discount=1.0)
        assert promo.calculate(1_000.0, "current") == 0.0

    def test_zero_discount_equals_base(self):
        base  = StandardFeeStrategy()
        promo = PromoFeeStrategy(base, discount=0.0)
        assert promo.calculate(1_000.0, "current") == base.calculate(1_000.0, "current")

    def test_invalid_discount_raises(self):
        with pytest.raises(ValueError):
            PromoFeeStrategy(StandardFeeStrategy(), discount=1.5)

    def test_wraps_tiered_strategy(self):
        base  = TieredFeeStrategy()
        promo = PromoFeeStrategy(base, discount=0.25)
        base_fee  = base.calculate(1_000.0, "current")
        promo_fee = promo.calculate(1_000.0, "current")
        assert promo_fee == round(base_fee * 0.75, 2)

    def test_description_mentions_discount(self):
        promo = PromoFeeStrategy(StandardFeeStrategy(), discount=0.3)
        assert "30" in promo.description()


# ---------------------------------------------------------------------------
# FeeResult
# ---------------------------------------------------------------------------

class TestFeeResult:

    def test_net_is_amount_minus_fee(self):
        result = FeeResult(1_000.0, 1.0, 999.0, "StandardFeeStrategy", "current")
        assert result.net == 999.0

    def test_fee_pct_calculation(self):
        result = FeeResult(1_000.0, 1.0, 999.0, "StandardFeeStrategy", "current")
        assert result.fee_pct == pytest.approx(0.1)

    def test_fee_pct_zero_amount(self):
        result = FeeResult(0.0, 0.0, 0.0, "ZeroFeeStrategy", "current")
        assert result.fee_pct == 0.0

    def test_is_immutable(self):
        result = FeeResult(1_000.0, 1.0, 999.0, "StandardFeeStrategy", "current")
        with pytest.raises(Exception):
            result.fee = 99.0


# ---------------------------------------------------------------------------
# FeeCalculator as context
# ---------------------------------------------------------------------------

class TestFeeCalculator:

    def test_default_strategy_is_standard(self):
        calc = FeeCalculator()
        assert isinstance(calc.strategy, StandardFeeStrategy)

    def test_apply_fee_returns_fee_result(self):
        account = AccountFactory.create("current", "Alice", 5_000.0)
        calc    = FeeCalculator()
        result  = calc.apply_fee(account, 1_000.0)
        assert isinstance(result, FeeResult)

    def test_apply_fee_uses_active_strategy(self):
        account = AccountFactory.create("current", "Alice", 5_000.0)
        calc    = FeeCalculator(ZeroFeeStrategy())
        result  = calc.apply_fee(account, 1_000.0)
        assert result.fee == 0.0

    def test_set_strategy_switches_calculation(self):
        account = AccountFactory.create("current", "Alice", 5_000.0)
        calc    = FeeCalculator()

        result_standard = calc.apply_fee(account, 1_000.0)

        calc.set_strategy(ZeroFeeStrategy())
        result_zero = calc.apply_fee(account, 1_000.0)

        assert result_standard.fee > result_zero.fee
        assert result_zero.fee == 0.0

    def test_estimate_does_not_publish_event(self):
        from tests.test_alert_system import RecordingObserver
        recorder = RecordingObserver()
        AlertSystem.get_instance().subscribe(EventType.FEE_APPLIED, recorder)

        calc = FeeCalculator()
        calc.estimate(1_000.0, "current")

        assert recorder.count() == 0

    def test_apply_fee_publishes_fee_event(self):
        from tests.test_alert_system import RecordingObserver
        recorder = RecordingObserver()
        AlertSystem.get_instance().subscribe(EventType.FEE_APPLIED, recorder)

        account = AccountFactory.create("current", "Alice", 5_000.0)
        FeeCalculator().apply_fee(account, 1_000.0)

        assert recorder.count() == 1
        event = recorder.received[0]
        assert event.event_type == EventType.FEE_APPLIED
        assert event.metadata["original_amount"] == 1_000.0

    def test_compare_strategies_returns_all(self):
        calc    = FeeCalculator()
        results = calc.compare_strategies(1_000.0, "current")
        names   = [r["strategy"] for r in results]
        assert "StandardFeeStrategy" in names
        assert "ZeroFeeStrategy" in names
        assert "TieredFeeStrategy" in names

    def test_compare_strategies_net_is_amount_minus_fee(self):
        calc    = FeeCalculator()
        results = calc.compare_strategies(1_000.0, "current")
        for row in results:
            assert row["net"] == pytest.approx(1_000.0 - row["fee"])
