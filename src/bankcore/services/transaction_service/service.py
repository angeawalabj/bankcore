"""
BankCore — Day 16: TransactionService (Microservice)
=====================================================
Autonomous microservice responsible for transaction processing.

Responsibilities:
  - Process transfers, deposits, withdrawals
  - Validate transaction rules (limits, funds availability)
  - Maintain its own transaction log
  - Call AccountService to read/update balances

NOT responsible for:
  - Account creation or management (AccountService's job)
  - Notification/alerts (future AlertService's job)

API surface:
  POST /transfers           → execute a transfer between accounts
  POST /deposits            → credit an account
  POST /withdrawals         → debit an account
  GET  /transactions/{id}   → get transaction details
  GET  /transactions        → list transactions (optional filter by account)

Microservices rule: TransactionService has its own data store (tx log).
It calls AccountService via ServiceClient — never imports it directly.
"""

from __future__ import annotations
import uuid
from datetime import datetime
from typing import Optional

from bankcore.services.shared.service_client import (
    ServiceClient, ServiceRequest, ServiceResponse,
)
from bankcore.config_manager import ConfigManager
from bankcore.protocols import FakeConfig


class TransactionLog:
    """
    TransactionService's own data store.
    Stores transaction records independently of AccountService.
    """

    def __init__(self) -> None:
        self._records: list[dict] = []

    def append(self, record: dict) -> None:
        self._records.append({**record, "created_at": datetime.now().isoformat()})

    def find_by_id(self, tx_id: str) -> Optional[dict]:
        return next((r for r in self._records if r["tx_id"] == tx_id), None)

    def find_by_account(self, account_id: str) -> list[dict]:
        return [r for r in self._records if
                r.get("from_account_id") == account_id or
                r.get("to_account_id")   == account_id or
                r.get("account_id")      == account_id]

    def count(self) -> int:
        return len(self._records)

    def all(self) -> list[dict]:
        return list(self._records)


class TransactionMicroservice:
    """
    TransactionService microservice.

    Depends on AccountService via ServiceClient (injected).
    No direct import of AccountService classes.
    Communication is entirely through dict (JSON-like) messages.
    """

    SERVICE_NAME = "transaction-service"

    def __init__(self, account_client: ServiceClient, config: FakeConfig = None) -> None:
        self._accounts = account_client
        self._log      = TransactionLog()
        self._config   = config or FakeConfig()

    # ------------------------------------------------------------------
    # HTTP-style router
    # ------------------------------------------------------------------

    def handle(self, request: ServiceRequest) -> ServiceResponse:
        method = request.method.upper()
        path   = request.path.rstrip("/")

        if method == "POST" and path == "/transfers":
            return self._transfer(request)

        if method == "POST" and path == "/deposits":
            return self._deposit(request)

        if method == "POST" and path == "/withdrawals":
            return self._withdrawal(request)

        if method == "GET" and path == "/transactions":
            return self._list_transactions(request)

        if method == "GET" and path.startswith("/transactions/"):
            tx_id = path.split("/transactions/")[1]
            return self._get_transaction(tx_id)

        return ServiceResponse(404, {"error": f"Route not found: {method} {path}"})

    # ------------------------------------------------------------------
    # Route handlers
    # ------------------------------------------------------------------

    def _transfer(self, request: ServiceRequest) -> ServiceResponse:
        """
        POST /transfers — move funds between two accounts.

        Flow (sequence diagram in docs/jour-16/README.md):
          1. Validate request body
          2. Load both accounts from AccountService
          3. Validate business rules (balance, limits)
          4. Update both balances via AccountService PATCH
          5. Log transaction record
          6. Return result
        """
        body = request.body
        from_id = body.get("from_account_id", "")
        to_id   = body.get("to_account_id",   "")
        amount  = body.get("amount", 0)

        # Step 1: Basic validation
        if not from_id or not to_id:
            return ServiceResponse(422, {
                "error": "from_account_id and to_account_id are required.",
                "code":  "VALIDATION_ERROR",
            })
        try:
            amount = float(amount)
        except (ValueError, TypeError):
            return ServiceResponse(422, {"error": "Invalid amount.", "code": "VALIDATION_ERROR"})

        if amount <= 0:
            return ServiceResponse(422, {
                "error": "Amount must be positive.",
                "code": "VALIDATION_ERROR",
            })

        max_amount = self._config.get("limits.max_transfer_amount", 50_000.0)
        if amount > max_amount:
            return ServiceResponse(422, {
                "error": f"Amount {amount} exceeds limit {max_amount}.",
                "code": "LIMIT_EXCEEDED",
            })

        # Step 2: Load accounts from AccountService
        from_resp = self._accounts.get(f"/accounts/{from_id}")
        if not from_resp.ok:
            return ServiceResponse(from_resp.status_code, from_resp.body)

        to_resp = self._accounts.get(f"/accounts/{to_id}")
        if not to_resp.ok:
            return ServiceResponse(to_resp.status_code, to_resp.body)

        from_account = from_resp.body
        to_account   = to_resp.body

        # Step 3: Validate business rules
        from_balance = from_account.get("balance", 0)
        min_balance  = from_account.get("min_possible_balance", 0)

        if from_balance - amount < min_balance:
            return ServiceResponse(422, {
                "error": (
                    f"Insufficient funds. Balance: {from_balance:.2f}, "
                    f"required: {amount:.2f}, minimum: {min_balance:.2f}."
                ),
                "code": "INSUFFICIENT_FUNDS",
            })

        # Step 4: Update balances via AccountService
        new_from = from_balance - amount
        new_to   = to_account.get("balance", 0) + amount

        patch_from = self._accounts.patch(
            f"/accounts/{from_id}/balance", {"balance": new_from}
        )
        if not patch_from.ok:
            return ServiceResponse(patch_from.status_code, {
                "error": "Failed to debit source account.",
                "details": patch_from.body,
            })

        patch_to = self._accounts.patch(
            f"/accounts/{to_id}/balance", {"balance": new_to}
        )
        if not patch_to.ok:
            # Rollback: restore source account
            self._accounts.patch(
                f"/accounts/{from_id}/balance", {"balance": from_balance}
            )
            return ServiceResponse(patch_to.status_code, {
                "error": "Failed to credit destination. Transfer reversed.",
                "details": patch_to.body,
            })

        # Step 5: Log the transaction
        tx_id = f"TX-{str(uuid.uuid4())[:8].upper()}"
        self._log.append({
            "tx_id":           tx_id,
            "type":            "TRANSFER",
            "from_account_id": from_id,
            "to_account_id":   to_id,
            "amount":          amount,
            "from_balance_after": new_from,
            "to_balance_after":  new_to,
            "initiated_by":    body.get("initiated_by", "api"),
        })

        # Step 6: Return result
        return ServiceResponse(200, {
            "tx_id":             tx_id,
            "success":           True,
            "from_account_id":   from_id,
            "to_account_id":     to_id,
            "amount":            amount,
            "from_balance_after": new_from,
            "to_balance_after":   new_to,
        })

    def _deposit(self, request: ServiceRequest) -> ServiceResponse:
        body       = request.body
        account_id = body.get("account_id", "")
        amount     = body.get("amount", 0)

        if not account_id:
            return ServiceResponse(422, {"error": "account_id required.", "code": "VALIDATION_ERROR"})
        try:
            amount = float(amount)
        except (ValueError, TypeError):
            return ServiceResponse(422, {"error": "Invalid amount.", "code": "VALIDATION_ERROR"})
        if amount <= 0:
            return ServiceResponse(422, {"error": "Amount must be positive.", "code": "VALIDATION_ERROR"})

        # Load account
        resp = self._accounts.get(f"/accounts/{account_id}")
        if not resp.ok:
            return ServiceResponse(resp.status_code, resp.body)

        new_balance = resp.body.get("balance", 0) + amount

        patch = self._accounts.patch(
            f"/accounts/{account_id}/balance", {"balance": new_balance}
        )
        if not patch.ok:
            return ServiceResponse(patch.status_code, {"error": "Failed to update balance."})

        tx_id = f"TX-{str(uuid.uuid4())[:8].upper()}"
        self._log.append({
            "tx_id":       tx_id,
            "type":        "DEPOSIT",
            "account_id":  account_id,
            "amount":      amount,
            "balance_after": new_balance,
            "initiated_by": body.get("initiated_by", "api"),
        })

        return ServiceResponse(200, {
            "tx_id":        tx_id,
            "success":      True,
            "account_id":   account_id,
            "amount":       amount,
            "balance_after": new_balance,
        })

    def _withdrawal(self, request: ServiceRequest) -> ServiceResponse:
        body       = request.body
        account_id = body.get("account_id", "")
        amount     = body.get("amount", 0)

        if not account_id:
            return ServiceResponse(422, {"error": "account_id required.", "code": "VALIDATION_ERROR"})
        try:
            amount = float(amount)
        except (ValueError, TypeError):
            return ServiceResponse(422, {"error": "Invalid amount.", "code": "VALIDATION_ERROR"})
        if amount <= 0:
            return ServiceResponse(422, {"error": "Amount must be positive.", "code": "VALIDATION_ERROR"})

        resp = self._accounts.get(f"/accounts/{account_id}")
        if not resp.ok:
            return ServiceResponse(resp.status_code, resp.body)

        current_balance = resp.body.get("balance", 0)
        min_balance     = resp.body.get("min_possible_balance", 0)
        new_balance     = current_balance - amount

        if new_balance < min_balance:
            return ServiceResponse(422, {
                "error": f"Insufficient funds. Balance: {current_balance:.2f}.",
                "code":  "INSUFFICIENT_FUNDS",
            })

        patch = self._accounts.patch(
            f"/accounts/{account_id}/balance", {"balance": new_balance}
        )
        if not patch.ok:
            return ServiceResponse(patch.status_code, {"error": "Failed to update balance."})

        tx_id = f"TX-{str(uuid.uuid4())[:8].upper()}"
        self._log.append({
            "tx_id":        tx_id,
            "type":         "WITHDRAWAL",
            "account_id":   account_id,
            "amount":       amount,
            "balance_after": new_balance,
            "initiated_by": body.get("initiated_by", "api"),
        })

        return ServiceResponse(200, {
            "tx_id":        tx_id,
            "success":      True,
            "account_id":   account_id,
            "amount":       amount,
            "balance_after": new_balance,
        })

    def _list_transactions(self, request: ServiceRequest) -> ServiceResponse:
        account_id = request.params.get("account_id")
        if account_id:
            records = self._log.find_by_account(account_id)
        else:
            records = self._log.all()
        return ServiceResponse(200, {"transactions": records, "count": len(records)})

    def _get_transaction(self, tx_id: str) -> ServiceResponse:
        record = self._log.find_by_id(tx_id)
        if record is None:
            return ServiceResponse(404, {
                "error": f"Transaction {tx_id} not found.",
                "code":  "TX_NOT_FOUND",
            })
        return ServiceResponse(200, record)

    # ------------------------------------------------------------------
    # Direct access for testing
    # ------------------------------------------------------------------

    @property
    def transaction_log(self) -> TransactionLog:
        return self._log

    @property
    def account_client(self) -> ServiceClient:
        return self._accounts
