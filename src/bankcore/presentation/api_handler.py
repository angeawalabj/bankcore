"""
BankCore — Day 15: BankAPIHandler (Primary Adapter)
=====================================================
Simulates a REST API adapter for BankCore.

This is NOT a real HTTP server — it's a pure Python class that
mimics the request/response cycle of an API handler.

Purpose:
  - Demonstrates how BankCore can be driven by an HTTP API
  - Provides a testable API surface without a real web framework
  - Maps HTTP-style requests (method, path, body) to Commands
  - Returns HTTP-style responses (status_code, body dict)

In production (Day 16+ Microservices), this becomes:
  - FastAPI route handlers
  - Flask blueprints
  - Django views

Hexagonal Architecture rule:
    BankAPIHandler contains ZERO business logic.
    It translates HTTP requests to Commands and Commands results to HTTP responses.
    Status codes (200, 201, 400, 404, 422) come from the result, not business rules.
"""

from __future__ import annotations
from typing import Any, Optional

from bankcore.application.commands import (
    CreateAccountCommand, DepositCommand,
    WithdrawCommand, TransferCommand,
)
from bankcore.application.use_cases import BankApplicationService


class HTTPResponse:
    """Simulated HTTP response."""

    def __init__(self, status_code: int, body: dict) -> None:
        self.status_code = status_code
        self.body        = body

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def __repr__(self) -> str:
        return f"HTTPResponse({self.status_code}, {self.body})"


class BankAPIHandler:
    """
    REST API adapter for BankCore.

    Maps HTTP-style requests to Commands and returns HTTP-style responses.
    No real HTTP server — pure Python for testing and demonstration.

    Routes simulated:
        POST   /accounts               → create_account
        GET    /accounts               → list_accounts
        GET    /accounts/{id}          → get_account
        POST   /accounts/{id}/deposit  → deposit
        POST   /accounts/{id}/withdraw → withdraw
        POST   /transfers              → transfer
    """

    def __init__(self, app: BankApplicationService) -> None:
        self._app = app

    # ------------------------------------------------------------------
    # Account endpoints
    # ------------------------------------------------------------------

    def create_account(self, body: dict) -> HTTPResponse:
        """POST /accounts"""
        try:
            cmd = CreateAccountCommand(
                owner_name=body.get("owner_name", ""),
                account_type=body.get("account_type", "current"),
                initial_deposit=float(body.get("initial_deposit", 0.0)),
                initiated_by=body.get("initiated_by", "api"),
            )
        except (ValueError, TypeError) as e:
            return HTTPResponse(422, {"error": str(e), "code": "VALIDATION_ERROR"})

        result = self._app.create_account(cmd)
        if result.success:
            return HTTPResponse(201, result.data)
        return self._error_response(result)

    def list_accounts(self) -> HTTPResponse:
        """GET /accounts"""
        accounts = self._app.list_accounts()
        return HTTPResponse(200, {"accounts": accounts, "count": len(accounts)})

    def get_account(self, account_id: str) -> HTTPResponse:
        """GET /accounts/{account_id}"""
        info = self._app.get_account(account_id)
        if info is None:
            return HTTPResponse(404, {
                "error": f"Account {account_id} not found.",
                "code": "ACCOUNT_NOT_FOUND",
            })
        return HTTPResponse(200, info)

    # ------------------------------------------------------------------
    # Transaction endpoints
    # ------------------------------------------------------------------

    def deposit(self, account_id: str, body: dict) -> HTTPResponse:
        """POST /accounts/{account_id}/deposit"""
        try:
            cmd = DepositCommand(
                account_id=account_id,
                amount=float(body.get("amount", 0)),
                initiated_by=body.get("initiated_by", "api"),
                description=body.get("description", "API deposit"),
            )
        except (ValueError, TypeError) as e:
            return HTTPResponse(422, {"error": str(e), "code": "VALIDATION_ERROR"})

        result = self._app.deposit(cmd)
        if result.success:
            return HTTPResponse(200, result.data)
        return self._error_response(result)

    def withdraw(self, account_id: str, body: dict) -> HTTPResponse:
        """POST /accounts/{account_id}/withdraw"""
        try:
            cmd = WithdrawCommand(
                account_id=account_id,
                amount=float(body.get("amount", 0)),
                initiated_by=body.get("initiated_by", "api"),
                description=body.get("description", "API withdrawal"),
            )
        except (ValueError, TypeError) as e:
            return HTTPResponse(422, {"error": str(e), "code": "VALIDATION_ERROR"})

        result = self._app.withdraw(cmd)
        if result.success:
            return HTTPResponse(200, result.data)
        return self._error_response(result)

    def transfer(self, body: dict) -> HTTPResponse:
        """POST /transfers"""
        try:
            cmd = TransferCommand(
                from_account_id=body.get("from_account_id", ""),
                to_account_id=body.get("to_account_id", ""),
                amount=float(body.get("amount", 0)),
                initiated_by=body.get("initiated_by", "api"),
                description=body.get("description", "API transfer"),
            )
        except (ValueError, TypeError) as e:
            return HTTPResponse(422, {"error": str(e), "code": "VALIDATION_ERROR"})

        result = self._app.transfer(cmd)
        if result.success:
            return HTTPResponse(200, result.data)
        return self._error_response(result)

    # ------------------------------------------------------------------
    # Response helpers
    # ------------------------------------------------------------------

    def _error_response(self, result) -> HTTPResponse:
        """Map a failed UseCaseResult to an HTTP error response."""
        code_to_status = {
            "ACCOUNT_NOT_FOUND":    404,
            "INVALID_ACCOUNT_TYPE": 422,
            "TRANSFER_REJECTED":    422,
            "DEPOSIT_REJECTED":     422,
            "WITHDRAWAL_REJECTED":  422,
            "NOT_INTEREST_BEARING": 422,
            "BUSINESS_ERROR":       400,
        }
        status = code_to_status.get(result.error_code, 400)
        return HTTPResponse(status, {
            "error": result.error,
            "code":  result.error_code,
        })
