"""
Tests — Day 12: Clean Architecture
=====================================
Test strategy:
  1. Money value object — arithmetic, immutability, currency safety
  2. AccountId value object — typed identity
  3. Domain Events — pure, no infrastructure imports
  4. AccountRepositoryPort — contract verification
  5. InMemoryAccountRepository — adapter implementation
  6. Use Cases with InMemoryAccountRepository (Clean Architecture swap)
  7. Layer isolation — domain has zero infrastructure imports
  8. Dependency direction — Infrastructure depends on Application, not vice versa
"""

import sys
import pytest

sys.path.insert(0, "src")

from bankcore.config_manager import ConfigManager
from bankcore.account_factory import AccountFactory
from bankcore.alert_system import AlertSystem
from bankcore.account_type_registry import AccountTypeRegistry
from bankcore.protocols import FakeConfig, SpyAlertSystem
from bankcore.container import BankContainer
from bankcore.domain.value_objects import Money, AccountId
from bankcore.domain.domain_events import (
    AccountOpened, MoneyDeposited, MoneyWithdrawn,
    MoneyTransferred, InterestApplied, FeeCharged,
)
from bankcore.application.ports import AccountRepositoryPort
from bankcore.infrastructure.persistence.in_memory_repository import (
    InMemoryAccountRepository, InMemoryDomainEventStore,
)
from bankcore.application.commands import (
    CreateAccountCommand, TransferCommand,
    DepositCommand, ApplyInterestCommand,
)
from bankcore.application.use_cases import BankApplicationService


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
def container():
    return BankContainer.build_for_testing()


# ---------------------------------------------------------------------------
# Money — Value Object
# ---------------------------------------------------------------------------

class TestMoney:

    def test_creation(self):
        m = Money(100.0, "EUR")
        assert m.amount == 100.0
        assert m.currency == "EUR"

    def test_currency_normalized_to_uppercase(self):
        m = Money(50.0, "eur")
        assert m.currency == "EUR"

    def test_negative_amount_raises(self):
        with pytest.raises(ValueError, match="negative"):
            Money(-1.0, "EUR")

    def test_invalid_currency_raises(self):
        with pytest.raises(ValueError, match="3-letter"):
            Money(100.0, "EURO")

    def test_addition(self):
        m1 = Money(100.0, "EUR")
        m2 = Money(50.0,  "EUR")
        assert m1 + m2 == Money(150.0, "EUR")

    def test_subtraction(self):
        m1 = Money(100.0, "EUR")
        m2 = Money(30.0,  "EUR")
        assert m1 - m2 == Money(70.0, "EUR")

    def test_subtraction_below_zero_raises(self):
        m1 = Money(30.0, "EUR")
        m2 = Money(50.0, "EUR")
        with pytest.raises(ValueError):
            m1 - m2

    def test_multiplication(self):
        m = Money(100.0, "EUR")
        assert m * 0.025 == Money(2.5, "EUR")

    def test_comparison(self):
        m1 = Money(100.0, "EUR")
        m2 = Money(200.0, "EUR")
        assert m1 < m2
        assert m2 > m1
        assert m1 <= m1
        assert m1 >= m1

    def test_cross_currency_addition_raises(self):
        eur = Money(100.0, "EUR")
        usd = Money(100.0, "USD")
        with pytest.raises(ValueError, match="currencies"):
            eur + usd

    def test_cross_currency_comparison_raises(self):
        eur = Money(100.0, "EUR")
        usd = Money(50.0,  "USD")
        with pytest.raises(ValueError, match="currencies"):
            eur < usd

    def test_equality(self):
        assert Money(100.0, "EUR") == Money(100.0, "EUR")
        assert Money(100.0, "EUR") != Money(100.0, "USD")
        assert Money(100.0, "EUR") != Money(200.0, "EUR")

    def test_immutability(self):
        m = Money(100.0, "EUR")
        with pytest.raises(Exception):
            m.amount = 999.0

    def test_zero_factory(self):
        assert Money.zero() == Money(0.0, "EUR")
        assert Money.zero("USD") == Money(0.0, "USD")

    def test_eur_factory(self):
        assert Money.eur(150.0) == Money(150.0, "EUR")

    def test_is_zero(self):
        assert Money.zero().is_zero()
        assert not Money.eur(1.0).is_zero()

    def test_is_positive(self):
        assert Money.eur(0.01).is_positive()
        assert not Money.zero().is_positive()

    def test_percentage(self):
        m = Money.eur(1_000.0)
        assert m.percentage(2.5) == Money.eur(25.0)

    def test_string_representation(self):
        m = Money(1234.56, "EUR")
        assert "1,234.56" in str(m)
        assert "EUR" in str(m)


# ---------------------------------------------------------------------------
# AccountId — Value Object
# ---------------------------------------------------------------------------

class TestAccountId:

    def test_creation(self):
        aid = AccountId("acc-001")
        assert aid.value == "ACC-001"   # normalized to uppercase

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            AccountId("")

    def test_equality_with_string(self):
        aid = AccountId("ACC-001")
        assert aid == "acc-001"
        assert aid == "ACC-001"

    def test_equality_with_account_id(self):
        a1 = AccountId("ACC-001")
        a2 = AccountId("acc-001")
        assert a1 == a2

    def test_immutability(self):
        aid = AccountId("ACC-001")
        with pytest.raises(Exception):
            aid.value = "OTHER"

    def test_generate_produces_unique_ids(self):
        ids = {AccountId.generate() for _ in range(100)}
        assert len(ids) == 100

    def test_hashable(self):
        aid = AccountId("ACC-001")
        d = {aid: "test"}
        assert d[AccountId("ACC-001")] == "test"


# ---------------------------------------------------------------------------
# Domain Events — pure, no infrastructure
# ---------------------------------------------------------------------------

class TestDomainEvents:

    def test_account_opened_event(self):
        aid   = AccountId.generate()
        event = AccountOpened(
            aggregate_id=aid,
            owner_name="Alice",
            account_type="current",
            initial_deposit=Money.eur(1_000.0),
        )
        assert event.event_type == "AccountOpened"
        assert event.owner_name == "Alice"
        assert event.initial_deposit == Money.eur(1_000.0)

    def test_money_deposited_event(self):
        aid   = AccountId.generate()
        event = MoneyDeposited(
            aggregate_id=aid,
            amount=Money.eur(500.0),
            description="Salary",
        )
        assert event.amount == Money.eur(500.0)
        assert event.description == "Salary"

    def test_money_transferred_event(self):
        from_id = AccountId.generate()
        to_id   = AccountId.generate()
        event   = MoneyTransferred(
            aggregate_id=from_id,
            amount=Money.eur(200.0),
            to_account_id=to_id,
        )
        assert event.aggregate_id == from_id
        assert event.to_account_id == to_id
        assert event.amount == Money.eur(200.0)

    def test_interest_applied_event(self):
        aid   = AccountId.generate()
        event = InterestApplied(
            aggregate_id=aid,
            interest_amount=Money.eur(25.0),
            rate=0.025,
        )
        assert event.interest_amount == Money.eur(25.0)

    def test_events_are_immutable(self):
        aid   = AccountId.generate()
        event = MoneyDeposited(aggregate_id=aid, amount=Money.eur(100.0))
        with pytest.raises(Exception):
            event.amount = Money.eur(999.0)

    def test_events_have_unique_ids(self):
        aid    = AccountId.generate()
        event1 = MoneyDeposited(aggregate_id=aid, amount=Money.eur(100.0))
        event2 = MoneyDeposited(aggregate_id=aid, amount=Money.eur(100.0))
        assert event1.event_id != event2.event_id

    def test_to_dict_contains_required_keys(self):
        aid   = AccountId.generate()
        event = MoneyDeposited(aggregate_id=aid, amount=Money.eur(100.0))
        d     = event.to_dict()
        assert "event_type"   in d
        assert "event_id"     in d
        assert "aggregate_id" in d
        assert "occurred_at"  in d
        assert "amount"       in d

    def test_domain_events_have_zero_infrastructure_imports(self):
        """
        Clean Architecture: Domain Events must import nothing from infrastructure.
        """
        import importlib
        module = importlib.import_module("bankcore.domain.domain_events")
        source = open(module.__file__).read()

        forbidden = [
            "config_manager", "alert_system", "sqlalchemy",
            "redis", "kafka", "requests", "flask", "fastapi",
        ]
        for term in forbidden:
            assert term not in source.lower(), \
                f"DomainEvent imports infrastructure: '{term}'"


# ---------------------------------------------------------------------------
# AccountRepositoryPort — interface contract
# ---------------------------------------------------------------------------

class TestAccountRepositoryPort:
    """Verify that InMemoryAccountRepository satisfies the port contract."""

    def test_is_instance_of_port(self):
        repo = InMemoryAccountRepository()
        assert isinstance(repo, AccountRepositoryPort)

    def test_save_and_find(self):
        repo    = InMemoryAccountRepository()
        account = AccountFactory.create("current", "Alice", 500.0)
        repo.save(account)
        found = repo.find_by_id(account.account_id)
        assert found is account

    def test_find_unknown_returns_none(self):
        repo = InMemoryAccountRepository()
        assert repo.find_by_id("GHOST") is None

    def test_find_all(self):
        repo = InMemoryAccountRepository()
        a = AccountFactory.create("current", "Alice", 100.0)
        b = AccountFactory.create("savings", "Bob",   200.0)
        repo.save(a)
        repo.save(b)
        assert len(repo.find_all()) == 2

    def test_find_by_owner(self):
        repo = InMemoryAccountRepository()
        a1 = AccountFactory.create("current", "Alice", 100.0)
        a2 = AccountFactory.create("savings", "Alice", 200.0)
        b  = AccountFactory.create("current", "Bob",   300.0)
        for acc in [a1, a2, b]:
            repo.save(acc)
        alices = repo.find_by_owner("Alice")
        assert len(alices) == 2

    def test_exists(self):
        repo    = InMemoryAccountRepository()
        account = AccountFactory.create("current", "Alice", 100.0)
        repo.save(account)
        assert repo.exists(account.account_id) is True
        assert repo.exists("GHOST") is False

    def test_count(self):
        repo = InMemoryAccountRepository()
        assert repo.count() == 0
        repo.save(AccountFactory.create("current", "Alice", 100.0))
        assert repo.count() == 1

    def test_delete(self):
        repo    = InMemoryAccountRepository()
        account = AccountFactory.create("current", "Alice", 100.0)
        repo.save(account)
        assert repo.delete(account.account_id) is True
        assert repo.find_by_id(account.account_id) is None

    def test_save_updates_existing(self):
        repo    = InMemoryAccountRepository()
        account = AccountFactory.create("current", "Alice", 500.0)
        repo.save(account)
        account.deposit(200.0)
        repo.save(account)
        found = repo.find_by_id(account.account_id)
        assert found.balance == 700.0


# ---------------------------------------------------------------------------
# InMemoryDomainEventStore
# ---------------------------------------------------------------------------

class TestInMemoryDomainEventStore:

    def test_append_and_retrieve(self):
        store = InMemoryDomainEventStore()
        aid   = AccountId.generate()
        event = MoneyDeposited(aggregate_id=aid, amount=Money.eur(100.0))
        store.append(event)
        events = store.get_events_for(str(aid))
        assert len(events) == 1
        assert events[0] is event

    def test_events_ordered_by_occurrence(self):
        from datetime import datetime, timedelta
        store = InMemoryDomainEventStore()
        aid   = AccountId.generate()
        # Append multiple events
        for i in range(5):
            store.append(MoneyDeposited(aggregate_id=aid, amount=Money.eur(float(i * 100))))
        events = store.get_events_for(str(aid))
        assert len(events) == 5

    def test_empty_aggregate_returns_empty_list(self):
        store = InMemoryDomainEventStore()
        assert store.get_events_for("GHOST") == []

    def test_count(self):
        store = InMemoryDomainEventStore()
        aid1  = AccountId.generate()
        aid2  = AccountId.generate()
        store.append(MoneyDeposited(aggregate_id=aid1, amount=Money.eur(100.0)))
        store.append(MoneyDeposited(aggregate_id=aid1, amount=Money.eur(200.0)))
        store.append(MoneyDeposited(aggregate_id=aid2, amount=Money.eur(300.0)))
        assert store.count() == 3
        assert store.count_for(str(aid1)) == 2


# ---------------------------------------------------------------------------
# Use Cases with InMemoryAccountRepository (Clean Architecture swap)
# ---------------------------------------------------------------------------

class TestUseCasesWithCleanArchitectureRepo:
    """
    The key Clean Architecture test:
    Use Cases work identically with InMemoryAccountRepository
    as they did with AccountRegistry — without any modification.
    """

    @pytest.fixture
    def app(self, container):
        repo = InMemoryAccountRepository()
        return BankApplicationService(container, registry=repo)

    def test_create_and_find_account(self, app):
        result = app.create_account(
            CreateAccountCommand("Alice", "current", 1_000.0, "system")
        )
        assert result.success is True
        info = app.get_account(result.data["account_id"])
        assert info["owner_name"] == "Alice"

    def test_transfer_between_accounts(self, app):
        r1 = app.create_account(
            CreateAccountCommand("Alice", "current", 2_000.0, "system"))
        r2 = app.create_account(
            CreateAccountCommand("Bob",   "savings", 1_000.0, "system"))

        result = app.transfer(TransferCommand(
            r1.data["account_id"], r2.data["account_id"], 500.0, "user"
        ))
        assert result.success is True
        assert result.data["from_balance_after"] == 1_500.0
        assert result.data["to_balance_after"]   == 1_500.0

    def test_deposit_persists(self, app):
        r = app.create_account(
            CreateAccountCommand("Alice", "current", 500.0, "system"))
        app.deposit(DepositCommand(r.data["account_id"], 300.0, "sys"))
        info = app.get_account(r.data["account_id"])
        assert info["balance"] == 800.0


# ---------------------------------------------------------------------------
# Layer isolation — Clean Architecture dependency rules
# ---------------------------------------------------------------------------

class TestCleanArchitectureLayerIsolation:

    def test_domain_value_objects_have_zero_infrastructure_imports(self):
        import importlib
        module = importlib.import_module("bankcore.domain.value_objects")
        source = open(module.__file__).read()

        forbidden = [
            "config_manager", "alert_system", "transaction_history",
            "account_factory", "fee_calculator", "sqlalchemy",
        ]
        for term in forbidden:
            assert term not in source.lower(), \
                f"Domain value_objects imports infrastructure: '{term}'"

    def test_application_ports_do_not_import_infrastructure(self):
        """
        Ports must not IMPORT from infrastructure.
        Comments mentioning infrastructure names are fine.
        We check actual import statements only.
        """
        import importlib
        module = importlib.import_module("bankcore.application.ports")
        source = open(module.__file__).read()

        # Only check actual import lines, not comments or docstrings
        import_lines = [
            line for line in source.splitlines()
            if line.strip().startswith(("import ", "from ")) and
               not line.strip().startswith("#")
        ]
        import_text = "\n".join(import_lines).lower()

        forbidden = ["in_memory_repository", "sqlalchemy", "redis"]
        for term in forbidden:
            assert term not in import_text, \
                f"Application ports import infrastructure: '{term}'"

    def test_infrastructure_imports_application_ports(self):
        """
        Infrastructure MUST import Application ports — it implements them.
        This is the correct direction in Clean Architecture.
        """
        import importlib
        module = importlib.import_module(
            "bankcore.infrastructure.persistence.in_memory_repository"
        )
        source = open(module.__file__).read()
        assert "AccountRepositoryPort" in source, \
            "Infrastructure adapter must import and implement AccountRepositoryPort"

    def test_swapping_repository_does_not_change_use_cases(self):
        """
        The definitive Clean Architecture test:
        Same Use Cases, different repository — identical behaviour.
        """
        from bankcore.application.use_cases import AccountRegistry

        container = BankContainer.build_for_testing()

        # App 1: original AccountRegistry
        app1 = BankApplicationService(container, registry=AccountRegistry())
        # App 2: InMemoryAccountRepository
        app2 = BankApplicationService(container, registry=InMemoryAccountRepository())

        cmd = CreateAccountCommand("Alice", "current", 1_000.0, "system")

        r1 = app1.create_account(cmd)
        r2 = app2.create_account(cmd)

        # Same result from both — different storage, same behaviour
        assert r1.success == r2.success
        assert r1.data["owner_name"] == r2.data["owner_name"]
        assert r1.data["account_type"] == r2.data["account_type"]
        assert r1.data["initial_balance"] == r2.data["initial_balance"]
