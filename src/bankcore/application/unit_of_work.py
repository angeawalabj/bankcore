"""
BankCore — Day 14: Unit of Work
=================================
Coordinates atomic operations across multiple repositories.

Problem: a bank transfer modifies TWO accounts. Without UnitOfWork:
  1. alice.withdraw(500)  → saved
  2. bob.deposit(500)    → save FAILS
  → Database has alice's debit but not bob's credit. Inconsistency.

With UnitOfWork:
  1. alice.withdraw(500)  → tracked (not yet saved)
  2. bob.deposit(500)    → tracked (not yet saved)
  3. uow.commit()         → saves BOTH atomically, or neither

This is the application-level equivalent of a database transaction.

Design:
  - Tracks "dirty" accounts (modified since last commit)
  - commit() saves all dirty accounts in one operation
  - rollback() discards all pending changes
  - Context manager protocol: __enter__ / __exit__

Connection to Day 13 (Schema):
  For SQLiteAccountRepository, commit() brackets every save() in this
  batch inside begin_transaction()/commit() (or rollback() on failure),
  so the database only ever sees all writes or none — a real SQLite
  transaction boundary, not just an application-level promise. For
  InMemoryAccountRepository, find() hands out a deep copy rather than
  the live stored object: mutating it never touches the repository, so
  rollback() (which just discards the copy) genuinely reverts nothing
  having happened, instead of leaving an already-mutated object behind.
"""

from __future__ import annotations
import copy
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from bankcore.application.ports import AccountRepositoryPort


class UnitOfWork:
    """
    Tracks changes to accounts and commits them atomically.

    Usage:
        with UnitOfWork(repo) as uow:
            alice = uow.find("ACC-001")
            bob   = uow.find("ACC-002")
            alice.withdraw(500)
            bob.deposit(500)
            uow.commit()
        # On exception: automatic rollback (nothing saved)
    """

    def __init__(self, repository: "AccountRepositoryPort") -> None:
        self._repo    = repository
        self._dirty:  dict = {}   # account_id → account (modified)
        self._loaded: dict = {}   # account_id → account (original snapshot)
        self._committed = False

    # ------------------------------------------------------------------
    # Account access
    # ------------------------------------------------------------------

    def find(self, account_id: str):
        """
        Load an account and register it for change tracking.
        Returns the same object instance on repeated calls (identity map).

        Returns a deep copy of the repository's account, not the live
        stored object: callers can freely mutate it (withdraw/deposit)
        without touching the repository until commit(). rollback() then
        just has to discard the copy — no mutation ever reached storage.
        """
        if account_id in self._loaded:
            return self._loaded[account_id]

        account = self._repo.find_by_id(account_id)
        if account is not None:
            account = copy.deepcopy(account)
            self._loaded[account_id] = account
        return account

    def register_new(self, account) -> None:
        """Register a newly created account (not yet in the repository)."""
        self._dirty[account.account_id] = account

    def register_dirty(self, account) -> None:
        """Mark an account as modified — will be saved on commit."""
        self._dirty[account.account_id] = account

    # ------------------------------------------------------------------
    # Commit / Rollback
    # ------------------------------------------------------------------

    def commit(self) -> None:
        """
        Persist all dirty accounts atomically.

        For SQLite repositories, begin_transaction() suspends the
        repository's normal per-save autocommit, so every save() below
        lands in one open transaction. If any save() raises, rollback()
        performs a real SQLite ROLLBACK — undoing prior saves in this
        batch too — and the exception propagates. Only if every save()
        succeeds does commit() perform the real SQLite COMMIT. Repositories
        without transaction support (e.g. in-memory) just skip these hooks.
        """
        if hasattr(self._repo, "begin_transaction"):
            self._repo.begin_transaction()

        try:
            for account in self._dirty.values():
                self._repo.save(account)
        except Exception:
            if hasattr(self._repo, "rollback"):
                self._repo.rollback()
            raise

        if hasattr(self._repo, "commit"):
            self._repo.commit()

        self._dirty.clear()
        self._committed = True

    def rollback(self) -> None:
        """
        Discard all pending changes.

        Loaded accounts are deep copies (see find()), so clearing them
        here is enough: nothing mutated on these copies ever reached the
        repository, so there is nothing in storage to undo.
        """
        self._dirty.clear()
        self._loaded.clear()

        if hasattr(self._repo, "rollback"):
            self._repo.rollback()

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "UnitOfWork":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if exc_type is None:
            # No exception — commit if not already done
            if not self._committed and self._dirty:
                self.commit()
        else:
            # Exception occurred — rollback
            self.rollback()
        return False   # do not suppress exceptions

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    @property
    def dirty_count(self) -> int:
        return len(self._dirty)

    @property
    def loaded_count(self) -> int:
        return len(self._loaded)

    def is_dirty(self, account_id: str) -> bool:
        return account_id in self._dirty


class TransferOperation:
    """
    Domain operation: transfer funds between two accounts atomically.

    Encapsulates the business logic of a transfer within a UnitOfWork.
    Used by TransferUseCase when atomic consistency is required.

    This replaces the manual withdraw/deposit sequence in TransactionService
    for the case where two accounts must be saved together.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    def execute(
        self,
        from_account_id: str,
        to_account_id: str,
        amount: float,
        description: str = "Transfer",
    ) -> dict:
        """
        Execute a transfer within the Unit of Work.
        Both accounts are registered as dirty — commit() saves both.
        """
        from_account = self._uow.find(from_account_id)
        to_account   = self._uow.find(to_account_id)

        if from_account is None:
            return {"success": False, "reason": f"Account {from_account_id} not found."}
        if to_account is None:
            return {"success": False, "reason": f"Account {to_account_id} not found."}

        withdrawn = from_account.withdraw(
            amount, description=f"Transfer to {to_account_id}"
        )
        if not withdrawn:
            return {
                "success": False,
                "reason": "Withdrawal refused (insufficient funds or account rules).",
            }

        to_account.deposit(amount, description=f"Transfer from {from_account_id}")

        # Register both as dirty
        self._uow.register_dirty(from_account)
        self._uow.register_dirty(to_account)

        return {
            "success":           True,
            "from_account_id":   from_account_id,
            "to_account_id":     to_account_id,
            "amount":            amount,
            "from_balance_after": from_account.balance,
            "to_balance_after":  to_account.balance,
        }
