"""
Tests — Day 08: Liskov Substitution Principle
===============================================
Core assertion: every Account subtype is a valid substitute for Account.
Code that works with Account must work identically with any subtype.

Test strategy:
  1. AccountContractVerifier — each built-in type passes all invariants
  2. Substitutability — TransactionService works with all subtypes
  3. can_withdraw() — consistent behaviour across subtypes
  4. min_possible_balance — declared correctly by each subtype
  5. Violation detection — a broken subtype is caught by the verifier
  6. Future types — YouthAccount (from Day 07) also satisfies LSP
"""

import sys
import pytest

sys.path.insert(0, "src")

from bankcore.config_manager import ConfigManager
from bankcore.account_factory import AccountFactory
from bankcore.alert_system import AlertSystem
from bankcore.account_type_registry import AccountTypeRegistry, ConfigProfile
from bankcore.account import Account, CurrentAccount, SavingsAccount, ProAccount
from bankcore.account_contract import AccountContractVerifier, ContractViolation
from bankcore.transaction_service import TransactionService


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


# ---------------------------------------------------------------------------
# AccountContractVerifier — all built-in types pass every invariant
# ---------------------------------------------------------------------------

class TestContractVerifierBuiltInTypes:

    @pytest.fixture
    def verifier(self):
        return AccountContractVerifier()

    def test_current_account_passes_all_invariants(self, verifier):
        account = AccountFactory.create("current", "Alice", 1_000.0)
        violations = verifier.check(account, test_amount=100.0)
        assert violations == [], f"Violations: {violations}"

    def test_savings_account_passes_all_invariants(self, verifier):
        account = AccountFactory.create("savings", "Bob", 500.0)
        violations = verifier.check(account, test_amount=100.0)
        assert violations == [], f"Violations: {violations}"

    def test_pro_account_passes_all_invariants(self, verifier):
        account = AccountFactory.create("pro", "Acme Corp", 10_000.0)
        violations = verifier.check(account, test_amount=100.0)
        assert violations == [], f"Violations: {violations}"

    def test_assert_compliant_passes_for_all_built_in_types(self, verifier):
        for account_type in ["current", "savings", "pro"]:
            account = AccountFactory.create(account_type, "Test", 1_000.0)
            # Should not raise
            verifier.assert_compliant(account, test_amount=100.0)


# ---------------------------------------------------------------------------
# Invariant 1 — Identity
# ---------------------------------------------------------------------------

class TestIdentityInvariant:

    def test_all_types_have_non_empty_account_id(self):
        for t in ["current", "savings", "pro"]:
            account = AccountFactory.create(t, "Test", 100.0)
            assert account.account_id
            assert len(account.account_id) > 0

    def test_account_ids_are_unique_across_types(self):
        accounts = [AccountFactory.create(t, "Test", 100.0)
                    for t in ["current", "savings", "pro"]]
        ids = [a.account_id for a in accounts]
        assert len(set(ids)) == 3   # all unique

    def test_owner_name_preserved_exactly(self):
        for t in ["current", "savings", "pro"]:
            account = AccountFactory.create(t, "Alice Martin", 100.0)
            assert account.owner_name == "Alice Martin"


# ---------------------------------------------------------------------------
# Invariant 2 & 3 — Balance consistency and deposit contract
# ---------------------------------------------------------------------------

class TestDepositContract:
    """
    LSP: deposit(amount > 0) must ALWAYS succeed and increase balance.
    This is an unconditional guarantee on Account — no subtype may weaken it.
    """

    @pytest.mark.parametrize("account_type,initial", [
        ("current", 0.0),
        ("savings", 0.0),    # even starting at 0 — deposit must work
        ("pro",     0.0),
    ])
    def test_deposit_always_succeeds(self, account_type, initial):
        account = AccountFactory.create(account_type, "Test", initial)
        result = account.deposit(200.0)
        assert result is True

    @pytest.mark.parametrize("account_type", ["current", "savings", "pro"])
    def test_deposit_always_increases_balance(self, account_type):
        account = AccountFactory.create(account_type, "Test", 500.0)
        before = account.balance
        account.deposit(300.0)
        assert account.balance == before + 300.0

    @pytest.mark.parametrize("account_type", ["current", "savings", "pro"])
    def test_deposit_zero_always_fails(self, account_type):
        account = AccountFactory.create(account_type, "Test", 500.0)
        result = account.deposit(0.0)
        assert result is False

    @pytest.mark.parametrize("account_type", ["current", "savings", "pro"])
    def test_deposit_negative_always_fails(self, account_type):
        account = AccountFactory.create(account_type, "Test", 500.0)
        result = account.deposit(-100.0)
        assert result is False


# ---------------------------------------------------------------------------
# Invariant 4 — Withdraw contract: False = no side effect
# ---------------------------------------------------------------------------

class TestWithdrawContract:
    """
    LSP: withdraw() returning False must NEVER modify balance.
    """

    def test_refused_withdrawal_leaves_balance_unchanged_current(self):
        account = AccountFactory.create("current", "Alice", 100.0)
        before = account.balance
        account.withdraw(1_000_000.0)   # impossible amount
        assert account.balance == before

    def test_refused_withdrawal_leaves_balance_unchanged_savings(self):
        account = AccountFactory.create("savings", "Bob", 100.0)
        before = account.balance
        account.withdraw(90.0)   # would drop below 50 EUR min
        assert account.balance == before

    def test_refused_withdrawal_leaves_balance_unchanged_pro(self):
        account = AccountFactory.create("pro", "Acme", 0.0)
        before = account.balance
        account.withdraw(6_000.0)   # would exceed -5000 overdraft limit
        assert account.balance == before


# ---------------------------------------------------------------------------
# Invariant 5 — min_possible_balance
# ---------------------------------------------------------------------------

class TestMinPossibleBalance:

    def test_current_min_balance_is_zero(self):
        account = AccountFactory.create("current", "Alice", 500.0)
        assert account.min_possible_balance == 0.0

    def test_savings_min_balance_equals_min_balance_attr(self):
        account = AccountFactory.create("savings", "Bob", 500.0)
        assert account.min_possible_balance == account.min_balance

    def test_savings_default_min_balance_is_fifty(self):
        account = AccountFactory.create("savings", "Bob", 500.0)
        assert account.min_possible_balance == 50.0

    def test_pro_min_balance_equals_overdraft_limit(self):
        account = AccountFactory.create("pro", "Acme", 0.0)
        assert account.min_possible_balance == account.overdraft_limit

    def test_pro_default_overdraft_limit(self):
        account = AccountFactory.create("pro", "Acme", 0.0)
        assert account.min_possible_balance == -5_000.0

    @pytest.mark.parametrize("account_type,initial", [
        ("current", 500.0),
        ("savings", 500.0),
        ("pro",     500.0),
    ])
    def test_balance_never_below_min_possible(self, account_type, initial):
        """
        After any sequence of operations, balance >= min_possible_balance.
        """
        account = AccountFactory.create(account_type, "Test", initial)
        # Try many withdrawals
        for amount in [100.0, 200.0, 1_000.0, 5_000.0, 999_999.0]:
            account.withdraw(amount)
        assert account.balance >= account.min_possible_balance


# ---------------------------------------------------------------------------
# Invariant 6 — get_info() contract
# ---------------------------------------------------------------------------

class TestGetInfoContract:
    """
    LSP: get_info() must always return the same required keys.
    Services depend on this dict's structure — a missing key breaks them.
    """

    REQUIRED_KEYS = {
        "account_id", "owner_name", "account_type",
        "balance", "created_at", "transaction_count",
    }

    @pytest.mark.parametrize("account_type", ["current", "savings", "pro"])
    def test_get_info_has_all_required_keys(self, account_type):
        account = AccountFactory.create(account_type, "Test", 500.0)
        info = account.get_info()
        missing = self.REQUIRED_KEYS - set(info.keys())
        assert missing == set(), f"Missing keys: {missing}"

    @pytest.mark.parametrize("account_type", ["current", "savings", "pro"])
    def test_get_info_balance_matches_account_balance(self, account_type):
        account = AccountFactory.create(account_type, "Test", 750.0)
        assert account.get_info()["balance"] == account.balance

    @pytest.mark.parametrize("account_type", ["current", "savings", "pro"])
    def test_get_info_account_type_matches(self, account_type):
        account = AccountFactory.create(account_type, "Test", 500.0)
        assert account.get_info()["account_type"] == account_type


# ---------------------------------------------------------------------------
# can_withdraw() — consistent behaviour across subtypes
# ---------------------------------------------------------------------------

class TestCanWithdraw:
    """
    can_withdraw() is a side-effect-free feasibility check.
    Its result must be consistent with withdraw()'s outcome.
    """

    @pytest.mark.parametrize("account_type", ["current", "savings", "pro"])
    def test_can_withdraw_consistent_with_withdraw(self, account_type):
        """
        If can_withdraw(amount) returns True, withdraw(amount) must succeed.
        If can_withdraw(amount) returns False, withdraw(amount) must fail.
        Core LSP guarantee: no inconsistency between check and execution.
        """
        account = AccountFactory.create(account_type, "Test", 1_000.0)
        for amount in [50.0, 500.0, 999.0, 1_001.0, 100_000.0]:
            balance_before = account.balance
            can = account.can_withdraw(amount)
            did = account.withdraw(amount, "LSP consistency check")

            assert can == did, (
                f"{account_type}.can_withdraw({amount}) = {can} "
                f"but withdraw({amount}) = {did}"
            )
            # Restore balance if withdraw succeeded
            if did:
                account.deposit(amount, "LSP restore")

    def test_can_withdraw_zero_always_false(self):
        for t in ["current", "savings", "pro"]:
            account = AccountFactory.create(t, "Test", 500.0)
            assert account.can_withdraw(0.0) is False

    def test_can_withdraw_negative_always_false(self):
        for t in ["current", "savings", "pro"]:
            account = AccountFactory.create(t, "Test", 500.0)
            assert account.can_withdraw(-100.0) is False

    def test_can_withdraw_does_not_modify_balance(self):
        for t in ["current", "savings", "pro"]:
            account = AccountFactory.create(t, "Test", 500.0)
            before = account.balance
            account.can_withdraw(100.0)
            account.can_withdraw(1_000_000.0)
            assert account.balance == before


# ---------------------------------------------------------------------------
# Substitutability — TransactionService works with any Account subtype
# ---------------------------------------------------------------------------

class TestSubstitutability:
    """
    The definitive LSP test: code written for Account works with all subtypes.
    TransactionService never checks isinstance() — it treats all accounts equally.
    """

    def test_transaction_service_deposits_to_all_types(self):
        service = TransactionService()
        for account_type in ["current", "savings", "pro"]:
            account = AccountFactory.create(account_type, "Test", 0.0)
            result  = service.deposit(account, 500.0)
            assert result["success"] is True, \
                f"deposit failed for {account_type}: {result}"

    def test_transaction_service_withdraws_from_all_types(self):
        service = TransactionService()
        for account_type in ["current", "savings", "pro"]:
            account = AccountFactory.create(account_type, "Test", 1_000.0)
            result  = service.withdraw(account, 200.0)
            assert result["success"] is True, \
                f"withdraw failed for {account_type}: {result}"

    def test_transaction_service_transfers_between_all_type_combinations(self):
        service = TransactionService()
        types   = ["current", "savings", "pro"]

        for from_type in types:
            for to_type in types:
                sender   = AccountFactory.create(from_type, "Sender",   2_000.0)
                receiver = AccountFactory.create(to_type,   "Receiver", 1_000.0)
                result   = service.transfer(sender, receiver, 100.0)
                assert result["success"] is True, \
                    f"transfer {from_type}→{to_type} failed: {result}"

    def test_get_info_usable_without_isinstance(self):
        """
        Services that call get_info() never need to know the concrete type.
        This is the practical test of LSP: polymorphic code that just works.
        """
        accounts = [
            AccountFactory.create("current", "Alice", 1_000.0),
            AccountFactory.create("savings", "Bob",   2_000.0),
            AccountFactory.create("pro",     "Acme",  5_000.0),
        ]

        # Code written for Account — no isinstance, no type checks
        def summarize(account: Account) -> str:
            info = account.get_info()
            return (f"{info['owner_name']} ({info['account_type']}): "
                    f"{info['balance']:.2f} EUR")

        summaries = [summarize(a) for a in accounts]
        assert len(summaries) == 3
        assert all(isinstance(s, str) for s in summaries)


# ---------------------------------------------------------------------------
# Violation detection — a broken subtype is caught
# ---------------------------------------------------------------------------

class TestViolationDetection:
    """
    The verifier must catch subtypes that violate LSP contracts.
    """

    def test_verifier_catches_missing_min_possible_balance(self):
        class BrokenAccount(CurrentAccount):
            """Forgot to implement min_possible_balance override."""
            # min_possible_balance is inherited from CurrentAccount → 0.0
            # This is actually fine, so we break deposit instead
            def deposit(self, amount, description=""):
                return False  # Violates: deposit(amount>0) must always succeed

        broken = BrokenAccount("Test", 500.0)
        verifier = AccountContractVerifier()
        violations = verifier.check(broken, test_amount=100.0)
        deposit_violations = [v for v in violations if "DEPOSIT" in v.rule]
        assert len(deposit_violations) > 0

    def test_verifier_catches_missing_get_info_key(self):
        class BrokenAccount(CurrentAccount):
            def get_info(self):
                info = super().get_info()
                del info["balance"]   # Removes required key
                return info

        broken = BrokenAccount("Test", 500.0)
        verifier = AccountContractVerifier()
        violations = verifier.check(broken, test_amount=100.0)
        info_violations = [v for v in violations if "GET_INFO" in v.rule]
        assert len(info_violations) > 0

    def test_assert_compliant_raises_on_violation(self):
        class BrokenAccount(CurrentAccount):
            def deposit(self, amount, description=""):
                return False

        broken = BrokenAccount("Test", 500.0)
        verifier = AccountContractVerifier()
        with pytest.raises(AssertionError, match="LSP contracts"):
            verifier.assert_compliant(broken, test_amount=100.0)


# ---------------------------------------------------------------------------
# Future types — new types registered via AccountTypeRegistry satisfy LSP
# ---------------------------------------------------------------------------

class TestFutureTypeLSP:

    def test_youth_account_passes_lsp_verifier(self):
        """
        YouthAccount (first introduced Day 07) must satisfy all LSP invariants.
        This test ensures OCP and LSP are compatible:
        freely extensible types must still honour the base contract.
        """
        class YouthAccount(CurrentAccount):
            DAILY_LIMIT = 500.0

            def __init__(self, owner, deposit=0.0):
                super().__init__(owner, deposit, daily_limit=self.DAILY_LIMIT)

            @property
            def account_type(self): return "youth"

            @property
            def min_possible_balance(self): return 0.0

        youth = YouthAccount("Charlie", 300.0)
        verifier = AccountContractVerifier()
        violations = verifier.check(youth, test_amount=50.0)
        assert violations == [], f"YouthAccount LSP violations: {violations}"

    def test_youth_account_substitutable_in_transaction_service(self):
        class YouthAccount(CurrentAccount):
            @property
            def account_type(self): return "youth"
            @property
            def min_possible_balance(self): return 0.0

        youth   = YouthAccount("Charlie", 500.0)
        regular = AccountFactory.create("current", "Alice", 500.0)
        service = TransactionService()

        # TransactionService must work identically with both
        r1 = service.deposit(youth,   100.0)
        r2 = service.deposit(regular, 100.0)
        assert r1["success"] == r2["success"] == True
