"""
Tests — Day 21: Event Sourcing
================================
Test strategy:
  1. EventStore — append, get_events, versioning, optimistic locking
  2. StoredEvent — checksum, integrity verification
  3. AccountAggregate — open, deposit, withdraw, transfer, interest
  4. AccountAggregate.from_events() — full state reconstruction
  5. AccountProjection — current state from event stream
  6. BalanceHistoryProjection — balance evolution over time
  7. Concurrency — optimistic locking prevents lost updates
  8. Immutability — events cannot be modified
  9. Full flow — command → events → store → projection
"""

import sys
import pytest

sys.path.insert(0, "src")

from bankcore.config_manager import ConfigManager
from bankcore.alert_system import AlertSystem
from bankcore.account_type_registry import AccountTypeRegistry
from bankcore.account_factory import AccountFactory
from bankcore.domain.value_objects import Money, AccountId
from bankcore.domain.domain_events import (
    AccountOpened, MoneyDeposited, MoneyWithdrawn,
    MoneyTransferred, InterestApplied, InterestRateSet,
)
from bankcore.domain.event_sourcing.event_store import (
    InProcessEventStore, StoredEvent, ConcurrencyError,
)
from bankcore.domain.event_sourcing.aggregate import (
    AccountAggregate, AccountProjection, BalanceHistoryProjection,
)


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
def store():
    return InProcessEventStore()


@pytest.fixture
def alice_id():
    return "ACC-ALICE-001"


@pytest.fixture
def bob_id():
    return "ACC-BOB-001"


# ---------------------------------------------------------------------------
# EventStore — core behaviour
# ---------------------------------------------------------------------------

class TestEventStore:

    def test_append_returns_stored_event(self, store, alice_id):
        event  = AccountOpened(
            aggregate_id=AccountId(alice_id),
            owner_name="Alice",
            account_type="current",
            initial_deposit=Money.eur(1_000.0),
        )
        stored = store.append(event)
        assert isinstance(stored, StoredEvent)
        assert stored.sequence_number == 1
        assert stored.aggregate_version == 1

    def test_sequence_number_increments_globally(self, store, alice_id, bob_id):
        e1 = AccountOpened(aggregate_id=AccountId(alice_id),
                           owner_name="Alice", account_type="current",
                           initial_deposit=Money.eur(1_000.0))
        e2 = AccountOpened(aggregate_id=AccountId(bob_id),
                           owner_name="Bob", account_type="savings",
                           initial_deposit=Money.eur(500.0))
        s1 = store.append(e1)
        s2 = store.append(e2)
        assert s2.sequence_number == s1.sequence_number + 1

    def test_aggregate_version_per_aggregate(self, store, alice_id):
        for i in range(3):
            store.append(MoneyDeposited(
                aggregate_id=AccountId(alice_id),
                amount=Money.eur(100.0),
            ))
        events = store.get_events(alice_id)
        assert [e.aggregate_version for e in events] == [1, 2, 3]

    def test_get_events_in_order(self, store, alice_id):
        amounts = [100.0, 200.0, 300.0]
        for amount in amounts:
            store.append(MoneyDeposited(
                aggregate_id=AccountId(alice_id),
                amount=Money.eur(amount),
            ))
        events = store.get_events(alice_id)
        assert [e.event.amount.amount for e in events] == amounts

    def test_get_events_from_version(self, store, alice_id):
        for i in range(5):
            store.append(MoneyDeposited(
                aggregate_id=AccountId(alice_id),
                amount=Money.eur(100.0),
            ))
        events = store.get_events(alice_id, from_version=3)
        assert len(events) == 2   # only versions 4 and 5

    def test_get_version(self, store, alice_id):
        assert store.get_version(alice_id) == 0
        store.append(MoneyDeposited(
            aggregate_id=AccountId(alice_id),
            amount=Money.eur(100.0),
        ))
        assert store.get_version(alice_id) == 1

    def test_events_for_different_aggregates_isolated(self, store, alice_id, bob_id):
        store.append(MoneyDeposited(
            aggregate_id=AccountId(alice_id), amount=Money.eur(100.0)))
        store.append(MoneyDeposited(
            aggregate_id=AccountId(bob_id), amount=Money.eur(200.0)))

        alice_events = store.get_events(alice_id)
        bob_events   = store.get_events(bob_id)
        assert len(alice_events) == 1
        assert len(bob_events)   == 1

    def test_unknown_aggregate_returns_empty(self, store):
        assert store.get_events("NONEXISTENT") == []

    def test_total_event_count(self, store, alice_id, bob_id):
        store.append(MoneyDeposited(aggregate_id=AccountId(alice_id), amount=Money.eur(100.0)))
        store.append(MoneyDeposited(aggregate_id=AccountId(alice_id), amount=Money.eur(200.0)))
        store.append(MoneyDeposited(aggregate_id=AccountId(bob_id),   amount=Money.eur(300.0)))
        assert store.total_event_count() == 3

    def test_aggregate_count(self, store, alice_id, bob_id):
        store.append(MoneyDeposited(aggregate_id=AccountId(alice_id), amount=Money.eur(100.0)))
        store.append(MoneyDeposited(aggregate_id=AccountId(bob_id),   amount=Money.eur(100.0)))
        assert store.aggregate_count() == 2


# ---------------------------------------------------------------------------
# Checksum and integrity
# ---------------------------------------------------------------------------

class TestStoredEventIntegrity:

    def test_checksum_computed_on_append(self, store, alice_id):
        event  = MoneyDeposited(
            aggregate_id=AccountId(alice_id), amount=Money.eur(100.0))
        stored = store.append(event)
        assert len(stored.checksum) == 16

    def test_verify_checksum_passes_for_intact_event(self, store, alice_id):
        event  = MoneyDeposited(
            aggregate_id=AccountId(alice_id), amount=Money.eur(100.0))
        stored = store.append(event)
        assert stored.verify_checksum() is True

    def test_verify_integrity_no_errors_for_fresh_store(self, store, alice_id):
        store.append(MoneyDeposited(
            aggregate_id=AccountId(alice_id), amount=Money.eur(100.0)))
        errors = store.verify_integrity(alice_id)
        assert errors == []

    def test_stored_event_to_dict(self, store, alice_id):
        event  = MoneyDeposited(
            aggregate_id=AccountId(alice_id), amount=Money.eur(100.0))
        stored = store.append(event)
        d      = stored.to_dict()
        assert "sequence_number"   in d
        assert "aggregate_version" in d
        assert "checksum"          in d
        assert "payload"           in d


# ---------------------------------------------------------------------------
# Optimistic locking
# ---------------------------------------------------------------------------

class TestOptimisticLocking:

    def test_append_with_correct_expected_version(self, store, alice_id):
        store.append(MoneyDeposited(
            aggregate_id=AccountId(alice_id), amount=Money.eur(100.0)))
        # version is now 1 — append with expected_version=1 should work
        store.append(
            MoneyDeposited(aggregate_id=AccountId(alice_id), amount=Money.eur(200.0)),
            expected_version=1,
        )
        assert store.get_version(alice_id) == 2

    def test_append_with_wrong_expected_version_raises(self, store, alice_id):
        store.append(MoneyDeposited(
            aggregate_id=AccountId(alice_id), amount=Money.eur(100.0)))
        with pytest.raises(ConcurrencyError, match="version"):
            store.append(
                MoneyDeposited(aggregate_id=AccountId(alice_id), amount=Money.eur(200.0)),
                expected_version=0,   # wrong — already at version 1
            )

    def test_no_expected_version_always_succeeds(self, store, alice_id):
        store.append(MoneyDeposited(
            aggregate_id=AccountId(alice_id), amount=Money.eur(100.0)))
        # No expected_version → no locking → always succeeds
        store.append(MoneyDeposited(
            aggregate_id=AccountId(alice_id), amount=Money.eur(200.0)))
        assert store.get_version(alice_id) == 2


# ---------------------------------------------------------------------------
# AccountAggregate — commands
# ---------------------------------------------------------------------------

class TestAccountAggregate:

    def test_open_account(self):
        account = AccountAggregate()
        account.open("ACC-001", "Alice", "current", 1_000.0)
        assert account.balance     == 1_000.0
        assert account.owner_name  == "Alice"
        assert account.account_type == "current"

    def test_deposit(self):
        account = AccountAggregate()
        account.open("ACC-001", "Alice", "current", 500.0)
        account.deposit(300.0)
        assert account.balance == 800.0

    def test_withdraw(self):
        account = AccountAggregate()
        account.open("ACC-001", "Alice", "current", 1_000.0)
        account.withdraw(400.0)
        assert account.balance == 600.0

    def test_withdraw_insufficient_funds_raises(self):
        account = AccountAggregate()
        account.open("ACC-001", "Alice", "current", 100.0)
        with pytest.raises(ValueError, match="Insufficient"):
            account.withdraw(200.0)

    def test_transfer_out(self):
        account = AccountAggregate()
        account.open("ACC-001", "Alice", "current", 1_000.0)
        account.transfer_out(300.0, "ACC-002")
        assert account.balance == 700.0

    def test_apply_interest(self):
        account = AccountAggregate()
        account.open("ACC-001", "Bob", "savings", 1_000.0)
        account.set_interest_rate(0.025)
        account.apply_interest()
        assert account.balance == pytest.approx(1_025.0)

    def test_pending_events_collected(self):
        account = AccountAggregate()
        account.open("ACC-001", "Alice", "current", 500.0)
        account.deposit(100.0)
        account.withdraw(50.0)
        events = account.pop_pending_events()
        assert len(events) == 3   # AccountOpened + MoneyDeposited + MoneyWithdrawn

    def test_pop_pending_clears_queue(self):
        account = AccountAggregate()
        account.open("ACC-001", "Alice", "current", 500.0)
        account.pop_pending_events()
        assert account.pop_pending_events() == []

    def test_cannot_open_twice(self):
        account = AccountAggregate()
        account.open("ACC-001", "Alice", "current", 500.0)
        with pytest.raises(ValueError, match="already opened"):
            account.open("ACC-001", "Alice", "current", 500.0)


# ---------------------------------------------------------------------------
# AccountAggregate.from_events — state reconstruction
# ---------------------------------------------------------------------------

class TestAccountAggregateReconstruction:

    def test_reconstruct_from_single_open_event(self, store, alice_id):
        account = AccountAggregate()
        account.open(alice_id, "Alice", "current", 1_000.0)
        store.append_all(account.pop_pending_events())

        rebuilt = AccountAggregate.from_events(store.get_events(alice_id))
        assert rebuilt.balance     == 1_000.0
        assert rebuilt.owner_name  == "Alice"

    def test_reconstruct_after_multiple_operations(self, store, alice_id):
        account = AccountAggregate()
        account.open(alice_id, "Alice", "current", 1_000.0)
        account.deposit(500.0)
        account.withdraw(200.0)
        account.deposit(100.0)
        store.append_all(account.pop_pending_events())

        rebuilt = AccountAggregate.from_events(store.get_events(alice_id))
        assert rebuilt.balance == 1_400.0   # 1000+500-200+100

    def test_reconstruct_version(self, store, alice_id):
        account = AccountAggregate()
        account.open(alice_id, "Alice", "current", 1_000.0)
        account.deposit(100.0)
        account.deposit(200.0)
        store.append_all(account.pop_pending_events())

        rebuilt = AccountAggregate.from_events(store.get_events(alice_id))
        assert rebuilt.version == 3

    def test_balance_is_deterministic(self, store, alice_id):
        """Replaying the same events always produces the same balance."""
        account = AccountAggregate()
        account.open(alice_id, "Alice", "current", 1_000.0)
        account.deposit(500.0)
        account.withdraw(300.0)
        store.append_all(account.pop_pending_events())

        events = store.get_events(alice_id)
        b1 = AccountAggregate.from_events(events).balance
        b2 = AccountAggregate.from_events(events).balance
        assert b1 == b2 == 1_200.0


# ---------------------------------------------------------------------------
# InterestRateSet — ADR-009: custom interest rates survive reconstruction
# ---------------------------------------------------------------------------

class TestInterestRateReconstruction:

    def test_set_interest_rate_records_an_event(self, bob_id):
        account = AccountAggregate()
        account.open(bob_id, "Bob", "savings", 1_000.0)
        account.set_interest_rate(0.025)

        events = account.pop_pending_events()
        assert any(isinstance(e, InterestRateSet) for e in events)

    def test_custom_rate_survives_reconstruction(self, store, bob_id):
        """
        The regression this fix targets: a promotional rate (0.04) that
        differs from the savings default (0.025) must not be silently
        replaced by the default when the aggregate is rebuilt — that
        was exactly the ADR-009 gap (set_interest_rate() was an in-memory
        mutation, never persisted as an event).
        """
        account = AccountAggregate()
        account.open(bob_id, "Bob", "savings", 1_000.0)
        account.set_interest_rate(0.04)   # promotional rate, not the 0.025 default
        store.append_all(account.pop_pending_events())

        rebuilt = AccountAggregate.from_events(store.get_events(bob_id))
        assert rebuilt.interest_rate == 0.04

        rebuilt.apply_interest()
        assert rebuilt.balance == pytest.approx(1_040.0)   # 1000 * 1.04, not 1.025

    def test_rate_change_after_the_fact_also_survives(self, store, bob_id):
        """A rate changed on an existing account persists across reloads too."""
        account = AccountAggregate()
        account.open(bob_id, "Bob", "savings", 1_000.0)
        account.set_interest_rate(0.025)
        store.append_all(account.pop_pending_events())

        promoted = AccountAggregate.from_events(store.get_events(bob_id))
        promoted.set_interest_rate(0.05)
        store.append_all(promoted.pop_pending_events())

        rebuilt_again = AccountAggregate.from_events(store.get_events(bob_id))
        assert rebuilt_again.interest_rate == 0.05

    def test_default_rate_still_applies_when_never_set_explicitly(self, store, bob_id):
        """
        Backward-compatible fallback: a savings account that never had
        set_interest_rate() called still gets the type-based default
        (0.025) from _apply(AccountOpened) — unchanged behaviour.
        """
        account = AccountAggregate()
        account.open(bob_id, "Bob", "savings", 1_000.0)
        store.append_all(account.pop_pending_events())

        rebuilt = AccountAggregate.from_events(store.get_events(bob_id))
        assert rebuilt.interest_rate == 0.025


# ---------------------------------------------------------------------------
# AccountProjection
# ---------------------------------------------------------------------------

class TestAccountProjection:

    def test_projection_current_balance(self, store, alice_id):
        account = AccountAggregate()
        account.open(alice_id, "Alice", "current", 1_000.0)
        account.deposit(400.0)
        account.withdraw(150.0)
        store.append_all(account.pop_pending_events())

        proj = AccountProjection.from_store(store, alice_id)
        assert proj.balance == 1_250.0

    def test_projection_snapshot_fields(self, store, alice_id):
        account = AccountAggregate()
        account.open(alice_id, "Alice", "current", 500.0)
        store.append_all(account.pop_pending_events())

        proj = AccountProjection.from_store(store, alice_id)
        snap = proj.snapshot
        assert snap.account_id   == alice_id
        assert snap.owner_name   == "Alice"
        assert snap.account_type == "current"
        assert snap.event_count  == 1

    def test_projection_version_matches_store(self, store, alice_id):
        account = AccountAggregate()
        account.open(alice_id, "Alice", "current", 500.0)
        account.deposit(100.0)
        account.deposit(200.0)
        store.append_all(account.pop_pending_events())

        proj = AccountProjection.from_store(store, alice_id)
        assert proj.snapshot.version == store.get_version(alice_id)


# ---------------------------------------------------------------------------
# BalanceHistoryProjection
# ---------------------------------------------------------------------------

class TestBalanceHistoryProjection:

    def test_history_recorded_for_each_event(self, store, alice_id):
        account = AccountAggregate()
        account.open(alice_id, "Alice", "current", 1_000.0)
        account.deposit(500.0)
        account.withdraw(200.0)
        store.append_all(account.pop_pending_events())

        proj = BalanceHistoryProjection.from_store(store, alice_id)
        assert len(proj.history) == 3

    def test_history_balances_correct(self, store, alice_id):
        account = AccountAggregate()
        account.open(alice_id, "Alice", "current", 1_000.0)
        account.deposit(500.0)
        account.withdraw(200.0)
        store.append_all(account.pop_pending_events())

        proj     = BalanceHistoryProjection.from_store(store, alice_id)
        balances = [p.balance for p in proj.history]
        assert balances == [1_000.0, 1_500.0, 1_300.0]

    def test_balance_at_version(self, store, alice_id):
        account = AccountAggregate()
        account.open(alice_id, "Alice", "current", 1_000.0)
        account.deposit(500.0)   # v2 → 1500
        account.withdraw(200.0)  # v3 → 1300
        store.append_all(account.pop_pending_events())

        proj = BalanceHistoryProjection.from_store(store, alice_id)
        assert proj.balance_at_version(2) == 1_500.0
        assert proj.balance_at_version(1) == 1_000.0

    def test_current_balance_matches_projection(self, store, alice_id):
        account = AccountAggregate()
        account.open(alice_id, "Alice", "current", 1_000.0)
        account.deposit(500.0)
        store.append_all(account.pop_pending_events())

        history_proj = BalanceHistoryProjection.from_store(store, alice_id)
        account_proj = AccountProjection.from_store(store, alice_id)
        assert history_proj.current_balance == account_proj.balance


# ---------------------------------------------------------------------------
# Full flow
# ---------------------------------------------------------------------------

class TestEventSourcingFullFlow:

    def test_command_to_projection_full_cycle(self, store, alice_id, bob_id):
        """
        Full Event Sourcing cycle:
        Command → Aggregate → Events → Store → Projection
        """
        # Create Alice's account
        alice = AccountAggregate()
        alice.open(alice_id, "Alice", "current", 2_000.0)
        alice.deposit(1_000.0, "Salary")
        store.append_all(alice.pop_pending_events())

        # Create Bob's account
        bob = AccountAggregate()
        bob.open(bob_id, "Bob", "savings", 500.0)
        bob.set_interest_rate(0.025)
        store.append_all(bob.pop_pending_events())

        # Alice transfers to Bob
        alice_rebuilt = AccountAggregate.from_events(store.get_events(alice_id))
        alice_rebuilt.transfer_out(500.0, bob_id)
        store.append_all(alice_rebuilt.pop_pending_events())

        bob_rebuilt = AccountAggregate.from_events(store.get_events(bob_id))
        bob_rebuilt.deposit(500.0, f"Transfer from {alice_id}")
        store.append_all(bob_rebuilt.pop_pending_events())

        # Apply Bob's interest — rate is restored by from_events() via the
        # InterestRateSet event recorded above (ADR-009), no re-set needed.
        bob_final = AccountAggregate.from_events(store.get_events(bob_id))
        bob_final.apply_interest()
        store.append_all(bob_final.pop_pending_events())

        # Verify via projections
        alice_proj = AccountProjection.from_store(store, alice_id)
        bob_proj   = AccountProjection.from_store(store, bob_id)

        assert alice_proj.balance == 2_500.0   # 2000+1000-500
        assert bob_proj.balance   == pytest.approx(1_025.0)   # (500+500)*1.025

    def test_audit_trail_is_complete(self, store, alice_id):
        """Event Sourcing provides complete audit trail."""
        account = AccountAggregate()
        account.open(alice_id, "Alice", "current", 1_000.0)
        account.deposit(500.0,  "Salary")
        account.withdraw(100.0, "ATM")
        account.deposit(200.0,  "Refund")
        store.append_all(account.pop_pending_events())

        events = store.get_events(alice_id)
        event_types = [e.event_type for e in events]

        assert "AccountOpened"  in event_types
        assert "MoneyDeposited" in event_types
        assert "MoneyWithdrawn" in event_types
        assert len(events) == 4   # complete, nothing missing
