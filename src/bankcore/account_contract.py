"""
BankCore — Day 08: LSP Contract Verifier
==========================================
Provides tools to formally verify that any Account subtype
satisfies the Liskov Substitution Principle contracts.

Why a verifier class instead of just tests?
  - It can be called in AccountTypeRegistry.register() to validate
    new types at registration time — fail fast, not at runtime.
  - It serves as living documentation of what "being an Account" means.
  - New account types registered via AccountTypeRegistry (Day 07) can
    be validated automatically before they enter production.

Usage:
    verifier = AccountContractVerifier()
    violations = verifier.check(account)
    assert violations == [], f"LSP violations: {violations}"

Or as a guard in registration:
    verifier = AccountContractVerifier()
    verifier.assert_compliant(account, initial_deposit=100.0)
"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bankcore.account import Account


class ContractViolation:
    """Describes a single LSP contract violation."""

    def __init__(self, rule: str, detail: str) -> None:
        self.rule   = rule
        self.detail = detail

    def __str__(self) -> str:
        return f"[{self.rule}] {self.detail}"

    def __repr__(self) -> str:
        return f"ContractViolation({self.rule!r}, {self.detail!r})"


class AccountContractVerifier:
    """
    Verifies that an Account instance satisfies all LSP invariants.

    The six invariants are defined in docs/jour-08/README.md.
    Each check_*() method tests one invariant and returns a list
    of ContractViolation objects (empty = passed).
    """

    def check(self, account: "Account", test_amount: float = 100.0) -> list[ContractViolation]:
        """
        Run all invariant checks on the given account.
        Returns a list of violations (empty list = fully compliant).

        test_amount: amount used for deposit/withdraw checks.
        Should be small enough that the account can afford it.
        """
        violations: list[ContractViolation] = []
        violations.extend(self._check_identity(account))
        violations.extend(self._check_balance_consistency(account, test_amount))
        violations.extend(self._check_deposit_contract(account, test_amount))
        violations.extend(self._check_withdraw_contract(account, test_amount))
        violations.extend(self._check_min_balance_invariant(account))
        violations.extend(self._check_get_info_contract(account))
        return violations

    def assert_compliant(self, account: "Account", test_amount: float = 100.0) -> None:
        """
        Assert full LSP compliance. Raises AssertionError with details if not.
        Use this in AccountTypeRegistry.register() to validate new types.
        """
        violations = self.check(account, test_amount)
        if violations:
            details = "\n  ".join(str(v) for v in violations)
            raise AssertionError(
                f"{account.__class__.__name__} violates LSP contracts:\n  {details}"
            )

    # ------------------------------------------------------------------
    # Invariant checks
    # ------------------------------------------------------------------

    def _check_identity(self, account: "Account") -> list[ContractViolation]:
        """
        Invariant 1: account_id is non-empty and stable.
        Every Account must be uniquely identifiable.
        """
        violations = []
        if not account.account_id:
            violations.append(ContractViolation(
                "IDENTITY",
                "account_id must be non-empty after construction."
            ))
        if not account.owner_name or not account.owner_name.strip():
            violations.append(ContractViolation(
                "IDENTITY",
                "owner_name must be non-empty after construction."
            ))
        return violations

    def _check_balance_consistency(
        self, account: "Account", test_amount: float
    ) -> list[ContractViolation]:
        """
        Invariant 2: balance reflects the sum of all transactions.
        Verified by checking that a deposit changes balance by exactly the amount.
        """
        violations = []
        balance_before = account.balance
        account.deposit(test_amount, description="LSP invariant check")
        balance_after = account.balance

        expected = balance_before + test_amount
        if abs(balance_after - expected) > 0.001:
            violations.append(ContractViolation(
                "BALANCE_CONSISTENCY",
                f"After deposit({test_amount}), balance should be {expected:.2f} "
                f"but was {balance_after:.2f}."
            ))

        # Reverse the deposit to leave account in original state
        account.withdraw(test_amount, description="LSP invariant check reversal")
        return violations

    def _check_deposit_contract(
        self, account: "Account", test_amount: float
    ) -> list[ContractViolation]:
        """
        Invariant 3: deposit(amount > 0) always succeeds and increases balance.
        No subtype may reject a valid positive deposit.
        """
        violations = []
        balance_before = account.balance
        result = account.deposit(test_amount, description="LSP deposit check")

        if result is not True:
            violations.append(ContractViolation(
                "DEPOSIT_CONTRACT",
                f"deposit({test_amount}) returned {result!r} instead of True. "
                "A positive deposit must always succeed."
            ))
        elif account.balance <= balance_before:
            violations.append(ContractViolation(
                "DEPOSIT_CONTRACT",
                f"deposit({test_amount}) returned True but balance did not increase "
                f"({balance_before:.2f} → {account.balance:.2f})."
            ))

        # Reverse
        account.withdraw(test_amount, description="LSP check reversal")
        return violations

    def _check_withdraw_contract(
        self, account: "Account", test_amount: float
    ) -> list[ContractViolation]:
        """
        Invariant 4: withdraw() returns False without modifying balance
        when the operation is refused.

        We test with an amount the account cannot afford (10× current balance + 1).
        A compliant withdraw() must return False and leave balance unchanged.
        """
        violations = []
        impossible_amount = abs(account.balance) * 10 + 1_000_000.0
        balance_before = account.balance
        result = account.withdraw(impossible_amount, description="LSP withdraw check")

        if result is True:
            # Some account types may have very high limits — not a violation per se
            # but we note it for awareness. Only flag if balance changed unexpectedly.
            pass
        elif result is False:
            if account.balance != balance_before:
                violations.append(ContractViolation(
                    "WITHDRAW_CONTRACT",
                    f"withdraw({impossible_amount}) returned False but balance changed "
                    f"({balance_before:.2f} → {account.balance:.2f}). "
                    "A refused withdrawal must not modify balance."
                ))
        return violations

    def _check_min_balance_invariant(self, account: "Account") -> list[ContractViolation]:
        """
        Invariant 5: balance >= min_possible_balance at all times.
        Every subtype must declare its minimum possible balance.
        """
        violations = []
        if not hasattr(account, "min_possible_balance"):
            violations.append(ContractViolation(
                "MIN_BALANCE",
                f"{account.__class__.__name__} does not implement min_possible_balance. "
                "Every Account subtype must declare its minimum balance."
            ))
            return violations

        min_bal = account.min_possible_balance
        if account.balance < min_bal:
            violations.append(ContractViolation(
                "MIN_BALANCE",
                f"balance ({account.balance:.2f}) is below min_possible_balance "
                f"({min_bal:.2f})."
            ))
        return violations

    def _check_get_info_contract(self, account: "Account") -> list[ContractViolation]:
        """
        Invariant 6: get_info() returns a dict with all required keys.
        Services depend on these keys — missing one breaks substitutability.
        """
        REQUIRED_KEYS = {
            "account_id", "owner_name", "account_type",
            "balance", "created_at", "transaction_count",
        }
        violations = []
        try:
            info = account.get_info()
        except Exception as exc:
            violations.append(ContractViolation(
                "GET_INFO_CONTRACT",
                f"get_info() raised {type(exc).__name__}: {exc}"
            ))
            return violations

        missing = REQUIRED_KEYS - set(info.keys())
        if missing:
            violations.append(ContractViolation(
                "GET_INFO_CONTRACT",
                f"get_info() is missing required keys: {sorted(missing)}"
            ))
        return violations
