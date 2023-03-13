"""
Tests — Day 23: Saga Pattern
==============================
Test strategy:
  1. SagaOrchestrator — happy path, all steps complete
  2. Compensation — failure triggers reverse compensation
  3. Each step in isolation — execute and compensate
  4. Saga state machine — status transitions
  5. Execution log — all events recorded
  6. InternationalTransferSaga — full integration
  7. Partial failure — compensation restores original state
  8. Compensation failure — FAILED status, needs manual intervention
"""

import sys
import pytest

sys.path.insert(0, "src")

from bankcore.config_manager import ConfigManager
from bankcore.alert_system import AlertSystem
from bankcore.account_type_registry import AccountTypeRegistry
from bankcore.account_factory import AccountFactory
from bankcore.application.saga.saga import (
    SagaOrchestrator, SagaStatus, SagaStep, StepResult,
    DebitSourceStep, ConvertCurrencyStep, CreditDestinationStep,
    NotifyStep, create_international_transfer_saga,
)
from bankcore.services.account_service.service import AccountService
from bankcore.services.shared.service_client import ServiceRequest


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


@pytest.fixture
def account_svc():
    return AccountService()


@pytest.fixture
def alice_id(account_svc):
    r = account_svc.handle(ServiceRequest(
        "POST", "/accounts",
        body={"owner_name": "Alice", "account_type": "current",
              "initial_deposit": 2_000.0}
    ))
    return r.body["account_id"]


@pytest.fixture
def bob_id(account_svc):
    r = account_svc.handle(ServiceRequest(
        "POST", "/accounts",
        body={"owner_name": "Bob", "account_type": "current",
              "initial_deposit": 500.0}
    ))
    return r.body["account_id"]


# ---------------------------------------------------------------------------
# Helper steps for testing
# ---------------------------------------------------------------------------

class SuccessStep(SagaStep):
    def __init__(self, name: str, output: dict = None):
        self._name   = name
        self._output = output or {}
        self.executed    = False
        self.compensated = False

    @property
    def name(self) -> str:
        return self._name

    def execute(self, context: dict) -> StepResult:
        self.executed = True
        return StepResult.ok(self._name, **self._output)

    def compensate(self, context: dict) -> StepResult:
        self.compensated = True
        return StepResult.ok(self._name)


class FailStep(SagaStep):
    def __init__(self, name: str, error: str = "Simulated failure"):
        self._name  = name
        self._error = error

    @property
    def name(self) -> str:
        return self._name

    def execute(self, context: dict) -> StepResult:
        return StepResult.fail(self._name, self._error)

    def compensate(self, context: dict) -> StepResult:
        return StepResult.ok(self._name)


class FailCompensateStep(SagaStep):
    """A step that succeeds but whose compensation fails."""
    def __init__(self, name: str):
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def execute(self, context: dict) -> StepResult:
        return StepResult.ok(self._name)

    def compensate(self, context: dict) -> StepResult:
        return StepResult.fail(self._name, "Compensation failed!")


# ---------------------------------------------------------------------------
# SagaOrchestrator — core behaviour
# ---------------------------------------------------------------------------

class TestSagaOrchestrator:

    def test_all_steps_succeed(self):
        s1 = SuccessStep("step1")
        s2 = SuccessStep("step2")
        s3 = SuccessStep("step3")

        saga   = SagaOrchestrator("test-saga")
        result = saga.add_step(s1).add_step(s2).add_step(s3).execute()

        assert result.success is True
        assert result.status == SagaStatus.COMPLETED
        assert s1.executed and s2.executed and s3.executed

    def test_failure_triggers_compensation(self):
        s1 = SuccessStep("step1")
        s2 = SuccessStep("step2")
        s3 = FailStep("step3")

        saga   = SagaOrchestrator("test-saga")
        result = saga.add_step(s1).add_step(s2).add_step(s3).execute()

        assert result.success is False
        assert result.status == SagaStatus.COMPENSATED
        assert s1.compensated
        assert s2.compensated

    def test_only_completed_steps_are_compensated(self):
        s1 = SuccessStep("step1")
        s2 = FailStep("step2")
        s3 = SuccessStep("step3")   # never executed

        saga   = SagaOrchestrator("test-saga")
        result = saga.add_step(s1).add_step(s2).add_step(s3).execute()

        assert s1.compensated
        assert not s3.executed      # never ran
        assert not s3.compensated   # never compensated

    def test_compensation_order_is_reversed(self):
        order = []

        class OrderedStep(SagaStep):
            def __init__(self, n):
                self._n = n
            @property
            def name(self): return f"step{self._n}"
            def execute(self, ctx): return StepResult.ok(self.name)
            def compensate(self, ctx):
                order.append(self._n)
                return StepResult.ok(self.name)

        saga = SagaOrchestrator("test")
        for i in range(1, 4):
            saga.add_step(OrderedStep(i))
        saga.add_step(FailStep("fail"))
        saga.execute()

        assert order == [3, 2, 1]   # compensated in reverse order

    def test_failed_step_error_captured(self):
        saga   = SagaOrchestrator("test")
        result = saga.add_step(FailStep("bad", "specific error message")).execute()
        assert result.failed_step  == "bad"
        assert "specific error message" in result.failed_error

    def test_saga_status_pending_before_execute(self):
        saga = SagaOrchestrator("test")
        assert saga.status == SagaStatus.PENDING

    def test_saga_status_completed_after_success(self):
        saga = SagaOrchestrator("test")
        saga.add_step(SuccessStep("s1")).execute()
        assert saga.status == SagaStatus.COMPLETED

    def test_saga_status_compensated_after_failure(self):
        saga = SagaOrchestrator("test")
        saga.add_step(SuccessStep("s1")).add_step(FailStep("s2")).execute()
        assert saga.status == SagaStatus.COMPENSATED

    def test_saga_status_failed_when_compensation_fails(self):
        saga = SagaOrchestrator("test")
        saga.add_step(FailCompensateStep("s1")).add_step(FailStep("s2")).execute()
        assert saga.status == SagaStatus.FAILED

    def test_context_shared_between_steps(self):
        class WriterStep(SagaStep):
            @property
            def name(self): return "writer"
            def execute(self, ctx):
                return StepResult.ok(self.name, written_value=42)
            def compensate(self, ctx): return StepResult.ok(self.name)

        class ReaderStep(SagaStep):
            def __init__(self):
                self.read_value = None
            @property
            def name(self): return "reader"
            def execute(self, ctx):
                self.read_value = ctx.get("written_value")
                return StepResult.ok(self.name)
            def compensate(self, ctx): return StepResult.ok(self.name)

        writer = WriterStep()
        reader = ReaderStep()
        SagaOrchestrator("test").add_step(writer).add_step(reader).execute()
        assert reader.read_value == 42

    def test_duration_recorded(self):
        saga   = SagaOrchestrator("test")
        result = saga.add_step(SuccessStep("s1")).execute()
        assert result.duration_ms >= 0

    def test_empty_saga_completes(self):
        saga   = SagaOrchestrator("empty")
        result = saga.execute()
        assert result.success is True
        assert result.status  == SagaStatus.COMPLETED


# ---------------------------------------------------------------------------
# Execution log
# ---------------------------------------------------------------------------

class TestSagaLog:

    def test_log_contains_saga_started(self):
        saga   = SagaOrchestrator("test")
        result = saga.add_step(SuccessStep("s1")).execute()
        event_types = [e.event_type for e in result.log]
        assert "saga_started" in event_types

    def test_log_contains_step_events(self):
        saga   = SagaOrchestrator("test")
        result = saga.add_step(SuccessStep("s1")).execute()
        event_types = [e.event_type for e in result.log]
        assert "step_started"   in event_types
        assert "step_completed" in event_types

    def test_log_contains_compensation_events_on_failure(self):
        saga   = SagaOrchestrator("test")
        result = (saga.add_step(SuccessStep("s1"))
                      .add_step(FailStep("s2"))
                      .execute())
        event_types = [e.event_type for e in result.log]
        assert "saga_compensating"    in event_types
        assert "compensation_started" in event_types

    def test_step_count_helper(self):
        saga   = SagaOrchestrator("test")
        result = (saga.add_step(SuccessStep("s1"))
                      .add_step(SuccessStep("s2"))
                      .add_step(SuccessStep("s3"))
                      .execute())
        assert result.step_count("step_completed") == 3

    def test_summary_readable(self):
        saga   = SagaOrchestrator("test")
        result = saga.add_step(SuccessStep("s1")).execute()
        s      = result.summary()
        assert "COMPLETED" in s
        assert result.saga_id in s


# ---------------------------------------------------------------------------
# Individual steps
# ---------------------------------------------------------------------------

class TestDebitSourceStep:

    def test_debit_succeeds(self, account_svc, alice_id):
        step   = DebitSourceStep(account_svc)
        result = step.execute({
            "from_account_id": alice_id,
            "amount": 500.0,
        })
        assert result.success is True
        assert result.data["source_balance_after"] == 1_500.0

    def test_debit_insufficient_funds(self, account_svc, alice_id):
        step   = DebitSourceStep(account_svc)
        result = step.execute({
            "from_account_id": alice_id,
            "amount": 99_999.0,
        })
        assert result.success is False
        assert "Insufficient" in result.error

    def test_debit_unknown_account(self, account_svc):
        step   = DebitSourceStep(account_svc)
        result = step.execute({"from_account_id": "GHOST", "amount": 100.0})
        assert result.success is False

    def test_compensation_restores_balance(self, account_svc, alice_id):
        step    = DebitSourceStep(account_svc)
        context = {"from_account_id": alice_id, "amount": 300.0}
        step.execute(context)
        context["source_balance_before"] = 2_000.0
        step.compensate(context)

        resp = account_svc.handle(ServiceRequest("GET", f"/accounts/{alice_id}"))
        assert resp.body["balance"] == 2_000.0


class TestConvertCurrencyStep:

    def test_eur_to_gbp(self):
        step   = ConvertCurrencyStep()
        result = step.execute({
            "amount": 100.0,
            "from_currency": "EUR",
            "to_currency": "GBP",
        })
        assert result.success is True
        assert result.data["converted_amount"] == pytest.approx(87.0)
        assert result.data["rate"] == 0.87

    def test_same_currency_no_conversion(self):
        step   = ConvertCurrencyStep()
        result = step.execute({
            "amount": 100.0,
            "from_currency": "EUR",
            "to_currency": "EUR",
        })
        assert result.success is True
        assert result.data["converted_amount"] == 100.0
        assert result.data["rate"] == 1.0

    def test_unknown_currency_pair_fails(self):
        step   = ConvertCurrencyStep()
        result = step.execute({
            "amount": 100.0,
            "from_currency": "EUR",
            "to_currency": "JPY",
        })
        assert result.success is False

    def test_compensation_is_noop(self):
        step   = ConvertCurrencyStep()
        result = step.compensate({})
        assert result.success is True


class TestCreditDestinationStep:

    def test_credit_succeeds(self, account_svc, bob_id):
        step   = CreditDestinationStep(account_svc)
        result = step.execute({
            "to_account_id": bob_id,
            "converted_amount": 87.0,
        })
        assert result.success is True
        assert result.data["dest_balance_after"] == 587.0

    def test_credit_unknown_account_fails(self, account_svc):
        step   = CreditDestinationStep(account_svc)
        result = step.execute({"to_account_id": "GHOST", "converted_amount": 100.0})
        assert result.success is False

    def test_compensation_reverses_credit(self, account_svc, bob_id):
        step    = CreditDestinationStep(account_svc)
        context = {"to_account_id": bob_id, "converted_amount": 200.0}
        step.execute(context)
        context["dest_balance_before"] = 500.0
        step.compensate(context)

        resp = account_svc.handle(ServiceRequest("GET", f"/accounts/{bob_id}"))
        assert resp.body["balance"] == 500.0


class TestNotifyStep:

    def test_execute_records_notification(self):
        step   = NotifyStep()
        result = step.execute({
            "from_account_id": "ACC-001",
            "to_account_id":   "ACC-002",
            "amount": 100.0,
            "converted_amount": 87.0,
            "saga_id": "SAGA-001",
        })
        assert result.success is True
        assert len(step.sent) == 1
        assert step.sent[0]["type"] == "transfer_completed"

    def test_compensate_records_cancellation(self):
        step = NotifyStep()
        step.compensate({"saga_id": "SAGA-001"})
        assert len(step.cancelled) == 1
        assert step.cancelled[0]["type"] == "transfer_cancelled"


# ---------------------------------------------------------------------------
# InternationalTransferSaga — full integration
# ---------------------------------------------------------------------------

class TestInternationalTransferSaga:

    def test_successful_eur_to_gbp_transfer(self, account_svc, alice_id, bob_id):
        notify = NotifyStep()
        saga   = create_international_transfer_saga(account_svc, notify_step=notify)
        result = saga.execute({
            "from_account_id": alice_id,
            "to_account_id":   bob_id,
            "amount":          100.0,
            "from_currency":   "EUR",
            "to_currency":     "GBP",
        })

        assert result.success is True
        assert result.status  == SagaStatus.COMPLETED
        assert len(notify.sent) == 1

        alice_resp = account_svc.handle(ServiceRequest("GET", f"/accounts/{alice_id}"))
        bob_resp   = account_svc.handle(ServiceRequest("GET", f"/accounts/{bob_id}"))
        assert alice_resp.body["balance"] == 1_900.0   # 2000 - 100
        assert bob_resp.body["balance"]   == pytest.approx(587.0)  # 500 + 87

    def test_compensation_on_unknown_destination(self, account_svc, alice_id):
        """
        Saga Compensation test:
        Debit Alice → FX conversion → Credit GHOST (fails)
        → Compensation: restore Alice's balance
        """
        notify = NotifyStep()
        saga   = create_international_transfer_saga(account_svc, notify_step=notify)
        result = saga.execute({
            "from_account_id": alice_id,
            "to_account_id":   "GHOST-ACCOUNT",
            "amount":          500.0,
            "from_currency":   "EUR",
            "to_currency":     "EUR",
        })

        assert result.success is False
        assert result.status  == SagaStatus.COMPENSATED
        assert result.failed_step == "CreditDestination"

        # Alice's balance should be RESTORED
        alice_resp = account_svc.handle(ServiceRequest("GET", f"/accounts/{alice_id}"))
        assert alice_resp.body["balance"] == 2_000.0   # fully restored

    def test_notify_not_sent_on_failure(self, account_svc, alice_id):
        """
        NotifyStep is step 4 — if CreditDestination (step 3) fails,
        NotifyStep never executes, so no notification is sent.
        Compensation of NotifyStep also doesn't run (it never ran).
        This is correct: the client is notified of failure by a separate
        error response, not by the saga's internal NotifyStep.
        """
        notify = NotifyStep()
        saga   = create_international_transfer_saga(account_svc, notify_step=notify)
        saga.execute({
            "from_account_id": alice_id,
            "to_account_id":   "GHOST",
            "amount":          100.0,
            "from_currency":   "EUR",
            "to_currency":     "EUR",
        })
        # NotifyStep never executed (failed before reaching it)
        assert len(notify.sent) == 0
        assert len(notify.cancelled) == 0

    def test_insufficient_funds_never_debits(self, account_svc, alice_id, bob_id):
        """
        If DebitSource fails, no compensation needed.
        Alice's balance should remain unchanged.
        """
        notify = NotifyStep()
        saga   = create_international_transfer_saga(account_svc, notify_step=notify)
        result = saga.execute({
            "from_account_id": alice_id,
            "to_account_id":   bob_id,
            "amount":          99_999.0,
            "from_currency":   "EUR",
            "to_currency":     "EUR",
        })

        assert result.success is False
        assert result.failed_step == "DebitSource"
        assert result.status      == SagaStatus.COMPENSATED

        alice_resp = account_svc.handle(ServiceRequest("GET", f"/accounts/{alice_id}"))
        assert alice_resp.body["balance"] == 2_000.0   # untouched

    def test_unknown_fx_rate_compensates_debit(self, account_svc, alice_id, bob_id):
        """
        FX conversion fails → debit already happened → compensation restores Alice.
        """
        notify = NotifyStep()
        saga   = create_international_transfer_saga(account_svc, notify_step=notify)
        result = saga.execute({
            "from_account_id": alice_id,
            "to_account_id":   bob_id,
            "amount":          200.0,
            "from_currency":   "EUR",
            "to_currency":     "JPY",   # no rate defined
        })

        assert result.success is False
        assert result.failed_step == "ConvertCurrency"
        assert result.status      == SagaStatus.COMPENSATED

        # Alice's debit was compensated
        alice_resp = account_svc.handle(ServiceRequest("GET", f"/accounts/{alice_id}"))
        assert alice_resp.body["balance"] == 2_000.0
