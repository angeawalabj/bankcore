"""
BankCore — Day 23: Saga Pattern
=================================
Orchestrated saga for distributed transactions.

A Saga is a sequence of local transactions with compensation steps.
If any step fails, all completed steps are compensated in reverse order.

Design decisions:
  - Orchestration (not choreography): SagaOrchestrator directs all steps
  - Each step has execute() and compensate() — compensation is always defined
  - Saga state is tracked: PENDING → RUNNING → COMPLETED/COMPENSATING/...
  - Idempotent steps: execute() called twice = same result (safe retry)
  - Steps are pure functions: no global state, fully testable in isolation

Connection to Day 16 (Microservices):
  Each step calls a service through ServiceClient.
  The saga coordinates between services without coupling them.

Connection to Day 18 (MessageBus):
  Saga publishes events at each state transition.
  External observers (audit, monitoring) react to saga events.
"""

from __future__ import annotations
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Saga State
# ---------------------------------------------------------------------------

class SagaStatus(Enum):
    PENDING      = auto()   # created, not started
    RUNNING      = auto()   # steps executing
    COMPLETED    = auto()   # all steps succeeded
    COMPENSATING = auto()   # a step failed, compensating in reverse
    COMPENSATED  = auto()   # compensation complete (original state restored)
    FAILED       = auto()   # compensation also failed — needs manual intervention


# ---------------------------------------------------------------------------
# Step result
# ---------------------------------------------------------------------------

@dataclass
class StepResult:
    """Result of a single saga step (execute or compensate)."""
    success:    bool
    step_name:  str
    data:       dict = field(default_factory=dict)
    error:      str  = ""
    duration_ms: float = 0.0

    @classmethod
    def ok(cls, step_name: str, **data) -> "StepResult":
        return cls(success=True, step_name=step_name, data=data)

    @classmethod
    def fail(cls, step_name: str, error: str) -> "StepResult":
        return cls(success=False, step_name=step_name, error=error)


# ---------------------------------------------------------------------------
# SagaStep — abstract
# ---------------------------------------------------------------------------

class SagaStep(ABC):
    """
    One step in a Saga.
    Must implement both execute() and compensate().
    Compensation must always be defined — even if it's a no-op.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable step name for logging and debugging."""

    @abstractmethod
    def execute(self, context: dict) -> StepResult:
        """
        Execute this step.
        context: shared dict passed between steps (accumulates results).
        Returns StepResult with success=True and any output data.
        """

    @abstractmethod
    def compensate(self, context: dict) -> StepResult:
        """
        Undo this step's effects.
        context: same dict as execute() — contains step outputs needed for undo.
        Must not raise — return StepResult.fail() instead.
        """


# ---------------------------------------------------------------------------
# Saga execution log
# ---------------------------------------------------------------------------

@dataclass
class SagaEvent:
    """One entry in the saga's execution log."""
    timestamp:  str
    event_type: str   # "step_started", "step_completed", "step_failed", etc.
    step_name:  str   = ""
    details:    dict  = field(default_factory=dict)


# ---------------------------------------------------------------------------
# SagaOrchestrator
# ---------------------------------------------------------------------------

class SagaOrchestrator:
    """
    Orchestrates a sequence of steps with automatic compensation on failure.

    Usage:
        saga = SagaOrchestrator("international-transfer-saga")
        saga.add_step(DebitSourceStep(account_service))
        saga.add_step(ConvertCurrencyStep(fx_service))
        saga.add_step(CreditDestinationStep(account_service))

        result = saga.execute({"from_id": "ACC-001", "amount": 100.0, ...})
        if not result.success:
            print(f"Saga failed at step: {result.failed_step}")
            print(f"Status: {result.status}")  # COMPENSATED or FAILED
    """

    def __init__(self, name: str) -> None:
        self.name       = name
        self.saga_id    = str(uuid.uuid4())[:8].upper()
        self._steps:    list[SagaStep] = []
        self._status    = SagaStatus.PENDING
        self._log:      list[SagaEvent] = []
        self._context:  dict = {}
        self._completed_steps: list[SagaStep] = []

    def add_step(self, step: SagaStep) -> "SagaOrchestrator":
        self._steps.append(step)
        return self

    def execute(self, initial_context: dict = None) -> "SagaResult":
        """
        Execute all steps in order.
        On failure: compensate completed steps in reverse order.
        """
        import time
        self._context = dict(initial_context or {})
        self._context["saga_id"] = self.saga_id
        self._status  = SagaStatus.RUNNING
        self._log_event("saga_started", details={"steps": len(self._steps)})

        start = time.monotonic()

        # Forward pass
        failed_step   = None
        failed_result = None

        for step in self._steps:
            self._log_event("step_started", step.name)
            step_start = time.monotonic()

            try:
                result = step.execute(self._context)
                result.duration_ms = (time.monotonic() - step_start) * 1000
            except Exception as exc:
                result = StepResult.fail(step.name, str(exc))
                result.duration_ms = (time.monotonic() - step_start) * 1000

            if result.success:
                self._context.update(result.data)
                self._completed_steps.append(step)
                self._log_event("step_completed", step.name,
                                details={"duration_ms": result.duration_ms})
            else:
                failed_step   = step
                failed_result = result
                self._log_event("step_failed", step.name,
                                details={"error": result.error})
                break

        if failed_step is None:
            # All steps succeeded
            self._status = SagaStatus.COMPLETED
            self._log_event("saga_completed")
            return SagaResult(
                success=True,
                saga_id=self.saga_id,
                status=self._status,
                context=self._context,
                log=self._log,
                duration_ms=(time.monotonic() - start) * 1000,
            )

        # Compensation pass — reverse order
        self._status = SagaStatus.COMPENSATING
        self._log_event("saga_compensating",
                        details={"failed_step": failed_step.name})

        compensation_failed = False
        for step in reversed(self._completed_steps):
            self._log_event("compensation_started", step.name)
            try:
                comp_result = step.compensate(self._context)
            except Exception as exc:
                comp_result = StepResult.fail(step.name, str(exc))

            if comp_result.success:
                self._log_event("compensation_completed", step.name)
            else:
                self._log_event("compensation_failed", step.name,
                                details={"error": comp_result.error})
                compensation_failed = True

        self._status = SagaStatus.FAILED if compensation_failed else SagaStatus.COMPENSATED
        self._log_event("saga_ended",
                        details={"status": self._status.name})

        return SagaResult(
            success=False,
            saga_id=self.saga_id,
            status=self._status,
            context=self._context,
            log=self._log,
            failed_step=failed_step.name,
            failed_error=failed_result.error if failed_result else "",
            duration_ms=(time.monotonic() - start) * 1000,
        )

    def _log_event(
        self,
        event_type: str,
        step_name: str = "",
        details: dict = None,
    ) -> None:
        self._log.append(SagaEvent(
            timestamp=datetime.now().isoformat(),
            event_type=event_type,
            step_name=step_name,
            details=details or {},
        ))

    @property
    def status(self) -> SagaStatus:
        return self._status

    @property
    def log(self) -> list[SagaEvent]:
        return list(self._log)


# ---------------------------------------------------------------------------
# SagaResult
# ---------------------------------------------------------------------------

@dataclass
class SagaResult:
    """Final result of a saga execution."""
    success:      bool
    saga_id:      str
    status:       SagaStatus
    context:      dict
    log:          list[SagaEvent]
    failed_step:  str   = ""
    failed_error: str   = ""
    duration_ms:  float = 0.0

    def step_count(self, event_type: str = "step_completed") -> int:
        return sum(1 for e in self.log if e.event_type == event_type)

    def summary(self) -> str:
        return (
            f"Saga({self.saga_id}) {self.status.name} "
            f"in {self.duration_ms:.1f}ms — "
            f"steps_ok={self.step_count('step_completed')}"
            + (f" failed_at={self.failed_step}" if self.failed_step else "")
        )


# ---------------------------------------------------------------------------
# Concrete Steps for International Transfer Saga
# ---------------------------------------------------------------------------

class DebitSourceStep(SagaStep):
    """
    Step 1: Debit the source account.
    Compensation: credit the source account back.
    """

    def __init__(self, account_service) -> None:
        self._svc = account_service

    @property
    def name(self) -> str:
        return "DebitSource"

    def execute(self, context: dict) -> StepResult:
        from bankcore.services.shared.service_client import ServiceRequest
        from_id = context.get("from_account_id", "")
        amount  = context.get("amount", 0)

        # Get current balance
        get_resp = self._svc.handle(ServiceRequest("GET", f"/accounts/{from_id}"))
        if not get_resp.ok:
            return StepResult.fail(self.name, f"Account {from_id} not found.")

        balance     = get_resp.body.get("balance", 0)
        min_balance = get_resp.body.get("min_possible_balance", 0)

        if balance - amount < min_balance:
            return StepResult.fail(
                self.name,
                f"Insufficient funds: {balance:.2f} - {amount:.2f} < {min_balance:.2f}",
            )

        new_balance = balance - amount
        patch_resp  = self._svc.handle(ServiceRequest(
            "PATCH", f"/accounts/{from_id}/balance",
            body={"balance": new_balance},
        ))
        if not patch_resp.ok:
            return StepResult.fail(self.name, "Failed to debit source account.")

        return StepResult.ok(
            self.name,
            debited_amount=amount,
            source_balance_before=balance,
            source_balance_after=new_balance,
        )

    def compensate(self, context: dict) -> StepResult:
        """Restore the debited amount."""
        from bankcore.services.shared.service_client import ServiceRequest
        from_id             = context.get("from_account_id", "")
        balance_before      = context.get("source_balance_before", 0)

        patch_resp = self._svc.handle(ServiceRequest(
            "PATCH", f"/accounts/{from_id}/balance",
            body={"balance": balance_before},
        ))
        if not patch_resp.ok:
            return StepResult.fail(self.name, "Compensation failed: could not restore balance.")
        return StepResult.ok(self.name, restored_balance=balance_before)


class ConvertCurrencyStep(SagaStep):
    """
    Step 2: Convert currency via FxService.
    Compensation: no-op (no money moved, just rate looked up).
    """

    def __init__(self, fx_rates: dict = None) -> None:
        # Simplified: in-memory rates (real: call FxService)
        self._rates = fx_rates or {
            ("EUR", "GBP"): 0.87,
            ("EUR", "USD"): 1.08,
            ("GBP", "EUR"): 1.15,
            ("USD", "EUR"): 0.93,
        }

    @property
    def name(self) -> str:
        return "ConvertCurrency"

    def execute(self, context: dict) -> StepResult:
        from_currency = context.get("from_currency", "EUR")
        to_currency   = context.get("to_currency",   "EUR")
        amount        = context.get("amount",         0)

        if from_currency == to_currency:
            return StepResult.ok(
                self.name,
                converted_amount=amount,
                rate=1.0,
                from_currency=from_currency,
                to_currency=to_currency,
            )

        rate = self._rates.get((from_currency, to_currency))
        if rate is None:
            return StepResult.fail(
                self.name,
                f"No exchange rate for {from_currency} → {to_currency}",
            )

        converted = round(amount * rate, 2)
        return StepResult.ok(
            self.name,
            converted_amount=converted,
            rate=rate,
            from_currency=from_currency,
            to_currency=to_currency,
        )

    def compensate(self, context: dict) -> StepResult:
        # No money was moved — nothing to undo
        return StepResult.ok(self.name, note="No compensation needed for FX lookup.")


class CreditDestinationStep(SagaStep):
    """
    Step 3: Credit the destination account.
    Compensation: debit the destination account back.
    """

    def __init__(self, account_service) -> None:
        self._svc = account_service

    @property
    def name(self) -> str:
        return "CreditDestination"

    def execute(self, context: dict) -> StepResult:
        from bankcore.services.shared.service_client import ServiceRequest
        to_id   = context.get("to_account_id", "")
        amount  = context.get("converted_amount", context.get("amount", 0))

        get_resp = self._svc.handle(ServiceRequest("GET", f"/accounts/{to_id}"))
        if not get_resp.ok:
            return StepResult.fail(self.name, f"Account {to_id} not found.")

        current     = get_resp.body.get("balance", 0)
        new_balance = current + amount

        patch_resp = self._svc.handle(ServiceRequest(
            "PATCH", f"/accounts/{to_id}/balance",
            body={"balance": new_balance},
        ))
        if not patch_resp.ok:
            return StepResult.fail(self.name, "Failed to credit destination account.")

        return StepResult.ok(
            self.name,
            credited_amount=amount,
            dest_balance_before=current,
            dest_balance_after=new_balance,
        )

    def compensate(self, context: dict) -> StepResult:
        """Reverse the credit."""
        from bankcore.services.shared.service_client import ServiceRequest
        to_id           = context.get("to_account_id", "")
        balance_before  = context.get("dest_balance_before", 0)

        patch_resp = self._svc.handle(ServiceRequest(
            "PATCH", f"/accounts/{to_id}/balance",
            body={"balance": balance_before},
        ))
        if not patch_resp.ok:
            return StepResult.fail(self.name, "Compensation failed: could not reverse credit.")
        return StepResult.ok(self.name, restored_balance=balance_before)


class NotifyStep(SagaStep):
    """
    Step 4: Send notifications.
    Compensation: send cancellation notice.
    """

    def __init__(self) -> None:
        self._sent:       list[dict] = []
        self._cancelled:  list[dict] = []

    @property
    def name(self) -> str:
        return "Notify"

    def execute(self, context: dict) -> StepResult:
        notification = {
            "type":       "transfer_completed",
            "from_id":    context.get("from_account_id"),
            "to_id":      context.get("to_account_id"),
            "amount":     context.get("amount"),
            "converted":  context.get("converted_amount"),
            "saga_id":    context.get("saga_id"),
        }
        self._sent.append(notification)
        return StepResult.ok(self.name, notification_sent=True)

    def compensate(self, context: dict) -> StepResult:
        cancellation = {
            "type":    "transfer_cancelled",
            "saga_id": context.get("saga_id"),
        }
        self._cancelled.append(cancellation)
        return StepResult.ok(self.name, cancellation_sent=True)

    @property
    def sent(self) -> list[dict]:
        return list(self._sent)

    @property
    def cancelled(self) -> list[dict]:
        return list(self._cancelled)


# ---------------------------------------------------------------------------
# InternationalTransferSaga — pre-wired saga
# ---------------------------------------------------------------------------

def create_international_transfer_saga(
    account_service,
    fx_rates: dict = None,
    notify_step: NotifyStep = None,
) -> SagaOrchestrator:
    """
    Factory that assembles the InternationalTransfer saga.

    Args:
        account_service: AccountService instance
        fx_rates:        optional dict of (from, to) → rate
        notify_step:     optional NotifyStep (for testing/inspection)
    """
    notify = notify_step or NotifyStep()
    saga   = SagaOrchestrator("international-transfer")
    saga.add_step(DebitSourceStep(account_service))
    saga.add_step(ConvertCurrencyStep(fx_rates))
    saga.add_step(CreditDestinationStep(account_service))
    saga.add_step(notify)
    return saga
