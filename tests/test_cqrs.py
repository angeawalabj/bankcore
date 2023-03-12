"""
Tests — Day 22: CQRS
======================
Test strategy:
  1. Commands — open, deposit, withdraw, transfer, interest
  2. CommandResult — success/failure structure
  3. Read Models — balance, summary, history updated by events
  4. Queries — balance, summary, list, history
  5. ProjectionUpdater — event → read model
  6. CQRSFacade — integrated command + query
  7. CQRS separation — queries never touch EventStore
  8. Eventual consistency — read model reflects command results
  9. Full banking flow — open → deposit → transfer → query
"""

import sys
import pytest

sys.path.insert(0, "src")

from bankcore.config_manager import ConfigManager
from bankcore.alert_system import AlertSystem
from bankcore.account_type_registry import AccountTypeRegistry
from bankcore.account_factory import AccountFactory
from bankcore.application.cqrs.cqrs import (
    CQRSFacade,
    OpenAccountCommand, DepositCommand, WithdrawCommand,
    TransferCommand, ApplyInterestCommand,
    GetBalanceQuery, GetAccountSummaryQuery,
    ListAccountsQuery, GetTransactionHistoryQuery,
    CommandResult, ReadModelStore, ProjectionUpdater,
    AccountCommandHandler, AccountQueryHandler,
)
from bankcore.domain.event_sourcing.event_store import InProcessEventStore


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
def facade():
    return CQRSFacade()


@pytest.fixture
def alice_id():
    return "ACC-ALICE-001"


@pytest.fixture
def bob_id():
    return "ACC-BOB-001"


@pytest.fixture
def alice(facade, alice_id):
    facade.handle_command(OpenAccountCommand(
        account_id=alice_id,
        owner_name="Alice",
        account_type="current",
        initial_deposit=2_000.0,
    ))
    return alice_id


@pytest.fixture
def bob(facade, bob_id):
    facade.handle_command(OpenAccountCommand(
        account_id=bob_id,
        owner_name="Bob",
        account_type="savings",
        initial_deposit=1_000.0,
        interest_rate=0.025,
    ))
    return bob_id


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

class TestCommands:

    def test_open_account_succeeds(self, facade, alice_id):
        result = facade.handle_command(OpenAccountCommand(
            account_id=alice_id,
            owner_name="Alice",
            account_type="current",
            initial_deposit=1_000.0,
        ))
        assert result.success is True
        assert result.aggregate_id == alice_id
        assert result.version == 1

    def test_deposit_succeeds(self, facade, alice):
        result = facade.handle_command(DepositCommand(
            account_id=alice, amount=500.0
        ))
        assert result.success is True

    def test_withdraw_succeeds(self, facade, alice):
        result = facade.handle_command(WithdrawCommand(
            account_id=alice, amount=300.0
        ))
        assert result.success is True

    def test_withdraw_insufficient_funds_fails(self, facade, alice):
        result = facade.handle_command(WithdrawCommand(
            account_id=alice, amount=99_999.0
        ))
        assert result.success is False
        assert "Insufficient" in result.error

    def test_transfer_succeeds(self, facade, alice, bob):
        result = facade.handle_command(TransferCommand(
            from_account_id=alice,
            to_account_id=bob,
            amount=500.0,
        ))
        assert result.success is True

    def test_transfer_unknown_account_fails(self, facade, alice):
        result = facade.handle_command(TransferCommand(
            from_account_id=alice,
            to_account_id="GHOST",
            amount=100.0,
        ))
        assert result.success is False
        assert "not found" in result.error

    def test_apply_interest_succeeds(self, facade, bob):
        result = facade.handle_command(ApplyInterestCommand(account_id=bob))
        assert result.success is True

    def test_apply_interest_no_rate_fails(self, facade, alice):
        # Alice has no interest rate (current account)
        result = facade.handle_command(ApplyInterestCommand(account_id=alice))
        assert result.success is False

    def test_command_result_structure(self, facade, alice_id):
        result = facade.handle_command(OpenAccountCommand(
            account_id=alice_id,
            owner_name="Alice",
            account_type="current",
            initial_deposit=1_000.0,
        ))
        assert isinstance(result, CommandResult)
        assert result.version > 0
        assert result.error == ""

    def test_version_increments_with_commands(self, facade, alice):
        v1 = facade.handle_command(DepositCommand(account_id=alice, amount=100.0)).version
        v2 = facade.handle_command(DepositCommand(account_id=alice, amount=200.0)).version
        assert v2 == v1 + 1


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

class TestQueries:

    def test_get_balance_after_open(self, facade, alice):
        balance = facade.handle_query(GetBalanceQuery(account_id=alice))
        assert balance == 2_000.0

    def test_get_balance_after_deposit(self, facade, alice):
        facade.handle_command(DepositCommand(account_id=alice, amount=500.0))
        balance = facade.handle_query(GetBalanceQuery(account_id=alice))
        assert balance == 2_500.0

    def test_get_balance_after_withdrawal(self, facade, alice):
        facade.handle_command(WithdrawCommand(account_id=alice, amount=300.0))
        balance = facade.handle_query(GetBalanceQuery(account_id=alice))
        assert balance == 1_700.0

    def test_get_balance_unknown_account_returns_none(self, facade):
        balance = facade.handle_query(GetBalanceQuery(account_id="GHOST"))
        assert balance is None

    def test_get_account_summary(self, facade, alice):
        summary = facade.handle_query(GetAccountSummaryQuery(account_id=alice))
        assert summary is not None
        assert summary["owner_name"]   == "Alice"
        assert summary["account_type"] == "current"
        assert summary["balance"]      == 2_000.0

    def test_summary_tx_count_updates(self, facade, alice):
        facade.handle_command(DepositCommand(account_id=alice, amount=100.0))
        facade.handle_command(DepositCommand(account_id=alice, amount=200.0))
        summary = facade.handle_query(GetAccountSummaryQuery(account_id=alice))
        assert summary["tx_count"] == 3  # open + 2 deposits

    def test_list_accounts(self, facade, alice, bob):
        result = facade.handle_query(ListAccountsQuery())
        assert result["total"] == 2

    def test_list_accounts_filter_by_owner(self, facade, alice, bob):
        result = facade.handle_query(ListAccountsQuery(owner="Alice"))
        assert result["total"] == 1
        assert result["accounts"][0]["owner_name"] == "Alice"

    def test_list_accounts_filter_by_type(self, facade, alice, bob):
        result = facade.handle_query(ListAccountsQuery(actype="savings"))
        assert result["total"] == 1
        assert result["accounts"][0]["account_type"] == "savings"

    def test_list_accounts_pagination(self, facade):
        for i in range(10):
            facade.handle_command(OpenAccountCommand(
                account_id=f"ACC-{i:03d}",
                owner_name=f"User{i}",
                account_type="current",
                initial_deposit=100.0,
            ))
        page1 = facade.handle_query(ListAccountsQuery(page=1, page_size=3))
        page2 = facade.handle_query(ListAccountsQuery(page=2, page_size=3))
        assert len(page1["accounts"]) == 3
        assert len(page2["accounts"]) == 3
        assert page1["total"] == 10

    def test_get_transaction_history(self, facade, alice):
        facade.handle_command(DepositCommand(account_id=alice, amount=500.0, description="Salary"))
        facade.handle_command(WithdrawCommand(account_id=alice, amount=100.0, description="ATM"))
        history = facade.handle_query(GetTransactionHistoryQuery(account_id=alice))
        assert len(history) == 3  # open + deposit + withdrawal
        # Newest first
        assert history[0]["event_type"] == "Withdrawal"

    def test_history_balance_after_correct(self, facade, alice):
        facade.handle_command(DepositCommand(account_id=alice, amount=500.0))
        history = facade.handle_query(GetTransactionHistoryQuery(account_id=alice))
        assert history[0]["balance_after"] == 2_500.0


# ---------------------------------------------------------------------------
# ProjectionUpdater
# ---------------------------------------------------------------------------

class TestProjectionUpdater:

    def test_updater_creates_balance_on_open(self):
        store   = ReadModelStore()
        updater = ProjectionUpdater(store)
        event_store = InProcessEventStore()

        from bankcore.domain.domain_events import AccountOpened
        from bankcore.domain.value_objects import AccountId, Money
        event  = AccountOpened(
            aggregate_id=AccountId("ACC-001"),
            owner_name="Alice",
            account_type="current",
            initial_deposit=Money.eur(1_000.0),
        )
        stored = event_store.append(event)
        updater.apply(event, stored.aggregate_version)

        model = store.get_balance("ACC-001")
        assert model is not None
        assert model.balance == 1_000.0

    def test_updater_updates_balance_on_deposit(self):
        store   = ReadModelStore()
        updater = ProjectionUpdater(store)
        event_store = InProcessEventStore()

        from bankcore.domain.domain_events import AccountOpened, MoneyDeposited
        from bankcore.domain.value_objects import AccountId, Money

        e1 = AccountOpened(
            aggregate_id=AccountId("ACC-001"),
            owner_name="Alice",
            account_type="current",
            initial_deposit=Money.eur(500.0),
        )
        e2 = MoneyDeposited(
            aggregate_id=AccountId("ACC-001"),
            amount=Money.eur(300.0),
        )
        s1 = event_store.append(e1)
        s2 = event_store.append(e2)
        updater.apply(e1, s1.aggregate_version)
        updater.apply(e2, s2.aggregate_version)

        assert store.get_balance("ACC-001").balance == 800.0


# ---------------------------------------------------------------------------
# CQRS separation
# ---------------------------------------------------------------------------

class TestCQRSSeparation:

    def test_query_handler_has_no_event_store(self):
        """
        QueryHandler depends on ReadModelStore only — not EventStore.
        This is the fundamental CQRS separation.
        """
        read_store = ReadModelStore()
        handler    = AccountQueryHandler(read_store)
        # QueryHandler has no _event_store attribute
        assert not hasattr(handler, "_event_store")
        assert hasattr(handler, "_store")

    def test_command_handler_has_no_read_model(self):
        """CommandHandler writes to EventStore — not to Read Models directly."""
        event_store  = InProcessEventStore()
        read_store   = ReadModelStore()
        updater      = ProjectionUpdater(read_store)
        handler      = AccountCommandHandler(event_store, updater)
        # CommandHandler has no _read_store attribute (only access via updater)
        assert not hasattr(handler, "_read_store")

    def test_queries_reflect_command_results(self, facade, alice):
        """
        Eventual consistency: after command, query returns updated state.
        (Synchronous projection in Day 22 — async in production)
        """
        facade.handle_command(DepositCommand(account_id=alice, amount=750.0))
        balance = facade.handle_query(GetBalanceQuery(account_id=alice))
        assert balance == 2_750.0


# ---------------------------------------------------------------------------
# Full banking flow
# ---------------------------------------------------------------------------

class TestCQRSFullFlow:

    def test_complete_banking_scenario(self, facade, alice_id, bob_id):
        """
        Full CQRS flow:
        Commands → EventStore → Projections → Queries
        """
        # Commands (Write Side)
        facade.handle_command(OpenAccountCommand(
            alice_id, "Alice", "current", 5_000.0))
        facade.handle_command(OpenAccountCommand(
            bob_id, "Bob", "savings", 1_000.0, interest_rate=0.025))
        facade.handle_command(DepositCommand(alice_id, 3_000.0, "Salary"))
        facade.handle_command(TransferCommand(alice_id, bob_id, 1_000.0))
        facade.handle_command(ApplyInterestCommand(bob_id))

        # Queries (Read Side)
        alice_balance = facade.handle_query(GetBalanceQuery(alice_id))
        bob_balance   = facade.handle_query(GetBalanceQuery(bob_id))
        alice_summary = facade.handle_query(GetAccountSummaryQuery(alice_id))
        all_accounts  = facade.handle_query(ListAccountsQuery())
        bob_history   = facade.handle_query(GetTransactionHistoryQuery(bob_id))

        assert alice_balance == 7_000.0        # 5000 + 3000 - 1000
        assert bob_balance   == pytest.approx(2_050.0)  # (1000+1000)*1.025
        assert alice_summary["tx_count"] == 3  # open + salary + transfer
        assert all_accounts["total"] == 2
        assert len(bob_history) == 3           # open + transfer-in + interest

    def test_event_store_has_all_events(self, facade, alice_id, bob_id):
        """EventStore is the source of truth — all events are stored."""
        facade.handle_command(OpenAccountCommand(alice_id, "Alice", "current", 1_000.0))
        facade.handle_command(DepositCommand(alice_id, 500.0))
        facade.handle_command(WithdrawCommand(alice_id, 200.0))

        events = facade.event_store.get_events(alice_id)
        assert len(events) == 3

        event_types = [e.event_type for e in events]
        assert "AccountOpened"  in event_types
        assert "MoneyDeposited" in event_types
        assert "MoneyWithdrawn" in event_types
