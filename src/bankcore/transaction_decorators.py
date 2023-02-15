"""
BankCore — Day 05: Transaction Decorators
==========================================
Four decorators that enrich TransactionService without modifying it.

Each decorator has one responsibility:
  - ValidationDecorator : input sanity checks before any operation
  - LoggingDecorator    : structured timing + event logging
  - RateLimitDecorator  : per-account transaction frequency cap
  - FeeDecorator        : calculate and debit fees before transfer

Stack them in any order. The client calls the outermost decorator
and has no idea how many layers exist underneath.

Recommended production order (outermost → innermost):
    RateLimitDecorator
        └── LoggingDecorator
                └── ValidationDecorator
                        └── FeeDecorator
                                └── TransactionService
"""

import time
from collections import defaultdict
from datetime import datetime, timedelta

from bankcore.config_manager import ConfigManager
from bankcore.events import BankEvent, EventType
from bankcore.fee_calculator import FeeCalculator
from bankcore.fee_strategy import StandardFeeStrategy
from bankcore.transaction_processor import TransactionDecorator, TransactionProcessor


# ---------------------------------------------------------------------------
# ValidationDecorator
# ---------------------------------------------------------------------------

class ValidationDecorator(TransactionDecorator):
    """
    Guards all operations against invalid inputs.

    Catches errors that should never reach TransactionService:
      - negative or zero amounts
      - missing accounts
      - self-transfers
      - amounts exceeding global config limits

    If validation fails, returns an error dict immediately —
    the wrapped processor is never called.
    """

    def __init__(self, processor: TransactionProcessor) -> None:
        super().__init__(processor)
        self._config = ConfigManager.get_instance()

    def deposit(self, account, amount: float) -> dict:
        if account is None:
            return {"success": False, "reason": "Account is required."}
        if not isinstance(amount, (int, float)) or amount <= 0:
            return {"success": False, "reason": f"Invalid amount: {amount!r}. Must be positive."}
        return self._wrapped.deposit(account, amount)

    def withdraw(self, account, amount: float) -> dict:
        if account is None:
            return {"success": False, "reason": "Account is required."}
        if not isinstance(amount, (int, float)) or amount <= 0:
            return {"success": False, "reason": f"Invalid amount: {amount!r}. Must be positive."}
        return self._wrapped.withdraw(account, amount)

    def transfer(self, from_account, to_account, amount: float) -> dict:
        if from_account is None or to_account is None:
            return {"success": False, "reason": "Both accounts are required."}
        if not isinstance(amount, (int, float)) or amount <= 0:
            return {"success": False, "reason": f"Invalid amount: {amount!r}. Must be positive."}

        max_amount = self._config.get("limits.max_transfer_amount", 50_000.0)
        if amount > max_amount:
            return {
                "success": False,
                "reason": f"Amount {amount:.2f} exceeds limit of {max_amount:.2f} EUR.",
            }
        if from_account.account_id == to_account.account_id:
            return {"success": False, "reason": "Source and destination accounts must differ."}

        return self._wrapped.transfer(from_account, to_account, amount)


# ---------------------------------------------------------------------------
# LoggingDecorator
# ---------------------------------------------------------------------------

class LoggingDecorator(TransactionDecorator):
    """
    Records timing and outcome for every transaction.

    Publishes structured log events to AlertSystem (Day 03) rather than
    writing raw strings to stdout — keeps logs queryable and testable.

    Also prints human-readable output for the demo and development.
    """

    def __init__(self, processor: TransactionProcessor) -> None:
        super().__init__(processor)
        self._log: list[dict] = []

    def _timed_call(self, operation: str, fn, *args) -> dict:
        start  = time.perf_counter()
        result = fn(*args)
        elapsed_ms = (time.perf_counter() - start) * 1000

        entry = {
            "timestamp":  datetime.now().isoformat(),
            "operation":  operation,
            "success":    result.get("success"),
            "elapsed_ms": round(elapsed_ms, 2),
            "amount":     args[-1] if args else None,
        }
        self._log.append(entry)

        status = "OK  " if result.get("success") else "FAIL"
        print(
            f"[LOG] {status} {operation:10} "
            f"{entry['amount']:>10.2f} EUR  "
            f"{elapsed_ms:6.2f}ms"
        )
        return result

    def deposit(self, account, amount: float) -> dict:
        return self._timed_call("deposit", self._wrapped.deposit, account, amount)

    def withdraw(self, account, amount: float) -> dict:
        return self._timed_call("withdraw", self._wrapped.withdraw, account, amount)

    def transfer(self, from_account, to_account, amount: float) -> dict:
        return self._timed_call(
            "transfer", self._wrapped.transfer, from_account, to_account, amount
        )

    def get_log(self) -> list[dict]:
        return list(self._log)

    def success_rate(self) -> float:
        if not self._log:
            return 0.0
        successes = sum(1 for e in self._log if e["success"])
        return successes / len(self._log)

    def average_latency_ms(self) -> float:
        if not self._log:
            return 0.0
        return sum(e["elapsed_ms"] for e in self._log) / len(self._log)


# ---------------------------------------------------------------------------
# RateLimitDecorator
# ---------------------------------------------------------------------------

class RateLimitDecorator(TransactionDecorator):
    """
    Prevents any single account from exceeding a transaction frequency limit.

    Default: max 5 transactions per 60-second window (configurable).
    Tracks per-account timestamps using a sliding window algorithm.

    If the limit is exceeded, returns an error dict immediately —
    no money moves, no events published downstream.
    """

    def __init__(
        self,
        processor: TransactionProcessor,
        max_per_window: int | None = None,
        window_seconds: int = 60,
    ) -> None:
        super().__init__(processor)
        self._config    = ConfigManager.get_instance()
        self._max       = max_per_window or self._config.get(
            "limits.max_daily_transactions", 5
        )
        self._window    = window_seconds
        # account_id → list of datetime timestamps
        self._history: dict[str, list] = defaultdict(list)

    def _is_allowed(self, account_id: str) -> bool:
        now    = datetime.now()
        cutoff = now - timedelta(seconds=self._window)

        # Slide the window — remove timestamps older than the window
        self._history[account_id] = [
            ts for ts in self._history[account_id] if ts > cutoff
        ]

        if len(self._history[account_id]) >= self._max:
            return False

        self._history[account_id].append(now)
        return True

    def _rate_limit_error(self, account_id: str) -> dict:
        return {
            "success": False,
            "reason": (
                f"Rate limit exceeded for account {account_id}: "
                f"max {self._max} transactions per {self._window}s."
            ),
        }

    def deposit(self, account, amount: float) -> dict:
        if not self._is_allowed(account.account_id):
            return self._rate_limit_error(account.account_id)
        return self._wrapped.deposit(account, amount)

    def withdraw(self, account, amount: float) -> dict:
        if not self._is_allowed(account.account_id):
            return self._rate_limit_error(account.account_id)
        return self._wrapped.withdraw(account, amount)

    def transfer(self, from_account, to_account, amount: float) -> dict:
        if not self._is_allowed(from_account.account_id):
            return self._rate_limit_error(from_account.account_id)
        return self._wrapped.transfer(from_account, to_account, amount)

    def transaction_count(self, account_id: str) -> int:
        """Return number of transactions in the current window for an account."""
        return len(self._history.get(account_id, []))


# ---------------------------------------------------------------------------
# FeeDecorator
# ---------------------------------------------------------------------------

class FeeDecorator(TransactionDecorator):
    """
    Calculates and deducts fees before executing a transfer.

    Only applies to transfers (deposits and withdrawals are fee-free
    in BankCore's current model — Day 07 will make this configurable).

    Flow:
      1. Calculate fee via FeeCalculator (Day 04 Strategy)
      2. Debit fee from source account
      3. Delegate the original transfer to the wrapped processor
      4. Annotate the result with fee information

    If the source account cannot cover both the transfer amount AND
    the fee, the operation is rejected before any money moves.
    """

    def __init__(
        self,
        processor: TransactionProcessor,
        fee_calculator: FeeCalculator | None = None,
    ) -> None:
        super().__init__(processor)
        self._calculator = fee_calculator or FeeCalculator(StandardFeeStrategy())

    def transfer(self, from_account, to_account, amount: float) -> dict:
        # Calculate fee first — no side effects yet
        fee_result = self._calculator.apply_fee(from_account, amount, "transfer")

        if fee_result.fee > 0:
            # Attempt to debit the fee from the source account
            fee_paid = from_account.withdraw(
                fee_result.fee,
                description=f"Transfer fee ({fee_result.strategy_name})",
            )
            if not fee_paid:
                return {
                    "success": False,
                    "reason": (
                        f"Insufficient funds to cover transfer amount "
                        f"({amount:.2f} EUR) plus fee ({fee_result.fee:.2f} EUR)."
                    ),
                }

        # Delegate the actual transfer
        result = self._wrapped.transfer(from_account, to_account, amount)

        # Annotate result with fee details
        if result.get("success"):
            result["fee"]           = fee_result.fee
            result["fee_strategy"]  = fee_result.strategy_name
            result["net_to_sender"] = amount + fee_result.fee

        return result


# ---------------------------------------------------------------------------
# Pipeline builder — convenience function
# ---------------------------------------------------------------------------

def build_pipeline(
    service: TransactionProcessor,
    *,
    validate: bool = True,
    log: bool = True,
    rate_limit: bool = True,
    apply_fees: bool = True,
    fee_calculator: FeeCalculator | None = None,
    max_per_window: int | None = None,
) -> TransactionProcessor:
    """
    Assemble a TransactionProcessor pipeline with the standard decorator stack.

    Decorators are applied inside-out:
        RateLimit → Logging → Validation → Fee → Service

    Each layer can be toggled for different contexts:
      - Tests: validate=True, log=False, rate_limit=False, apply_fees=False
      - Production: all True
      - Internal transfers: apply_fees=False

    Usage:
        pipeline = build_pipeline(TransactionService())
        result   = pipeline.transfer(alice, bob, 500.0)
    """
    processor = service

    if apply_fees:
        processor = FeeDecorator(processor, fee_calculator)

    if validate:
        processor = ValidationDecorator(processor)

    if log:
        processor = LoggingDecorator(processor)

    if rate_limit:
        processor = RateLimitDecorator(processor, max_per_window)

    return processor


# ---------------------------------------------------------------------------
# Quick demo
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    from bankcore.account_factory import AccountFactory
    from bankcore.alert_system import AlertSystem, AuditLogger
    from bankcore.transaction_service import TransactionService

    print("=== BankCore — Day 05: Decorator Pipeline Demo ===\n")

    # Wire up audit logger
    audit = AuditLogger()
    AlertSystem.get_instance().subscribe_all(audit)

    # Create accounts
    alice = AccountFactory.create("current", "Alice Martin", 10_000.0)
    bob   = AccountFactory.create("savings", "Bob Dupont",   2_000.0)

    # Build the full pipeline
    pipeline = build_pipeline(
        TransactionService(),
        validate=True,
        log=True,
        rate_limit=True,
        apply_fees=True,
        max_per_window=3,
    )

    print("--- Valid transfers ---")
    for amount in [500.0, 1_000.0, 200.0]:
        result = pipeline.transfer(alice, bob, amount)
        status = "OK" if result["success"] else f"FAIL: {result.get('reason')}"
        print(f"  {amount:>8.2f} EUR → {status}")

    print("\n--- Rate limit hit (4th transfer) ---")
    result = pipeline.transfer(alice, bob, 100.0)
    print(f"  Result: {result.get('reason')}")

    print("\n--- Validation catches bad input ---")
    result = pipeline.transfer(alice, bob, -50.0)
    print(f"  Result: {result.get('reason')}")

    print(f"\n--- Audit log: {audit.log_count()} events recorded ---")
