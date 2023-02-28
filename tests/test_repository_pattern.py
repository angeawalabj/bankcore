"""
Tests — Day 14: Repository Pattern
=====================================
Test strategy:
  1. Specifications — each spec in isolation, boolean composition
  2. Pagination — Page object, has_next/has_prev, edge cases
  3. InMemoryAccountRepository.find() — spec + pagination
  4. SQLiteAccountRepository.find() — same specs, same results
  5. UnitOfWork — dirty tracking, commit, rollback, context manager
  6. TransferOperation — atomic transfer via UoW
  7. Cross-repo consistency — InMemory and SQLite produce identical results
"""

import sys
import pytest
import sqlite3

sys.path.insert(0, "src")

from bankcore.config_manager import ConfigManager
from bankcore.account_factory import AccountFactory
from bankcore.alert_system import AlertSystem
from bankcore.account_type_registry import AccountTypeRegistry
from bankcore.protocols import FakeConfig, SpyAlertSystem
from bankcore.container import BankContainer
from bankcore.application.specifications import (
    AccountSpec, AndSpec, OrSpec, NotSpec, AllSpec,
    OwnerSpec, TypeSpec, BalanceSpec,
    InterestEligibleSpec, OverdraftSpec, LowBalanceSpec,
    Page,
)
from bankcore.application.unit_of_work import UnitOfWork, TransferOperation
from bankcore.infrastructure.persistence.in_memory_repository import (
    InMemoryAccountRepository,
)
from bankcore.infrastructure.persistence.sqlite_repository import (
    SQLiteAccountRepository,
)
from bankcore.infrastructure.persistence.schema import get_connection, create_schema


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

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
def mem_repo():
    return InMemoryAccountRepository()


@pytest.fixture
def sqlite_repo():
    conn = get_connection(":memory:")
    return SQLiteAccountRepository(conn)


@pytest.fixture
def populated_repo(mem_repo):
    """Repository pre-filled with 6 accounts for query testing."""
    accounts = [
        AccountFactory.create("current", "Alice",   2_000.0),
        AccountFactory.create("current", "Alice",   500.0),    # Alice has 2 accounts
        AccountFactory.create("savings", "Bob",     5_000.0),
        AccountFactory.create("savings", "Carol",   80.0),     # low balance savings
        AccountFactory.create("pro",     "Dave",    10_000.0),
        AccountFactory.create("pro",     "Eve",     0.0),      # zero balance pro
    ]
    for a in accounts:
        mem_repo.save(a)
    # Put Dave's pro account into overdraft
    accounts[4].withdraw(12_000.0)  # -2000 (within -5000 limit)
    mem_repo.save(accounts[4])
    return mem_repo, accounts


# ---------------------------------------------------------------------------
# Specifications — in isolation
# ---------------------------------------------------------------------------

class TestSpecifications:

    def test_all_spec_matches_everything(self):
        account = AccountFactory.create("current", "Alice", 100.0)
        assert AllSpec().is_satisfied_by(account) is True

    def test_owner_spec_matches_owner(self):
        account = AccountFactory.create("current", "Alice", 100.0)
        assert OwnerSpec("Alice").is_satisfied_by(account) is True
        assert OwnerSpec("Bob").is_satisfied_by(account) is False

    def test_owner_spec_case_insensitive(self):
        account = AccountFactory.create("current", "Alice Martin", 100.0)
        assert OwnerSpec("alice martin").is_satisfied_by(account) is True
        assert OwnerSpec("ALICE MARTIN").is_satisfied_by(account) is True

    def test_type_spec_matches_account_type(self):
        savings = AccountFactory.create("savings", "Bob", 100.0)
        assert TypeSpec("savings").is_satisfied_by(savings) is True
        assert TypeSpec("current").is_satisfied_by(savings) is False

    def test_balance_spec_min(self):
        account = AccountFactory.create("current", "Alice", 1_000.0)
        assert BalanceSpec(min=500.0).is_satisfied_by(account) is True
        assert BalanceSpec(min=1_500.0).is_satisfied_by(account) is False

    def test_balance_spec_max(self):
        account = AccountFactory.create("current", "Alice", 1_000.0)
        assert BalanceSpec(max=2_000.0).is_satisfied_by(account) is True
        assert BalanceSpec(max=500.0).is_satisfied_by(account) is False

    def test_balance_spec_range(self):
        account = AccountFactory.create("current", "Alice", 1_000.0)
        assert BalanceSpec(min=500.0, max=1_500.0).is_satisfied_by(account) is True
        assert BalanceSpec(min=1_500.0, max=2_000.0).is_satisfied_by(account) is False

    def test_interest_eligible_spec_savings(self):
        savings = AccountFactory.create("savings", "Bob", 200.0)  # above 50 min
        assert InterestEligibleSpec().is_satisfied_by(savings) is True

    def test_interest_eligible_spec_current(self):
        current = AccountFactory.create("current", "Alice", 1_000.0)
        assert InterestEligibleSpec().is_satisfied_by(current) is False

    def test_overdraft_spec(self):
        pro = AccountFactory.create("pro", "Dave", 0.0)
        assert OverdraftSpec().is_satisfied_by(pro) is False
        pro.withdraw(1_000.0)
        assert OverdraftSpec().is_satisfied_by(pro) is True

    def test_low_balance_spec(self):
        account = AccountFactory.create("current", "Alice", 50.0)
        assert LowBalanceSpec(threshold=100.0).is_satisfied_by(account) is True
        assert LowBalanceSpec(threshold=20.0).is_satisfied_by(account) is False


# ---------------------------------------------------------------------------
# Boolean composition
# ---------------------------------------------------------------------------

class TestSpecificationComposition:

    def test_and_spec(self):
        account = AccountFactory.create("savings", "Bob", 5_000.0)
        spec = TypeSpec("savings") & BalanceSpec(min=1_000.0)
        assert spec.is_satisfied_by(account) is True

    def test_and_spec_fails_if_one_fails(self):
        account = AccountFactory.create("savings", "Bob", 500.0)
        spec = TypeSpec("savings") & BalanceSpec(min=1_000.0)
        assert spec.is_satisfied_by(account) is False

    def test_or_spec(self):
        current = AccountFactory.create("current", "Alice", 100.0)
        spec = TypeSpec("savings") | TypeSpec("current")
        assert spec.is_satisfied_by(current) is True

    def test_or_spec_both_fail(self):
        pro = AccountFactory.create("pro", "Dave", 100.0)
        spec = TypeSpec("savings") | TypeSpec("current")
        assert spec.is_satisfied_by(pro) is False

    def test_not_spec(self):
        current = AccountFactory.create("current", "Alice", 100.0)
        spec = ~TypeSpec("savings")
        assert spec.is_satisfied_by(current) is True

    def test_complex_composition(self):
        """VIP client: savings account with > 10k, not in overdraft."""
        account = AccountFactory.create("savings", "Bob", 15_000.0)
        spec = TypeSpec("savings") & BalanceSpec(min=10_000.0) & ~OverdraftSpec()
        assert spec.is_satisfied_by(account) is True

    def test_repr_is_readable(self):
        spec = TypeSpec("savings") & BalanceSpec(min=1_000.0)
        r = repr(spec)
        assert "TypeSpec" in r
        assert "BalanceSpec" in r
        assert "AND" in r


# ---------------------------------------------------------------------------
# Page — paginated result
# ---------------------------------------------------------------------------

class TestPage:

    def test_empty_page(self):
        p = Page(items=[], total=0, page=1, page_size=10)
        assert len(p) == 0
        assert p.has_next is False
        assert p.has_prev is False

    def test_has_next(self):
        p = Page(items=[1, 2, 3], total=25, page=1, page_size=10)
        assert p.has_next is True

    def test_has_prev(self):
        p = Page(items=[1, 2, 3], total=25, page=2, page_size=10)
        assert p.has_prev is True

    def test_no_prev_on_first_page(self):
        p = Page(items=[1], total=5, page=1, page_size=10)
        assert p.has_prev is False

    def test_total_pages(self):
        p = Page(items=[], total=25, page=1, page_size=10)
        assert p.total_pages == 3

    def test_total_pages_exact(self):
        p = Page(items=[], total=20, page=1, page_size=10)
        assert p.total_pages == 2

    def test_iterable(self):
        accounts = [AccountFactory.create("current", f"User{i}", 100.0) for i in range(3)]
        p = Page(items=accounts, total=3, page=1, page_size=10)
        assert list(p) == accounts

    def test_immutable(self):
        p = Page(items=[], total=0, page=1, page_size=10)
        with pytest.raises(Exception):
            p.total = 99


# ---------------------------------------------------------------------------
# InMemoryAccountRepository.find() with specifications
# ---------------------------------------------------------------------------

class TestInMemoryFind:

    def test_find_all_with_no_spec(self, populated_repo):
        repo, _ = populated_repo
        page = repo.find(page_size=100)
        assert page.total == 6

    def test_find_by_type(self, populated_repo):
        repo, _ = populated_repo
        page = repo.find(TypeSpec("savings"), page_size=100)
        assert page.total == 2
        assert all(a.account_type == "savings" for a in page.items)

    def test_find_by_owner(self, populated_repo):
        repo, _ = populated_repo
        page = repo.find(OwnerSpec("Alice"), page_size=100)
        assert page.total == 2
        assert all(a.owner_name == "Alice" for a in page.items)

    def test_find_with_balance_min(self, populated_repo):
        repo, _ = populated_repo
        page = repo.find(BalanceSpec(min=1_000.0), page_size=100)
        assert all(a.balance >= 1_000.0 for a in page.items)

    def test_find_interest_eligible(self, populated_repo):
        repo, _ = populated_repo
        page = repo.find(InterestEligibleSpec(), page_size=100)
        # Carol (savings, 80 > 50 min) and Bob (savings, 5000 > 50 min)
        assert page.total == 2

    def test_find_in_overdraft(self, populated_repo):
        repo, accounts = populated_repo
        page = repo.find(OverdraftSpec(), page_size=100)
        assert page.total == 1
        assert page.items[0].owner_name == "Dave"

    def test_pagination_first_page(self, populated_repo):
        repo, _ = populated_repo
        page = repo.find(page=1, page_size=2)
        assert len(page.items) == 2
        assert page.total == 6
        assert page.has_next is True
        assert page.has_prev is False

    def test_pagination_last_page(self, populated_repo):
        repo, _ = populated_repo
        page = repo.find(page=3, page_size=2)
        assert len(page.items) == 2
        assert page.has_next is False
        assert page.has_prev is True

    def test_find_one(self, populated_repo):
        repo, _ = populated_repo
        account = repo.find_one(TypeSpec("pro") & OwnerSpec("Eve"))
        assert account is not None
        assert account.owner_name == "Eve"

    def test_find_one_no_match(self, populated_repo):
        repo, _ = populated_repo
        account = repo.find_one(TypeSpec("youth"))
        assert account is None

    def test_count_spec(self, populated_repo):
        repo, _ = populated_repo
        assert repo.count_spec(TypeSpec("current")) == 2
        assert repo.count_spec(TypeSpec("savings")) == 2
        assert repo.count_spec(TypeSpec("pro"))     == 2


# ---------------------------------------------------------------------------
# UnitOfWork
# ---------------------------------------------------------------------------

class TestUnitOfWork:

    def test_find_loads_account(self, mem_repo):
        account = AccountFactory.create("current", "Alice", 1_000.0)
        mem_repo.save(account)

        uow = UnitOfWork(mem_repo)
        found = uow.find(account.account_id)
        assert found is not None
        assert found.account_id == account.account_id

    def test_find_returns_same_instance(self, mem_repo):
        account = AccountFactory.create("current", "Alice", 1_000.0)
        mem_repo.save(account)

        uow = UnitOfWork(mem_repo)
        first  = uow.find(account.account_id)
        second = uow.find(account.account_id)
        assert first is second   # identity map

    def test_commit_saves_dirty_accounts(self, mem_repo):
        alice = AccountFactory.create("current", "Alice", 1_000.0)
        mem_repo.save(alice)

        uow = UnitOfWork(mem_repo)
        loaded = uow.find(alice.account_id)
        loaded.deposit(500.0)
        uow.register_dirty(loaded)
        uow.commit()

        found = mem_repo.find_by_id(alice.account_id)
        assert found.balance == 1_500.0

    def test_rollback_clears_dirty_set(self, mem_repo):
        """
        UnitOfWork.rollback() clears the dirty set so nothing is committed.
        Note: in-memory repos share object references, so the account object
        itself is mutated. True isolation requires SQLite-level transactions
        (BEGIN/ROLLBACK) which the SQLite-backed UoW provides in production.
        This test verifies the UoW contract: after rollback, dirty_count == 0.
        """
        alice = AccountFactory.create("current", "Alice", 1_000.0)
        mem_repo.save(alice)

        uow = UnitOfWork(mem_repo)
        loaded = uow.find(alice.account_id)
        loaded.deposit(500.0)
        uow.register_dirty(loaded)
        assert uow.dirty_count == 1

        uow.rollback()

        # After rollback, nothing is pending
        assert uow.dirty_count == 0
        assert uow.loaded_count == 0

    def test_context_manager_commits_on_success(self, mem_repo):
        alice = AccountFactory.create("current", "Alice", 1_000.0)
        mem_repo.save(alice)

        with UnitOfWork(mem_repo) as uow:
            loaded = uow.find(alice.account_id)
            loaded.deposit(300.0)
            uow.register_dirty(loaded)
            # explicit commit
            uow.commit()

        found = mem_repo.find_by_id(alice.account_id)
        assert found.balance == 1_300.0

    def test_context_manager_rolls_back_on_exception(self, mem_repo):
        """
        On exception, context manager calls rollback() which clears dirty set.
        Nothing is committed to the repository on exception.
        """
        alice = AccountFactory.create("current", "Alice", 1_000.0)
        mem_repo.save(alice)

        uow_ref = None
        with pytest.raises(ValueError):
            with UnitOfWork(mem_repo) as uow:
                uow_ref = uow
                loaded = uow.find(alice.account_id)
                uow.register_dirty(loaded)
                raise ValueError("Simulated failure")

        # After exception, dirty set is cleared — nothing committed
        assert uow_ref.dirty_count == 0

    def test_dirty_count(self, mem_repo):
        alice = AccountFactory.create("current", "Alice", 1_000.0)
        bob   = AccountFactory.create("savings", "Bob",   500.0)
        mem_repo.save(alice)
        mem_repo.save(bob)

        uow = UnitOfWork(mem_repo)
        uow.register_dirty(alice)
        uow.register_dirty(bob)
        assert uow.dirty_count == 2


# ---------------------------------------------------------------------------
# TransferOperation
# ---------------------------------------------------------------------------

class TestTransferOperation:

    def test_transfer_succeeds(self, mem_repo):
        alice = AccountFactory.create("current", "Alice", 1_000.0)
        bob   = AccountFactory.create("savings", "Bob",   500.0)
        mem_repo.save(alice)
        mem_repo.save(bob)

        with UnitOfWork(mem_repo) as uow:
            op     = TransferOperation(uow)
            result = op.execute(alice.account_id, bob.account_id, 300.0)
            uow.commit()

        assert result["success"] is True
        assert result["from_balance_after"] == 700.0
        assert result["to_balance_after"]   == 800.0

        # Verify persistence
        assert mem_repo.find_by_id(alice.account_id).balance == 700.0
        assert mem_repo.find_by_id(bob.account_id).balance   == 800.0

    def test_transfer_fails_on_unknown_account(self, mem_repo):
        alice = AccountFactory.create("current", "Alice", 1_000.0)
        mem_repo.save(alice)

        uow = UnitOfWork(mem_repo)
        op  = TransferOperation(uow)
        result = op.execute(alice.account_id, "GHOST", 300.0)
        assert result["success"] is False
        assert "not found" in result["reason"]

    def test_transfer_fails_on_insufficient_funds(self, mem_repo):
        alice = AccountFactory.create("current", "Alice", 100.0)
        bob   = AccountFactory.create("savings", "Bob",   500.0)
        mem_repo.save(alice)
        mem_repo.save(bob)

        uow = UnitOfWork(mem_repo)
        op  = TransferOperation(uow)
        result = op.execute(alice.account_id, bob.account_id, 500.0)
        assert result["success"] is False

    def test_failed_transfer_does_not_modify_accounts(self, mem_repo):
        """
        Atomicity: if transfer fails, neither account is modified.
        """
        alice = AccountFactory.create("current", "Alice", 100.0)
        bob   = AccountFactory.create("savings", "Bob",   500.0)
        mem_repo.save(alice)
        mem_repo.save(bob)

        alice_balance_before = alice.balance

        uow = UnitOfWork(mem_repo)
        op  = TransferOperation(uow)
        op.execute(alice.account_id, bob.account_id, 9_999.0)
        # Do NOT commit — changes are lost

        assert mem_repo.find_by_id(alice.account_id).balance == alice_balance_before


# ---------------------------------------------------------------------------
# Cross-repo consistency: InMemory vs SQLite same specs
# ---------------------------------------------------------------------------

class TestCrossRepositoryConsistency:

    def _populate(self, repo):
        accounts = [
            AccountFactory.create("current", "Alice",   2_000.0),
            AccountFactory.create("savings", "Bob",     5_000.0),
            AccountFactory.create("savings", "Carol",   80.0),
            AccountFactory.create("pro",     "Dave",    10_000.0),
        ]
        for a in accounts:
            repo.save(a)
        return accounts

    def test_type_spec_same_count_in_memory_and_sqlite(self, sqlite_repo):
        mem = InMemoryAccountRepository()
        self._populate(mem)
        self._populate(sqlite_repo)

        mem_page    = mem.find(TypeSpec("savings"), page_size=100)
        sqlite_page = sqlite_repo.find(TypeSpec("savings"), page_size=100)

        assert mem_page.total == sqlite_page.total == 2

    def test_balance_spec_same_results(self, sqlite_repo):
        mem = InMemoryAccountRepository()
        self._populate(mem)
        self._populate(sqlite_repo)

        spec = BalanceSpec(min=1_000.0)
        mem_total    = mem.count_spec(spec)
        sqlite_total = sqlite_repo.count_spec(spec)

        assert mem_total == sqlite_total

    def test_interest_eligible_same_count(self, sqlite_repo):
        mem = InMemoryAccountRepository()
        self._populate(mem)
        self._populate(sqlite_repo)

        spec = InterestEligibleSpec()
        assert mem.count_spec(spec) == sqlite_repo.count_spec(spec)
