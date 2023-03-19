"""
BankCore — Day 27: RBAC (Role-Based Access Control)
=====================================================
Controls who can do what in BankCore.

Design:
  - Permission: atomic capability ("transfer", "deposit", "create_account")
  - Role: named set of permissions (Teller, Manager, Admin)
  - Principal: authenticated entity with a role
  - AuthorizationContext: injected into Use Cases (DIP J10)
  - @requires_permission: decorator for Use Case methods

Roles hierarchy:
  Teller  → deposit, withdraw (limit 5000), view_account
  Manager → Teller + transfer (limit 50000), close_account, view_reports
  Admin   → Manager + create_account, manage_users, configure_system

Connection to previous days:
  - J10 (DIP): AuthorizationContext is a Protocol — injectable, testable
  - J11 (Use Cases): permission check wraps Use Case execution
  - J26 (Audit Log): every authorization decision is logged
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum, auto
from functools import wraps
from typing import Optional, Callable, Any


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------

class Permission(str, Enum):
    # Account operations
    VIEW_ACCOUNT    = "view_account"
    DEPOSIT         = "deposit"
    WITHDRAW        = "withdraw"
    TRANSFER        = "transfer"
    CLOSE_ACCOUNT   = "close_account"
    CREATE_ACCOUNT  = "create_account"

    # Administrative
    VIEW_REPORTS    = "view_reports"
    MANAGE_USERS    = "manage_users"
    CONFIGURE       = "configure_system"
    VIEW_AUDIT_LOG  = "view_audit_log"


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------

class Role(Enum):
    TELLER  = "teller"
    MANAGER = "manager"
    ADMIN   = "admin"
    SYSTEM  = "system"   # internal service calls


# Role → Permission mapping
ROLE_PERMISSIONS: dict[Role, set[Permission]] = {
    Role.TELLER: {
        Permission.VIEW_ACCOUNT,
        Permission.DEPOSIT,
        Permission.WITHDRAW,
    },
    Role.MANAGER: {
        Permission.VIEW_ACCOUNT,
        Permission.DEPOSIT,
        Permission.WITHDRAW,
        Permission.TRANSFER,
        Permission.CLOSE_ACCOUNT,
        Permission.VIEW_REPORTS,
        Permission.VIEW_AUDIT_LOG,
    },
    Role.ADMIN: {
        Permission.VIEW_ACCOUNT,
        Permission.DEPOSIT,
        Permission.WITHDRAW,
        Permission.TRANSFER,
        Permission.CLOSE_ACCOUNT,
        Permission.CREATE_ACCOUNT,
        Permission.VIEW_REPORTS,
        Permission.VIEW_AUDIT_LOG,
        Permission.MANAGE_USERS,
        Permission.CONFIGURE,
    },
    Role.SYSTEM: set(Permission),   # system has all permissions
}


# ---------------------------------------------------------------------------
# Principal
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Principal:
    """
    An authenticated entity requesting an operation.
    Immutable: a principal's identity cannot change mid-request.
    """
    user_id:   str
    username:  str
    role:      Role
    limits:    dict = field(default_factory=dict)   # e.g. {"transfer": 5000.0}

    def has_permission(self, permission: Permission) -> bool:
        return permission in ROLE_PERMISSIONS.get(self.role, set())

    def get_limit(self, operation: str, default: float = float("inf")) -> float:
        return self.limits.get(operation, default)

    def __str__(self) -> str:
        return f"{self.username}({self.role.value})"


# Convenience factory functions
def teller(user_id: str, username: str, transfer_limit: float = 5_000.0) -> Principal:
    return Principal(user_id, username, Role.TELLER,
                     limits={"transfer": transfer_limit, "withdraw": transfer_limit})

def manager(user_id: str, username: str, transfer_limit: float = 50_000.0) -> Principal:
    return Principal(user_id, username, Role.MANAGER,
                     limits={"transfer": transfer_limit})

def admin(user_id: str, username: str) -> Principal:
    return Principal(user_id, username, Role.ADMIN)

def system_principal() -> Principal:
    return Principal("system", "system", Role.SYSTEM)


# ---------------------------------------------------------------------------
# Authorization exceptions
# ---------------------------------------------------------------------------

class AuthorizationError(Exception):
    """Raised when a principal lacks a required permission."""

    def __init__(self, principal: Principal, permission: Permission) -> None:
        self.principal  = principal
        self.permission = permission
        super().__init__(
            f"Principal '{principal}' does not have permission '{permission.value}'."
        )


class LimitExceededError(Exception):
    """Raised when an operation exceeds the principal's allowed limit."""

    def __init__(self, principal: Principal, operation: str,
                 amount: float, limit: float) -> None:
        self.principal = principal
        self.operation = operation
        self.amount    = amount
        self.limit     = limit
        super().__init__(
            f"Principal '{principal}' limit exceeded for '{operation}': "
            f"{amount:.2f} > {limit:.2f}."
        )


# ---------------------------------------------------------------------------
# AuthorizationService
# ---------------------------------------------------------------------------

class AuthorizationService:
    """
    Checks permissions and limits for a principal.

    Used by Use Cases (J11) to guard operations before execution.
    Injected via constructor (DIP J10) — testable with fake principals.
    """

    def __init__(self, audit_log=None) -> None:
        self._audit = audit_log
        self._decisions: list[dict] = []

    def authorize(
        self,
        principal: Principal,
        permission: Permission,
        resource: str = "",
        amount: Optional[float] = None,
    ) -> None:
        """
        Authorize an operation. Raises on failure.
        Records the decision in the audit log (J26).
        """
        # Permission check
        if not principal.has_permission(permission):
            self._record_decision(principal, permission, resource, "DENIED", amount)
            raise AuthorizationError(principal, permission)

        # Limit check (for financial operations)
        if amount is not None:
            op_name = permission.value
            limit   = principal.get_limit(op_name)
            if amount > limit:
                self._record_decision(principal, permission, resource, "LIMIT_EXCEEDED", amount)
                raise LimitExceededError(principal, op_name, amount, limit)

        self._record_decision(principal, permission, resource, "GRANTED", amount)

    def can(self, principal: Principal, permission: Permission) -> bool:
        """Non-raising permission check for conditional UI/logic."""
        return principal.has_permission(permission)

    def _record_decision(
        self,
        principal: Principal,
        permission: Permission,
        resource: str,
        decision: str,
        amount: Optional[float],
    ) -> None:
        record = {
            "principal":  str(principal),
            "permission": permission.value,
            "resource":   resource,
            "decision":   decision,
            "amount":     amount,
        }
        self._decisions.append(record)

        if self._audit:
            self._audit.append(
                f"AUTHZ_{decision}",
                actor=principal.user_id,
                resource=resource or permission.value,
                payload=record,
            )

    @property
    def decisions(self) -> list[dict]:
        return list(self._decisions)

    def denied_count(self) -> int:
        return sum(1 for d in self._decisions if d["decision"] == "DENIED")


# ---------------------------------------------------------------------------
# @requires_permission decorator
# ---------------------------------------------------------------------------

def requires_permission(
    permission: Permission,
    amount_arg: Optional[str] = None,
    resource_arg: str = "account_id",
):
    """
    Decorator for Use Case methods that require authorization.

    Usage:
        class TransferUseCase:
            @requires_permission(Permission.TRANSFER, amount_arg="amount")
            def execute(self, command, principal: Principal):
                ...

    The decorated method must have a `principal: Principal` parameter.
    The AuthorizationService must be available as self._authz.
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            # Find principal in kwargs or first positional arg
            principal = kwargs.get("principal")
            if principal is None:
                for arg in args:
                    if isinstance(arg, Principal):
                        principal = arg
                        break

            if principal is None:
                raise ValueError(
                    f"@requires_permission: no Principal found for {func.__name__}"
                )

            # Find amount if specified
            amount = None
            if amount_arg:
                amount = kwargs.get(amount_arg)
                if amount is None:
                    for arg in args:
                        if isinstance(arg, (int, float)):
                            amount = float(arg)
                            break

            # Find resource
            resource = kwargs.get(resource_arg, "")

            # Authorize
            authz = getattr(self, "_authz", None)
            if authz is None:
                raise ValueError(
                    f"@requires_permission: {self.__class__.__name__} "
                    f"has no _authz attribute"
                )
            authz.authorize(principal, permission, resource=resource, amount=amount)

            return func(self, *args, **kwargs)
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Secured Use Case wrapper
# ---------------------------------------------------------------------------

class SecuredBankApplicationService:
    """
    Wraps BankApplicationService with RBAC enforcement.

    Every operation requires an authenticated Principal.
    Authorization is checked before delegating to the inner service.

    Connection to J11 (Use Cases): wraps BankApplicationService
    Connection to J10 (DIP): AuthorizationService injected
    Connection to J26 (Audit): every decision logged
    """

    def __init__(self, app_service, authz: AuthorizationService) -> None:
        self._app   = app_service
        self._authz = authz

    def deposit(self, command, principal: Principal):
        self._authz.authorize(
            principal, Permission.DEPOSIT,
            resource=command.account_id,
            amount=command.amount,
        )
        return self._app.deposit(command)

    def withdraw(self, command, principal: Principal):
        self._authz.authorize(
            principal, Permission.WITHDRAW,
            resource=command.account_id,
            amount=command.amount,
        )
        return self._app.withdraw(command)

    def transfer(self, command, principal: Principal):
        self._authz.authorize(
            principal, Permission.TRANSFER,
            resource=command.from_account_id,
            amount=command.amount,
        )
        return self._app.transfer(command)

    def create_account(self, command, principal: Principal):
        self._authz.authorize(
            principal, Permission.CREATE_ACCOUNT,
            resource=command.owner_name,
        )
        return self._app.create_account(command)

    def get_account(self, account_id: str, principal: Principal):
        self._authz.authorize(
            principal, Permission.VIEW_ACCOUNT,
            resource=account_id,
        )
        return self._app.get_account(account_id)

    def list_accounts(self, principal: Principal):
        self._authz.authorize(principal, Permission.VIEW_REPORTS)
        return self._app.list_accounts()
