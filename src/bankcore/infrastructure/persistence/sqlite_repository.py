"""
BankCore — Day 13: SQLiteAccountRepository
============================================
Implements AccountRepositoryPort using SQLite and the schema from schema.py.

This is the first real persistence adapter in BankCore.

Clean Architecture rule respected:
  - Port defined in Application (AccountRepositoryPort)
  - Adapter defined here in Infrastructure
  - Use Cases never import this class directly
  - BankContainer wires it in (one-line swap from InMemoryAccountRepository)

Design decisions:
  - balance denormalized on account row (fast reads, updated on every write)
  - transactions inserted as OPENING on account creation
  - all amounts stored as REAL (float) in SQLite — currency stored separately
  - owner auto-created if not found (simplified for Day 13; full Owner
    entity management arrives with Jour 15 Hexagonal Architecture)
"""

from __future__ import annotations
import sqlite3
import uuid
from datetime import datetime
from typing import Optional, List

from bankcore.application.ports import AccountRepositoryPort
from bankcore.infrastructure.persistence.schema import create_schema, get_connection


class SQLiteAccountRepository(AccountRepositoryPort):
    """
    SQLite-backed implementation of AccountRepositoryPort.

    Each method maps directly to the schema designed in Day 13.
    The Account object (domain) is converted to/from rows here —
    this conversion is the Adapter's responsibility.

    Usage:
        conn = get_connection("bankcore.db")
        repo = SQLiteAccountRepository(conn)
        # Swap into BankContainer:
        container = BankContainer.build(repository=repo)
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        create_schema(conn)

    # ------------------------------------------------------------------
    # AccountRepositoryPort implementation
    # ------------------------------------------------------------------

    def save(self, account) -> None:
        """
        Insert or update an account row.
        Also ensures an owner row exists (auto-created if needed).
        """
        self._ensure_owner(account.owner_name)

        now = datetime.now().isoformat()

        self._conn.execute("""
            INSERT INTO account
                (account_id, owner_id, account_type, balance,
                 min_possible_balance, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'ACTIVE', ?, ?)
            ON CONFLICT(account_id) DO UPDATE SET
                balance              = excluded.balance,
                min_possible_balance = excluded.min_possible_balance,
                updated_at           = excluded.updated_at
        """, (
            account.account_id,
            self._owner_id(account.owner_name),
            account.account_type,
            account.balance,
            account.min_possible_balance,
            now, now,
        ))

        # Sync transaction history
        self._sync_transactions(account)
        self._conn.commit()

    def find_by_id(self, account_id: str) -> Optional[object]:
        row = self._conn.execute(
            "SELECT * FROM account WHERE account_id = ?", (account_id,)
        ).fetchone()
        if row is None:
            return None
        return self._reconstruct(dict(row))

    def find_all(self) -> List[object]:
        rows = self._conn.execute(
            "SELECT * FROM account WHERE status = 'ACTIVE' ORDER BY created_at"
        ).fetchall()
        return [self._reconstruct(dict(r)) for r in rows]

    def find_by_owner(self, owner_name: str) -> List[object]:
        owner_id = self._owner_id(owner_name)
        if owner_id is None:
            return []
        rows = self._conn.execute(
            "SELECT * FROM account WHERE owner_id = ? AND status = 'ACTIVE'",
            (owner_id,)
        ).fetchall()
        return [self._reconstruct(dict(r)) for r in rows]

    def count(self) -> int:
        return self._conn.execute(
            "SELECT COUNT(*) FROM account WHERE status = 'ACTIVE'"
        ).fetchone()[0]

    def exists(self, account_id: str) -> bool:
        return self._conn.execute(
            "SELECT 1 FROM account WHERE account_id = ?", (account_id,)
        ).fetchone() is not None

    # ------------------------------------------------------------------
    # Transaction history sync
    # ------------------------------------------------------------------

    def _sync_transactions(self, account) -> None:
        """
        Persist any new transaction records from the account's history.
        Only inserts rows not yet in the database (by tx_id).
        """
        existing_ids = {
            row[0] for row in self._conn.execute(
                "SELECT tx_id FROM \"transaction\" WHERE account_id = ?",
                (account.account_id,)
            ).fetchall()
        }

        for tx in account.get_transactions():
            if tx["id"] in existing_ids:
                continue

            # Map description to tx_type
            tx_type = self._infer_tx_type(tx["amount"], tx["description"])

            self._conn.execute("""
                INSERT INTO "transaction"
                    (tx_id, account_id, amount, balance_after,
                     description, tx_type, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                tx["id"],
                account.account_id,
                tx["amount"],
                tx["balance_after"],
                tx["description"],
                tx_type,
                tx["date"],
            ))

    def _infer_tx_type(self, amount: float, description: str) -> str:
        """Infer the transaction type from amount sign and description."""
        desc = description.lower()
        if "initial deposit" in desc or "opening" in desc:
            return "OPENING"
        if "interest" in desc:
            return "INTEREST"
        if "fee" in desc:
            return "FEE"
        if "transfer" in desc and amount < 0:
            return "TRANSFER_DEBIT"
        if "transfer" in desc and amount > 0:
            return "TRANSFER_CREDIT"
        if amount > 0:
            return "DEPOSIT"
        return "WITHDRAWAL"

    # ------------------------------------------------------------------
    # Owner management
    # ------------------------------------------------------------------

    def _ensure_owner(self, owner_name: str) -> str:
        """Create owner row if it doesn't exist. Return owner_id."""
        existing = self._owner_id(owner_name)
        if existing:
            return existing

        owner_id = str(uuid.uuid4())[:8].upper()
        now = datetime.now().isoformat()
        self._conn.execute(
            "INSERT INTO owner (owner_id, full_name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (owner_id, owner_name, now, now)
        )
        return owner_id

    def _owner_id(self, owner_name: str) -> Optional[str]:
        row = self._conn.execute(
            "SELECT owner_id FROM owner WHERE full_name = ?", (owner_name,)
        ).fetchone()
        return row[0] if row else None

    # ------------------------------------------------------------------
    # Object reconstruction
    # ------------------------------------------------------------------

    def _reconstruct(self, row: dict) -> object:
        """
        Reconstruct an Account domain object from a database row.

        This is the anti-corruption layer: BankCore Account objects
        are the source of truth — the database row is just storage.
        We reconstruct from scratch rather than mapping field-by-field
        to avoid coupling the domain model to the schema.
        """
        from bankcore.account_factory import AccountFactory
        from bankcore.account_type_registry import AccountTypeRegistry

        account_type = row["account_type"]
        if not AccountTypeRegistry.is_registered(account_type):
            account_type = "current"   # fallback for unknown types

        account = AccountFactory.create(
            account_type,
            self._owner_name(row["owner_id"]),
            0.0,   # created with zero; balance synced below
        )

        # Override the generated account_id with the stored one
        account.__dict__["account_id"] = row["account_id"]

        # Sync balance from database (authoritative source)
        # We use internal _balance to avoid triggering business logic
        account._balance = row["balance"]

        return account

    def _owner_name(self, owner_id: str) -> str:
        row = self._conn.execute(
            "SELECT full_name FROM owner WHERE owner_id = ?", (owner_id,)
        ).fetchone()
        return row[0] if row else "Unknown"

    # ------------------------------------------------------------------
    # Specification-based queries (Day 14 — Repository Pattern)
    # ------------------------------------------------------------------

    def find(self, spec=None, page: int = 1, page_size: int = 20):
        """
        Load all matching accounts from SQLite, apply spec in-memory,
        then paginate. For large datasets, SQLite-native filtering
        (Day 13 schema indexes) handles the heavy lifting.
        """
        from bankcore.application.specifications import AllSpec, Page
        spec = spec or AllSpec()

        rows = self._conn.execute(
            "SELECT account_id FROM account WHERE status = 'ACTIVE'"
        ).fetchall()

        all_accounts = []
        for row in rows:
            account = self.find_by_id(row[0])
            if account and spec.is_satisfied_by(account):
                all_accounts.append(account)

        total = len(all_accounts)
        start = (page - 1) * page_size
        end   = start + page_size
        return Page(
            items=all_accounts[start:end],
            total=total,
            page=page,
            page_size=page_size,
        )

    def find_one(self, spec=None):
        """Return first matching account, or None."""
        page = self.find(spec, page=1, page_size=1)
        return page.items[0] if page.items else None

    def count_spec(self, spec=None) -> int:
        """Count accounts matching a specification."""
        page = self.find(spec, page=1, page_size=999_999)
        return page.total

    # ------------------------------------------------------------------
    # Reporting queries (beyond the Port interface)
    # ------------------------------------------------------------------

    def get_transaction_history(self, account_id: str) -> list[dict]:
        """Return all transactions for an account, newest first."""
        rows = self._conn.execute("""
            SELECT tx_id, amount, balance_after, description, tx_type, created_at
            FROM "transaction"
            WHERE account_id = ?
            ORDER BY created_at DESC
        """, (account_id,)).fetchall()
        return [dict(r) for r in rows]

    def get_account_summary(self, account_id: str) -> Optional[dict]:
        """Join account + owner for a complete summary view."""
        row = self._conn.execute("""
            SELECT a.*, o.full_name, o.email,
                   COUNT(t.tx_id) as tx_count,
                   SUM(CASE WHEN t.amount > 0 THEN t.amount ELSE 0 END) as total_credits,
                   SUM(CASE WHEN t.amount < 0 THEN ABS(t.amount) ELSE 0 END) as total_debits
            FROM account a
            JOIN owner o ON a.owner_id = o.owner_id
            LEFT JOIN "transaction" t ON a.account_id = t.account_id
            WHERE a.account_id = ?
            GROUP BY a.account_id
        """, (account_id,)).fetchone()
        return dict(row) if row else None
