"""
Tests — Day 05: Transaction Decorators & Pipeline
===================================================
Test strategy:
  1. Each decorator in isolation (mocking the wrapped processor)
  2. Decorator stacking — correct order of execution
  3. build_pipeline() convenience function
  4. Integration with Days 01-04 (config, accounts, fees, alerts)
  5. Error propagation — a decorator refuses → no downstream call
"""

import sys
import pytest
from unittest.mock import MagicMock

sys.path.insert(0, "src")

from bankcore.config_manager import ConfigManager
from bankcore.account_factory import AccountFactory
from bankcore.alert_system import AlertSystem
from bankcore.transaction_service import TransactionService
from bankcore.transaction_processor import TransactionProcessor, TransactionDecorator
from bankcore.transaction_decorators import (
    ValidationDecorator, LoggingDecorator,
    RateLimitDecorator, FeeDecorator, build_pipeline,
)
from bankcore.fee_strategy import ZeroFeeStrategy, StandardFeeStrategy
from bankcore.fee_calculator import FeeCalculator


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_state():
    ConfigManager._reset()
    AlertSystem._reset()
    AccountFactory._reset_registry()
    yield
    ConfigManager._reset()
    AlertSystem._reset()
    AccountFactory._reset_registry()


@pytest.fixture
def alice():
    return AccountFactory.create("current", "Alice", 10_000.0)


@pytest.fixture
def bob():
    return AccountFactory.create("savings", "Bob", 2_000.0)


@pytest.fixture
def mock_processor():
    """A mock TransactionProcessor that always succeeds."""
    proc = MagicMock(spec=TransactionProcessor)
    proc.transfer.return_value = {"success": True, "amount": 0}
    proc.deposit.return_value  = {"success": True, "amount": 0}
    proc.withdraw.return_value = {"success": True, "amount": 0}
    return proc


# ---------------------------------------------------------------------------
# TransactionDecorator base
# ---------------------------------------------------------------------------

class TestTransactionDecorator:

    def test_delegates_deposit_by_default(self, mock_processor, alice):
        decorator = TransactionDecorator(mock_processor)
        decorator.deposit(alice, 100.0)
        mock_processor.deposit.assert_called_once_with(alice, 100.0)

    def test_delegates_withdraw_by_default(self, mock_processor, alice):
        decorator = TransactionDecorator(mock_processor)
        decorator.withdraw(alice, 100.0)
        mock_processor.withdraw.assert_called_once_with(alice, 100.0)

    def test_delegates_transfer_by_default(self, mock_processor, alice, bob):
        decorator = TransactionDecorator(mock_processor)
        decorator.transfer(alice, bob, 100.0)
        mock_processor.transfer.assert_called_once_with(alice, bob, 100.0)


# ---------------------------------------------------------------------------
# ValidationDecorator
# ---------------------------------------------------------------------------

class TestValidationDecorator:

    def test_passes_valid_transfer(self, mock_processor, alice, bob):
        dec = ValidationDecorator(mock_processor)
        result = dec.transfer(alice, bob, 100.0)
        mock_processor.transfer.assert_called_once()
        assert result["success"] is True

    def test_rejects_zero_amount(self, mock_processor, alice, bob):
        dec = ValidationDecorator(mock_processor)
        result = dec.transfer(alice, bob, 0.0)
        assert result["success"] is False
        mock_processor.transfer.assert_not_called()

    def test_rejects_negative_amount(self, mock_processor, alice, bob):
        dec = ValidationDecorator(mock_processor)
        result = dec.transfer(alice, bob, -100.0)
        assert result["success"] is False
        mock_processor.transfer.assert_not_called()

    def test_rejects_none_account(self, mock_processor, alice):
        dec = ValidationDecorator(mock_processor)
        result = dec.transfer(None, alice, 100.0)
        assert result["success"] is False
        mock_processor.transfer.assert_not_called()

    def test_rejects_same_account_transfer(self, mock_processor, alice):
        dec = ValidationDecorator(mock_processor)
        result = dec.transfer(alice, alice, 100.0)
        assert result["success"] is False
        mock_processor.transfer.assert_not_called()

    def test_rejects_amount_above_config_limit(self, mock_processor, alice, bob):
        ConfigManager.get_instance().set("limits.max_transfer_amount", 1_000.0)
        dec = ValidationDecorator(mock_processor)
        result = dec.transfer(alice, bob, 2_000.0)
        assert result["success"] is False
        mock_processor.transfer.assert_not_called()

    def test_passes_valid_deposit(self, mock_processor, alice):
        dec = ValidationDecorator(mock_processor)
        result = dec.deposit(alice, 200.0)
        mock_processor.deposit.assert_called_once()

    def test_rejects_invalid_deposit(self, mock_processor, alice):
        dec = ValidationDecorator(mock_processor)
        result = dec.deposit(alice, -50.0)
        assert result["success"] is False
        mock_processor.deposit.assert_not_called()


# ---------------------------------------------------------------------------
# LoggingDecorator
# ---------------------------------------------------------------------------

class TestLoggingDecorator:

    def test_records_successful_transfer(self, mock_processor, alice, bob):
        mock_processor.transfer.return_value = {"success": True, "amount": 500.0}
        dec = LoggingDecorator(mock_processor)
        dec.transfer(alice, bob, 500.0)
        assert len(dec.get_log()) == 1
        assert dec.get_log()[0]["operation"] == "transfer"

    def test_records_failed_transfer(self, mock_processor, alice, bob):
        mock_processor.transfer.return_value = {"success": False, "reason": "Insufficient funds"}
        dec = LoggingDecorator(mock_processor)
        dec.transfer(alice, bob, 999_999.0)
        assert dec.get_log()[0]["success"] is False

    def test_records_elapsed_time(self, mock_processor, alice, bob):
        mock_processor.transfer.return_value = {"success": True}
        dec = LoggingDecorator(mock_processor)
        dec.transfer(alice, bob, 100.0)
        assert "elapsed_ms" in dec.get_log()[0]
        assert dec.get_log()[0]["elapsed_ms"] >= 0

    def test_success_rate_all_pass(self, mock_processor, alice, bob):
        mock_processor.transfer.return_value = {"success": True}
        dec = LoggingDecorator(mock_processor)
        dec.transfer(alice, bob, 100.0)
        dec.transfer(alice, bob, 200.0)
        assert dec.success_rate() == 1.0

    def test_success_rate_mixed(self, mock_processor, alice, bob):
        dec = LoggingDecorator(mock_processor)
        mock_processor.transfer.return_value = {"success": True}
        dec.transfer(alice, bob, 100.0)
        mock_processor.transfer.return_value = {"success": False}
        dec.transfer(alice, bob, 200.0)
        assert dec.success_rate() == 0.5

    def test_get_log_returns_copy(self, mock_processor, alice, bob):
        mock_processor.transfer.return_value = {"success": True}
        dec = LoggingDecorator(mock_processor)
        dec.transfer(alice, bob, 100.0)
        log = dec.get_log()
        log.clear()
        assert len(dec.get_log()) == 1


# ---------------------------------------------------------------------------
# RateLimitDecorator
# ---------------------------------------------------------------------------

class TestRateLimitDecorator:

    def test_allows_transfers_within_limit(self, mock_processor, alice, bob):
        mock_processor.transfer.return_value = {"success": True}
        dec = RateLimitDecorator(mock_processor, max_per_window=3)
        for _ in range(3):
            result = dec.transfer(alice, bob, 100.0)
            assert result["success"] is True

    def test_blocks_transfer_above_limit(self, mock_processor, alice, bob):
        mock_processor.transfer.return_value = {"success": True}
        dec = RateLimitDecorator(mock_processor, max_per_window=2)
        dec.transfer(alice, bob, 100.0)
        dec.transfer(alice, bob, 100.0)
        result = dec.transfer(alice, bob, 100.0)
        assert result["success"] is False
        assert "Rate limit" in result["reason"]

    def test_different_accounts_have_independent_limits(self, mock_processor, alice, bob):
        carol = AccountFactory.create("current", "Carol", 5_000.0)
        mock_processor.transfer.return_value = {"success": True}
        dec = RateLimitDecorator(mock_processor, max_per_window=1)

        # Alice hits her limit
        dec.transfer(alice, bob, 100.0)
        result_alice = dec.transfer(alice, bob, 100.0)

        # Carol is still within her limit
        result_carol = dec.transfer(carol, bob, 100.0)

        assert result_alice["success"] is False
        assert result_carol["success"] is True

    def test_blocked_transfer_does_not_call_wrapped(self, mock_processor, alice, bob):
        mock_processor.transfer.return_value = {"success": True}
        dec = RateLimitDecorator(mock_processor, max_per_window=1)
        dec.transfer(alice, bob, 100.0)
        dec.transfer(alice, bob, 100.0)  # blocked
        assert mock_processor.transfer.call_count == 1

    def test_transaction_count_tracking(self, mock_processor, alice, bob):
        mock_processor.transfer.return_value = {"success": True}
        dec = RateLimitDecorator(mock_processor, max_per_window=5)
        dec.transfer(alice, bob, 100.0)
        dec.transfer(alice, bob, 200.0)
        assert dec.transaction_count(alice.account_id) == 2


# ---------------------------------------------------------------------------
# FeeDecorator
# ---------------------------------------------------------------------------

class TestFeeDecorator:

    def test_deducts_fee_from_source_before_transfer(self, alice, bob):
        service = TransactionService()
        calculator = FeeCalculator(StandardFeeStrategy())
        dec = FeeDecorator(service, calculator)

        balance_before = alice.balance
        result = dec.transfer(alice, bob, 1_000.0)

        expected_fee = StandardFeeStrategy().calculate(1_000.0, "current")
        assert result["success"] is True
        assert result["fee"] == expected_fee
        assert alice.balance == balance_before - 1_000.0 - expected_fee

    def test_zero_fee_strategy_no_deduction(self, alice, bob):
        service    = TransactionService()
        calculator = FeeCalculator(ZeroFeeStrategy())
        dec        = FeeDecorator(service, calculator)

        balance_before = alice.balance
        result = dec.transfer(alice, bob, 500.0)

        assert result["success"] is True
        assert result["fee"] == 0.0
        assert alice.balance == balance_before - 500.0

    def test_rejects_if_insufficient_for_fee(self, bob):
        # Create account with exactly enough for transfer but not the fee
        tight = AccountFactory.create("current", "Tight", 1_000.01)
        service    = TransactionService()
        calculator = FeeCalculator(StandardFeeStrategy())
        dec        = FeeDecorator(service, calculator)

        # 1000 + 1 EUR fee = 1001 EUR needed, but only 1000.01 available
        result = dec.transfer(tight, bob, 1_000.0)
        # Standard fee for 1000 EUR current = 1.00 EUR; 1000.01 - 1.00 - 1000.00 = 0.01 OK
        # Let's use a bigger amount that will definitely fail
        tight2 = AccountFactory.create("current", "Tight2", 500.0)
        result2 = dec.transfer(tight2, bob, 500.0)
        # 500 * 0.1% = 0.50 fee; 500 - 0.50 = 499.50 < 500 needed for transfer
        assert result2["success"] is False
        # The rejection message comes from either FeeDecorator (can't cover fee)
        # or TransactionService (can't cover transfer after fee deducted)
        assert result2.get("reason") is not None

    def test_does_not_apply_fee_to_deposits(self, mock_processor, alice):
        calculator = FeeCalculator(StandardFeeStrategy())
        dec        = FeeDecorator(mock_processor, calculator)
        mock_processor.deposit.return_value = {"success": True}
        dec.deposit(alice, 1_000.0)
        mock_processor.deposit.assert_called_once_with(alice, 1_000.0)


# ---------------------------------------------------------------------------
# Pipeline integration
# ---------------------------------------------------------------------------

class TestBuildPipeline:

    def test_full_pipeline_successful_transfer(self, alice, bob):
        pipeline = build_pipeline(
            TransactionService(),
            validate=True, log=True, rate_limit=True,
            apply_fees=True,
            fee_calculator=FeeCalculator(ZeroFeeStrategy()),
            max_per_window=10,
        )
        result = pipeline.transfer(alice, bob, 500.0)
        assert result["success"] is True

    def test_pipeline_validation_rejects_bad_input(self, alice, bob):
        pipeline = build_pipeline(TransactionService(), max_per_window=10)
        result   = pipeline.transfer(alice, bob, -100.0)
        assert result["success"] is False

    def test_pipeline_rate_limit_blocks_after_max(self, alice, bob):
        pipeline = build_pipeline(
            TransactionService(),
            apply_fees=False,
            fee_calculator=FeeCalculator(ZeroFeeStrategy()),
            max_per_window=2,
        )
        pipeline.transfer(alice, bob, 100.0)
        pipeline.transfer(alice, bob, 100.0)
        result = pipeline.transfer(alice, bob, 100.0)
        assert result["success"] is False
        assert "Rate limit" in result["reason"]

    def test_pipeline_without_fees(self, alice, bob):
        balance_before = alice.balance
        pipeline = build_pipeline(
            TransactionService(),
            validate=True, log=False, rate_limit=False, apply_fees=False,
        )
        pipeline.transfer(alice, bob, 300.0)
        assert alice.balance == balance_before - 300.0

    def test_pipeline_returns_transaction_processor(self):
        pipeline = build_pipeline(TransactionService())
        assert isinstance(pipeline, TransactionProcessor)


# ---------------------------------------------------------------------------
# End-to-end: all 5 days working together
# ---------------------------------------------------------------------------

class TestWeek1Integration:
    """
    The full Week 1 system:
    ConfigManager (J01) + AccountFactory (J02) + AlertSystem (J03)
    + FeeCalculator (J04) + TransactionPipeline (J05)
    """

    def test_complete_transfer_flow(self, alice, bob):
        from bankcore.alert_system import AuditLogger
        audit = AuditLogger()
        AlertSystem.get_instance().subscribe_all(audit)

        pipeline = build_pipeline(
            TransactionService(),
            validate=True, log=True, rate_limit=True,
            apply_fees=True,
            fee_calculator=FeeCalculator(StandardFeeStrategy()),
            max_per_window=10,
        )

        result = pipeline.transfer(alice, bob, 1_000.0)

        assert result["success"] is True
        assert result["fee"] == StandardFeeStrategy().calculate(1_000.0, "current")
        # AlertSystem received at least the transfer event + fee event
        assert audit.log_count() >= 2

    def test_config_limit_enforced_through_pipeline(self, alice, bob):
        ConfigManager.get_instance().set("limits.max_transfer_amount", 200.0)
        pipeline = build_pipeline(TransactionService(), apply_fees=False)
        result   = pipeline.transfer(alice, bob, 500.0)
        assert result["success"] is False
        assert "limit" in result["reason"].lower()
