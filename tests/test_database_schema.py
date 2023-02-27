"""
Tests — Day 13: Database Schema & SQLiteAccountRepository
===========================================================
Test strategy:
  1. Schema structure — all tables, columns, constraints exist
  2. Schema indexes — performance indexes present
  3. Referential integrity — foreign keys enforced
  4. Business rule constraints — CHECK constraints enforced
  5. Transaction immutability — append-only behaviour
  6. SQLiteAccountRepository — full port contract
  7. Clean Architecture swap — SQLite behaves like InMemory
  8. Reporting queries — history and summary
"""

import sys
import sqlite3
import pytest

sys.path.insert(0, "src")

from bankcore.config_manager import ConfigManager
from bankcore.account_factory import AccountFactory
from bankcore.alert_system import AlertSystem
from bankcore.account_type_registry import AccountTypeRegistry
from bankcore.infrastructure.persistence.schema import (
    create_schema, get_connection, schema_connection, SchemaInspector,
    SCHEMA_SQL,
)
from bankcore.infrastructure.persistence.sqlite_repository import (
    SQLiteAccountRepository,
)
from bankcore.infrastructure.persistence.in_memory_repository import (
    InMemoryAccountRepository,
)
from bankcore.application.ports import AccountRepositoryPort
from bankcore.protocols import FakeConfig, SpyAlertSystem
from bankcore.container import BankContainer
from bankcore.application.commands import (
    CreateAccountCommand, TransferCommand, DepositCommand,
)
from bankcore.application.use_cases import BankApplicationService


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
def conn():
    """Fresh in-memory SQLite connection with schema for each test."""
    c = get_connection(":memory:")
    create_schema(c)
    yield c
    c.close()


@pytest.fixture
def inspector(conn):
    return SchemaInspector(conn)


@pytest.fixture
def repo(conn):
    return SQLiteAccountRepository(conn)


@pytest.fixture
def container():
    return BankContainer.build_for_testing()


# ---------------------------------------------------------------------------
# Schema structure — tables exist
# ---------------------------------------------------------------------------

class TestSchemaStructure:

    def test_all_required_tables_exist(self, inspector):
        tables = inspector.tables()
        for expected in ["owner", "account", "transaction", "transfer", "fee_record"]:
            assert expected in tables, f"Missing table: {expected}"

    def test_owner_table_columns(self, inspector):
        cols = inspector.column_names("owner")
        for expected in ["owner_id", "full_name", "email", "created_at"]:
            assert expected in cols, f"Missing column in owner: {expected}"

    def test_account_table_columns(self, inspector):
        cols = inspector.column_names("account")
        for expected in [
            "account_id", "owner_id", "account_type", "balance",
            "min_possible_balance", "status", "created_at", "updated_at",
        ]:
            assert expected in cols, f"Missing column in account: {expected}"

    def test_transaction_table_columns(self, inspector):
        cols = inspector.column_names("transaction")
        for expected in [
            "tx_id", "account_id", "amount", "balance_after",
            "description", "tx_type", "created_at",
        ]:
            assert expected in cols, f"Missing column in transaction: {expected}"

    def test_transfer_table_columns(self, inspector):
        cols = inspector.column_names("transfer")
        for expected in [
            "transfer_id", "debit_tx_id", "credit_tx_id",
            "amount", "status", "initiated_by", "created_at",
        ]:
            assert expected in cols, f"Missing column in transfer: {expected}"

    def test_fee_record_table_columns(self, inspector):
        cols = inspector.column_names("fee_record")
        for expected in [
            "fee_id", "account_id", "linked_tx_id",
            "fee_amount", "strategy_name", "created_at",
        ]:
            assert expected in cols, f"Missing column in fee_record: {expected}"


# ---------------------------------------------------------------------------
# Schema indexes
# ---------------------------------------------------------------------------

class TestSchemaIndexes:

    def test_transaction_account_index_exists(self, inspector):
        assert inspector.has_index("idx_tx_account_id"), \
            "Missing index: idx_tx_account_id"

    def test_transaction_time_index_exists(self, inspector):
        assert inspector.has_index("idx_tx_account_time"), \
            "Missing index: idx_tx_account_time"

    def test_account_owner_index_exists(self, inspector):
        assert inspector.has_index("idx_account_owner_id"), \
            "Missing index: idx_account_owner_id"

    def test_transfer_date_index_exists(self, inspector):
        assert inspector.has_index("idx_transfer_created_at"), \
            "Missing index: idx_transfer_created_at"


# ---------------------------------------------------------------------------
# Foreign key constraints
# ---------------------------------------------------------------------------

class TestForeignKeyConstraints:

    def test_account_requires_valid_owner(self, conn):
        """Cannot insert an account without a valid owner."""
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("""
                INSERT INTO account
                    (account_id, owner_id, account_type, balance,
                     min_possible_balance, created_at, updated_at)
                VALUES ('ACC-001', 'NONEXISTENT', 'current', 0, 0,
                        datetime('now'), datetime('now'))
            """)
            conn.commit()

    def test_transaction_requires_valid_account(self, conn):
        """Cannot insert a transaction without a valid account."""
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("""
                INSERT INTO "transaction"
                    (tx_id, account_id, amount, balance_after, tx_type)
                VALUES ('TX-001', 'NONEXISTENT', 100, 100, 'DEPOSIT')
            """)
            conn.commit()

    def test_transfer_requires_valid_debit_transaction(self, conn):
        """Cannot create a transfer with a non-existent debit transaction."""
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("""
                INSERT INTO transfer
                    (transfer_id, debit_tx_id, amount, initiated_by)
                VALUES ('TF-001', 'NONEXISTENT', 100, 'user')
            """)
            conn.commit()


# ---------------------------------------------------------------------------
# CHECK constraints
# ---------------------------------------------------------------------------

class TestCheckConstraints:

    def _create_owner(self, conn, owner_id="OWN-001", name="Test"):
        conn.execute(
            "INSERT INTO owner (owner_id, full_name, created_at, updated_at) "
            "VALUES (?, ?, datetime('now'), datetime('now'))", (owner_id, name)
        )

    def _create_account(self, conn, account_id="ACC-001", owner_id="OWN-001",
                         balance=1000.0, min_bal=0.0, actype="current"):
        conn.execute("""
            INSERT INTO account
                (account_id, owner_id, account_type, balance,
                 min_possible_balance, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        """, (account_id, owner_id, actype, balance, min_bal))

    def test_invalid_account_type_rejected(self, conn):
        self._create_owner(conn)
        with pytest.raises(sqlite3.IntegrityError):
            self._create_account(conn, actype="crypto")
            conn.commit()

    def test_balance_below_min_possible_rejected(self, conn):
        """balance < min_possible_balance violates CHECK constraint."""
        self._create_owner(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("""
                INSERT INTO account
                    (account_id, owner_id, account_type, balance,
                     min_possible_balance, created_at, updated_at)
                VALUES ('ACC-001', 'OWN-001', 'current', -100, 0,
                        datetime('now'), datetime('now'))
            """)
            conn.commit()

    def test_transaction_zero_amount_rejected(self, conn):
        self._create_owner(conn)
        self._create_account(conn)
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("""
                INSERT INTO "transaction"
                    (tx_id, account_id, amount, balance_after, tx_type)
                VALUES ('TX-001', 'ACC-001', 0, 1000, 'DEPOSIT')
            """)
            conn.commit()

    def test_invalid_transfer_status_rejected(self, conn):
        self._create_owner(conn)
        self._create_account(conn)
        conn.commit()
        conn.execute("""
            INSERT INTO "transaction"
                (tx_id, account_id, amount, balance_after, tx_type)
            VALUES ('TX-001', 'ACC-001', -100, 900, 'TRANSFER_DEBIT')
        """)
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("""
                INSERT INTO transfer
                    (transfer_id, debit_tx_id, amount, status, initiated_by)
                VALUES ('TF-001', 'TX-001', 100, 'INVALID_STATUS', 'user')
            """)
            conn.commit()

    def test_valid_account_types_accepted(self, conn):
        self._create_owner(conn)
        for i, actype in enumerate(["current", "savings", "pro", "youth"]):
            self._create_account(conn, account_id=f"ACC-{i:03d}", actype=actype)
        conn.commit()

    def test_transfer_same_tx_rejected(self, conn):
        """debit_tx_id != credit_tx_id constraint."""
        self._create_owner(conn)
        self._create_account(conn)
        conn.commit()
        conn.execute("""
            INSERT INTO "transaction"
                (tx_id, account_id, amount, balance_after, tx_type)
            VALUES ('TX-001', 'ACC-001', -100, 900, 'TRANSFER_DEBIT')
        """)
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("""
                INSERT INTO transfer
                    (transfer_id, debit_tx_id, credit_tx_id, amount, initiated_by)
                VALUES ('TF-001', 'TX-001', 'TX-001', 100, 'user')
            """)
            conn.commit()


# ---------------------------------------------------------------------------
# SQLiteAccountRepository — port contract
# ---------------------------------------------------------------------------

class TestSQLiteAccountRepository:

    def test_is_account_repository_port(self, repo):
        assert isinstance(repo, AccountRepositoryPort)

    def test_save_and_find_by_id(self, repo):
        account = AccountFactory.create("current", "Alice", 1_000.0)
        repo.save(account)
        found = repo.find_by_id(account.account_id)
        assert found is not None
        assert found.account_id == account.account_id

    def test_balance_persisted_correctly(self, repo):
        account = AccountFactory.create("current", "Alice", 750.0)
        repo.save(account)
        found = repo.find_by_id(account.account_id)
        assert found.balance == 750.0

    def test_find_unknown_returns_none(self, repo):
        assert repo.find_by_id("GHOST") is None

    def test_count(self, repo):
        assert repo.count() == 0
        repo.save(AccountFactory.create("current", "Alice", 100.0))
        repo.save(AccountFactory.create("savings", "Bob",   200.0))
        assert repo.count() == 2

    def test_find_all(self, repo):
        repo.save(AccountFactory.create("current", "Alice", 100.0))
        repo.save(AccountFactory.create("savings", "Bob",   200.0))
        accounts = repo.find_all()
        assert len(accounts) == 2

    def test_exists(self, repo):
        account = AccountFactory.create("current", "Alice", 100.0)
        repo.save(account)
        assert repo.exists(account.account_id) is True
        assert repo.exists("GHOST") is False

    def test_save_updates_balance(self, repo):
        account = AccountFactory.create("current", "Alice", 500.0)
        repo.save(account)
        account.deposit(200.0)
        repo.save(account)
        found = repo.find_by_id(account.account_id)
        assert found.balance == 700.0

    def test_find_by_owner(self, repo):
        a1 = AccountFactory.create("current", "Alice", 100.0)
        a2 = AccountFactory.create("savings", "Alice", 200.0)
        b  = AccountFactory.create("current", "Bob",   300.0)
        for acc in [a1, a2, b]:
            repo.save(acc)
        alices = repo.find_by_owner("Alice")
        assert len(alices) == 2

    def test_transaction_history_synced(self, repo, conn):
        account = AccountFactory.create("current", "Alice", 500.0)
        account.deposit(200.0, "Salary")
        account.withdraw(100.0, "Rent")
        repo.save(account)

        rows = conn.execute(
            'SELECT * FROM "transaction" WHERE account_id = ?',
            (account.account_id,)
        ).fetchall()
        # Initial deposit + Salary + Rent = 3 transactions
        assert len(rows) == 3

    def test_multiple_saves_do_not_duplicate_transactions(self, repo, conn):
        account = AccountFactory.create("current", "Alice", 500.0)
        repo.save(account)
        account.deposit(100.0, "More money")
        repo.save(account)
        repo.save(account)   # third save — should not duplicate

        rows = conn.execute(
            'SELECT COUNT(*) FROM "transaction" WHERE account_id = ?',
            (account.account_id,)
        ).fetchone()[0]
        assert rows == 2   # initial + deposit


# ---------------------------------------------------------------------------
# Reporting queries
# ---------------------------------------------------------------------------

class TestReportingQueries:

    def test_transaction_history(self, repo):
        account = AccountFactory.create("current", "Alice", 1_000.0)
        account.deposit(500.0, "Salary")
        account.withdraw(200.0, "Rent")
        repo.save(account)

        history = repo.get_transaction_history(account.account_id)
        assert len(history) == 3   # opening + salary + rent
        # Newest first
        descriptions = [h["description"] for h in history]
        assert "Rent" in descriptions
        assert "Salary" in descriptions

    def test_account_summary(self, repo):
        account = AccountFactory.create("current", "Alice", 1_000.0)
        account.deposit(500.0, "Salary")
        repo.save(account)

        summary = repo.get_account_summary(account.account_id)
        assert summary is not None
        assert summary["full_name"] == "Alice"
        assert summary["tx_count"] == 2   # opening + salary
        assert summary["total_credits"] == pytest.approx(1_500.0)

    def test_account_summary_unknown(self, repo):
        assert repo.get_account_summary("GHOST") is None


# ---------------------------------------------------------------------------
# Clean Architecture swap — SQLite behaves like InMemory
# ---------------------------------------------------------------------------

class TestCleanArchitectureSwap:
    """
    Core Day 13 test: Use Cases work identically with SQLite or InMemory.
    Same commands, same results, different storage.
    """

    def _run_flow(self, container, repository):
        app = BankApplicationService(container, registry=repository)

        r1 = app.create_account(
            CreateAccountCommand("Alice", "current", 2_000.0, "system"))
        r2 = app.create_account(
            CreateAccountCommand("Bob",   "savings", 1_000.0, "system"))

        alice_id = r1.data["account_id"]
        bob_id   = r2.data["account_id"]

        app.deposit(DepositCommand(alice_id, 500.0, "payroll"))
        t = app.transfer(TransferCommand(alice_id, bob_id, 300.0, "alice"))

        return {
            "transfer_success":      t.success,
            "alice_balance_after":   t.data.get("from_balance_after"),
            "bob_balance_after":     t.data.get("to_balance_after"),
        }

    def test_sqlite_produces_same_results_as_in_memory(self, conn, container):
        result_mem   = self._run_flow(container, InMemoryAccountRepository())
        result_sqlite = self._run_flow(container, SQLiteAccountRepository(conn))

        assert result_mem["transfer_success"]    == result_sqlite["transfer_success"]
        assert result_mem["alice_balance_after"] == result_sqlite["alice_balance_after"]
        assert result_mem["bob_balance_after"]   == result_sqlite["bob_balance_after"]

    def test_data_survives_reconnection(self, container):
        """
        Critical persistence test: data persists across connections.
        (Uses a temp file, not in-memory.)
        """
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            # Write
            conn1 = get_connection(db_path)
            repo1 = SQLiteAccountRepository(conn1)
            account = AccountFactory.create("current", "Alice", 1_000.0)
            repo1.save(account)
            account_id = account.account_id
            conn1.close()

            # Read from new connection
            conn2 = get_connection(db_path)
            repo2 = SQLiteAccountRepository(conn2)
            found = repo2.find_by_id(account_id)
            conn2.close()

            assert found is not None
            assert found.balance == 1_000.0
        finally:
            os.unlink(db_path)


# ---------------------------------------------------------------------------
# Schema idempotency
# ---------------------------------------------------------------------------

class TestSchemaIdempotency:

    def test_create_schema_twice_is_safe(self):
        """IF NOT EXISTS ensures re-running schema creation is safe."""
        conn = get_connection(":memory:")
        create_schema(conn)
        create_schema(conn)   # should not raise
        inspector = SchemaInspector(conn)
        assert inspector.has_table("account")
        conn.close()

    def test_schema_sql_contains_if_not_exists(self):
        """All CREATE TABLE statements use IF NOT EXISTS."""
        create_statements = [
            line for line in SCHEMA_SQL.splitlines()
            if line.strip().upper().startswith("CREATE TABLE")
        ]
        for stmt in create_statements:
            assert "IF NOT EXISTS" in stmt.upper(), \
                f"Missing IF NOT EXISTS: {stmt}"
