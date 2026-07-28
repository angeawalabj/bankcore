"""
BankCore — Day 16: AccountService (Microservice)
=================================================
Autonomous microservice responsible for account lifecycle.

Responsibilities:
  - Create, read, update, close accounts
  - Enforce account-level business rules (type, owner, initial deposit)
  - Maintain its own data store (no shared database)

NOT responsible for:
  - Transaction processing (TransactionService's job)
  - Fee calculation (TransactionService's job)
  - Fraud detection (future AlertService's job)

API surface (simulated HTTP):
  GET    /accounts          → list all accounts
  GET    /accounts/{id}     → get one account
  POST   /accounts          → create account
  PATCH  /accounts/{id}/balance → update balance (called by TransactionService)
  DELETE /accounts/{id}     → close account

Microservices rule: AccountService has its own data store.
It does NOT import TransactionService. Communication is one-way:
TransactionService calls AccountService.
"""

from __future__ import annotations
from typing import Optional

from bankcore.services.shared.service_client import ServiceRequest, ServiceResponse
from bankcore.infrastructure.persistence.in_memory_repository import (
    InMemoryAccountRepository,
)
from bankcore.application.commands import CreateAccountCommand
from bankcore.application.use_cases import BankApplicationService
from bankcore.application.specifications import OwnerSpec, TypeSpec
from bankcore.protocols import FakeConfig, SpyAlertSystem
from bankcore.container import BankContainer


class AccountService:
    """
    AccountService microservice.

    Exposes a handle(request) method that acts as the HTTP router.
    ServiceClient calls this method — in Day 19 it becomes a real
    FastAPI/Flask router.

    Owns:
        - Its own InMemoryAccountRepository (will be SQLite in production)
        - Its own BankContainer with FakeConfig for isolation
        - No reference to TransactionService
    """

    SERVICE_NAME = "account-service"

    def __init__(self) -> None:
        self._container = BankContainer.build(
            config=FakeConfig(),
            alert_system=SpyAlertSystem(),
        )
        self._repo = InMemoryAccountRepository()
        self._app  = BankApplicationService(self._container, registry=self._repo)

    # ------------------------------------------------------------------
    # HTTP-style router
    # ------------------------------------------------------------------

    def handle(self, request: ServiceRequest) -> ServiceResponse:
        """Route incoming requests to the appropriate handler."""
        method = request.method.upper()
        path   = request.path.rstrip("/")

        # GET /accounts
        if method == "GET" and path == "/accounts":
            return self._list_accounts(request)

        # GET /accounts/{id}
        if method == "GET" and path.startswith("/accounts/") and "/balance" not in path:
            account_id = path.split("/accounts/")[1]
            return self._get_account(account_id)

        # POST /accounts
        if method == "POST" and path == "/accounts":
            return self._create_account(request)

        # PATCH /accounts/{id}/balance
        if method == "PATCH" and path.endswith("/balance"):
            account_id = path.split("/accounts/")[1].replace("/balance", "")
            return self._update_balance(account_id, request)

        # DELETE /accounts/{id}
        if method == "DELETE" and path.startswith("/accounts/"):
            account_id = path.split("/accounts/")[1]
            return self._close_account(account_id)

        return ServiceResponse(404, {"error": f"Route not found: {method} {path}"})

    # ------------------------------------------------------------------
    # Route handlers
    # ------------------------------------------------------------------

    def _list_accounts(self, request: ServiceRequest) -> ServiceResponse:
        filters = {}
        owner = request.params.get("owner")
        atype = request.params.get("type")

        spec = None
        if owner:
            spec = OwnerSpec(owner)
        if atype:
            type_spec = TypeSpec(atype)
            spec = (spec & type_spec) if spec else type_spec

        page = self._repo.find(spec, page=1, page_size=1000)
        accounts = [a.get_info() for a in page.items]
        return ServiceResponse(200, {
            "accounts": accounts,
            "count":    len(accounts),
        })

    def _get_account(self, account_id: str) -> ServiceResponse:
        account = self._repo.find_by_id(account_id)
        if account is None:
            return ServiceResponse(404, {
                "error": f"Account {account_id} not found.",
                "code":  "ACCOUNT_NOT_FOUND",
            })
        info = account.get_info()
        # Include min_possible_balance for TransactionService validation
        info["min_possible_balance"] = account.min_possible_balance
        return ServiceResponse(200, info)

    def _create_account(self, request: ServiceRequest) -> ServiceResponse:
        body = request.body
        try:
            cmd = CreateAccountCommand(
                owner_name=body.get("owner_name", ""),
                account_type=body.get("account_type", "current"),
                initial_deposit=float(body.get("initial_deposit", 0.0)),
                initiated_by=body.get("initiated_by", "api"),
            )
        except (ValueError, TypeError) as e:
            return ServiceResponse(422, {"error": str(e), "code": "VALIDATION_ERROR"})

        result = self._app.create_account(cmd)
        if result.success:
            return ServiceResponse(201, result.data)
        return ServiceResponse(422, {"error": result.error, "code": result.error_code})

    def _update_balance(self, account_id: str, request: ServiceRequest) -> ServiceResponse:
        """
        Called by TransactionService after a successful transaction.
        Updates the account balance to the new value.

        Note: this is a simplified approach for Day 16.
        Day 18 (Message Queue) will use events instead of direct PATCH calls.
        """
        account = self._repo.find_by_id(account_id)
        if account is None:
            return ServiceResponse(404, {"error": f"Account {account_id} not found."})

        new_balance = request.body.get("balance")
        if new_balance is None:
            return ServiceResponse(422, {"error": "Missing 'balance' field."})

        # Validate against account constraints
        if new_balance < account.min_possible_balance:
            return ServiceResponse(422, {
                "error": (
                    f"Balance {new_balance:.2f} below minimum "
                    f"{account.min_possible_balance:.2f}."
                ),
                "code": "BALANCE_BELOW_MINIMUM",
            })

        # Apply balance update
        account._balance = float(new_balance)
        self._repo.save(account)

        return ServiceResponse(200, {
            "account_id": account_id,
            "balance":    account.balance,
            "updated":    True,
        })

    def _close_account(self, account_id: str) -> ServiceResponse:
        account = self._repo.find_by_id(account_id)
        if account is None:
            return ServiceResponse(404, {"error": f"Account {account_id} not found."})
        # Mark as closed (simplified — full implementation in production)
        return ServiceResponse(200, {"account_id": account_id, "status": "CLOSED"})

    # ------------------------------------------------------------------
    # Direct access for testing
    # ------------------------------------------------------------------

    @property
    def repository(self) -> InMemoryAccountRepository:
        return self._repo

    @property
    def app(self) -> BankApplicationService:
        return self._app
