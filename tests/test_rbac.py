"""
Tests — Day 27: RBAC
======================
Test strategy:
  1. Principal — role, permissions, limits
  2. Permission check — has_permission per role
  3. AuthorizationService — authorize, can, limits
  4. AuthorizationError and LimitExceededError
  5. SecuredBankApplicationService — wraps Use Cases with authz
  6. Audit log integration — decisions recorded
  7. Role hierarchy — Teller ⊂ Manager ⊂ Admin
"""

import sys
import pytest

sys.path.insert(0, "src")

from bankcore.config_manager import ConfigManager
from bankcore.alert_system import AlertSystem
from bankcore.account_type_registry import AccountTypeRegistry
from bankcore.account_factory import AccountFactory
from bankcore.protocols import FakeConfig, SpyAlertSystem
from bankcore.container import BankContainer
from bankcore.application.use_cases import BankApplicationService
from bankcore.infrastructure.persistence.in_memory_repository import InMemoryAccountRepository
from bankcore.application.commands import (
    CreateAccountCommand, DepositCommand, WithdrawCommand, TransferCommand,
)
from bankcore.application.rbac.rbac import (
    Permission, Role, Principal, ROLE_PERMISSIONS,
    AuthorizationService, AuthorizationError, LimitExceededError,
    SecuredBankApplicationService,
    teller, manager, admin, system_principal,
)
from bankcore.infrastructure.audit.audit_log import ImmutableAuditLog


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
def authz():
    return AuthorizationService()


@pytest.fixture
def app_service():
    container = BankContainer.build_for_testing()
    repo = InMemoryAccountRepository()
    return BankApplicationService(container, registry=repo)


@pytest.fixture
def secured(app_service, authz):
    return SecuredBankApplicationService(app_service, authz)


@pytest.fixture
def alice_id(secured):
    result = secured.create_account(
        CreateAccountCommand("Alice", "current", 2_000.0, "system"),
        principal=admin("admin-1", "admin"),
    )
    return result.data["account_id"]


@pytest.fixture
def bob_id(secured):
    result = secured.create_account(
        CreateAccountCommand("Bob", "savings", 1_000.0, "system"),
        principal=admin("admin-1", "admin"),
    )
    return result.data["account_id"]


# ---------------------------------------------------------------------------
# Principal
# ---------------------------------------------------------------------------

class TestPrincipal:

    def test_teller_has_deposit_permission(self):
        p = teller("T1", "john")
        assert p.has_permission(Permission.DEPOSIT) is True

    def test_teller_does_not_have_transfer(self):
        p = teller("T1", "john")
        assert p.has_permission(Permission.TRANSFER) is False

    def test_teller_does_not_have_create_account(self):
        p = teller("T1", "john")
        assert p.has_permission(Permission.CREATE_ACCOUNT) is False

    def test_manager_has_transfer(self):
        p = manager("M1", "jane")
        assert p.has_permission(Permission.TRANSFER) is True

    def test_manager_does_not_have_create_account(self):
        p = manager("M1", "jane")
        assert p.has_permission(Permission.CREATE_ACCOUNT) is False

    def test_admin_has_all_permissions(self):
        p = admin("A1", "boss")
        for permission in Permission:
            assert p.has_permission(permission) is True

    def test_system_has_all_permissions(self):
        p = system_principal()
        for permission in Permission:
            assert p.has_permission(permission) is True

    def test_principal_is_immutable(self):
        p = teller("T1", "john")
        with pytest.raises(Exception):
            p.role = Role.ADMIN

    def test_get_limit_default(self):
        p = teller("T1", "john", transfer_limit=5_000.0)
        # Key "transfer" is set by teller factory — returns configured limit
        assert p.get_limit("transfer") == 5_000.0
        # Unknown key returns default
        assert p.get_limit("unknown_op", default=1_000.0) == 1_000.0

    def test_get_limit_configured(self):
        p = teller("T1", "john", transfer_limit=5_000.0)
        assert p.get_limit("transfer") == 5_000.0

    def test_str_representation(self):
        p = teller("T1", "john")
        s = str(p)
        assert "john" in s
        assert "teller" in s


# ---------------------------------------------------------------------------
# Role hierarchy
# ---------------------------------------------------------------------------

class TestRoleHierarchy:

    def test_teller_permissions_subset_of_manager(self):
        teller_perms  = ROLE_PERMISSIONS[Role.TELLER]
        manager_perms = ROLE_PERMISSIONS[Role.MANAGER]
        assert teller_perms.issubset(manager_perms)

    def test_manager_permissions_subset_of_admin(self):
        manager_perms = ROLE_PERMISSIONS[Role.MANAGER]
        admin_perms   = ROLE_PERMISSIONS[Role.ADMIN]
        assert manager_perms.issubset(admin_perms)


# ---------------------------------------------------------------------------
# AuthorizationService
# ---------------------------------------------------------------------------

class TestAuthorizationService:

    def test_authorize_granted_for_valid_permission(self, authz):
        p = teller("T1", "john")
        authz.authorize(p, Permission.DEPOSIT, resource="ACC-001")
        assert authz.denied_count() == 0

    def test_authorize_raises_for_missing_permission(self, authz):
        p = teller("T1", "john")
        with pytest.raises(AuthorizationError) as exc_info:
            authz.authorize(p, Permission.TRANSFER, resource="ACC-001")
        assert "john" in str(exc_info.value)
        assert "transfer" in str(exc_info.value)

    def test_authorize_raises_limit_exceeded(self, authz):
        p = teller("T1", "john", transfer_limit=1_000.0)
        # Teller doesn't have TRANSFER, but test limit with WITHDRAW
        p2 = manager("M1", "jane", transfer_limit=500.0)
        with pytest.raises(LimitExceededError) as exc_info:
            authz.authorize(p2, Permission.TRANSFER, resource="ACC-001", amount=600.0)
        assert exc_info.value.amount == 600.0
        assert exc_info.value.limit  == 500.0

    def test_authorize_passes_within_limit(self, authz):
        p = manager("M1", "jane", transfer_limit=10_000.0)
        authz.authorize(p, Permission.TRANSFER, resource="ACC-001", amount=5_000.0)
        assert authz.denied_count() == 0

    def test_can_returns_bool_no_raise(self, authz):
        p = teller("T1", "john")
        assert authz.can(p, Permission.DEPOSIT)  is True
        assert authz.can(p, Permission.TRANSFER) is False

    def test_decisions_recorded(self, authz):
        p = teller("T1", "john")
        authz.authorize(p, Permission.DEPOSIT, resource="ACC-001")
        try:
            authz.authorize(p, Permission.TRANSFER, resource="ACC-001")
        except AuthorizationError:
            pass
        assert len(authz.decisions) == 2
        assert authz.decisions[0]["decision"] == "GRANTED"
        assert authz.decisions[1]["decision"] == "DENIED"

    def test_denied_count(self, authz):
        p = teller("T1", "john")
        for _ in range(3):
            try:
                authz.authorize(p, Permission.CREATE_ACCOUNT)
            except AuthorizationError:
                pass
        assert authz.denied_count() == 3

    def test_authorization_logged_to_audit_log(self):
        audit = ImmutableAuditLog(secret_key="test")
        authz = AuthorizationService(audit_log=audit)
        p     = teller("T1", "john")

        authz.authorize(p, Permission.DEPOSIT, resource="ACC-001")
        try:
            authz.authorize(p, Permission.TRANSFER, resource="ACC-001")
        except AuthorizationError:
            pass

        assert audit.count() == 2
        entries = audit.all_entries()
        assert entries[0].event_type == "AUTHZ_GRANTED"
        assert entries[1].event_type == "AUTHZ_DENIED"

        # Chain should be intact
        result = audit.verify_chain()
        assert result.is_valid is True


# ---------------------------------------------------------------------------
# SecuredBankApplicationService
# ---------------------------------------------------------------------------

class TestSecuredBankApplicationService:

    def test_admin_can_create_account(self, secured):
        result = secured.create_account(
            CreateAccountCommand("Carol", "current", 500.0, "admin"),
            principal=admin("A1", "boss"),
        )
        assert result.success is True

    def test_teller_cannot_create_account(self, secured):
        with pytest.raises(AuthorizationError):
            secured.create_account(
                CreateAccountCommand("Carol", "current", 500.0, "teller"),
                principal=teller("T1", "john"),
            )

    def test_teller_can_deposit(self, secured, alice_id):
        result = secured.deposit(
            DepositCommand(alice_id, 300.0, "teller"),
            principal=teller("T1", "john"),
        )
        assert result.success is True

    def test_teller_cannot_transfer(self, secured, alice_id, bob_id):
        with pytest.raises(AuthorizationError):
            secured.transfer(
                TransferCommand(alice_id, bob_id, 100.0, "teller"),
                principal=teller("T1", "john"),
            )

    def test_manager_can_transfer(self, secured, alice_id, bob_id):
        result = secured.transfer(
            TransferCommand(alice_id, bob_id, 500.0, "manager"),
            principal=manager("M1", "jane"),
        )
        assert result.success is True

    def test_manager_transfer_above_limit_fails(self, secured, alice_id, bob_id):
        m = manager("M1", "jane", transfer_limit=100.0)
        with pytest.raises(LimitExceededError):
            secured.transfer(
                TransferCommand(alice_id, bob_id, 500.0, "manager"),
                principal=m,
            )

    def test_teller_can_view_account(self, secured, alice_id):
        info = secured.get_account(alice_id, principal=teller("T1", "john"))
        assert info is not None
        assert info["owner_name"] == "Alice"

    def test_teller_cannot_list_all_accounts(self, secured):
        with pytest.raises(AuthorizationError):
            secured.list_accounts(principal=teller("T1", "john"))

    def test_manager_can_list_accounts(self, secured, alice_id):
        result = secured.list_accounts(principal=manager("M1", "jane"))
        assert isinstance(result, list)

    def test_system_principal_can_do_everything(self, secured, alice_id, bob_id):
        sys_p = system_principal()
        result = secured.transfer(
            TransferCommand(alice_id, bob_id, 1_000.0, "system"),
            principal=sys_p,
        )
        assert result.success is True

    def test_authz_decisions_tracked(self, secured, alice_id, bob_id, authz):
        count_before = len(authz.decisions)
        denied_before = authz.denied_count()

        secured.deposit(
            DepositCommand(alice_id, 100.0, "teller"),
            principal=teller("T1", "john"),
        )
        try:
            secured.transfer(
                TransferCommand(alice_id, bob_id, 100.0, "teller"),
                principal=teller("T1", "john"),
            )
        except AuthorizationError:
            pass

        assert len(authz.decisions) == count_before + 2
        assert authz.denied_count() == denied_before + 1
