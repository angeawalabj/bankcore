"""
BankCore — Day 02: Factory Pattern
=====================================
AccountFactory: the single point of account creation.

Problem solved: account creation logic was scattered across the codebase.
Each caller knew which class to instantiate and how to configure it.
Adding a new account type meant updating every caller.

Design decision: Factory Method with a dynamic registry.
- AccountFactory.create() is the only public API for account creation
- A registry dict maps type strings to creator functions
- New account types can be registered without modifying AccountFactory

Connection to Day 01: AccountFactory reads limits and fees from ConfigManager.
If config changes (e.g., via env var in production), new accounts
automatically reflect the updated rules.
"""

from typing import Callable
from bankcore.account import Account, CurrentAccount


# Type alias for creator functions stored in the registry
AccountCreator = Callable[..., Account]


class AccountFactory:
    """
    Creates BankCore accounts by type name.

    Usage:
        account = AccountFactory.create("savings", "Alice", initial_deposit=500.0)
        account = AccountFactory.create("current", "Bob")
        account = AccountFactory.create("pro", "Acme Corp", initial_deposit=10_000.0)

    The factory reads limits and fees from ConfigManager (Day 01),
    so production config changes are automatically applied to new accounts.
    """

    @classmethod
    def create(
        cls,
        account_type: str,
        owner_name: str,
        initial_deposit: float = 0.0,
    ) -> Account:
        """
        Create and return an account of the specified type.
        Delegates to AccountTypeRegistry (Day 07 — OCP).
        """
        from bankcore.account_type_registry import AccountTypeRegistry

        if not owner_name or not owner_name.strip():
            raise ValueError("Owner name cannot be empty.")
        if initial_deposit < 0:
            raise ValueError("Initial deposit cannot be negative.")

        return AccountTypeRegistry.create(account_type, owner_name.strip(), initial_deposit)

    @classmethod
    def register(cls, account_type: str, creator: AccountCreator) -> None:
        """
        Register a new account type.
        Day 07 (OCP): delegates to AccountTypeRegistry so create() finds it.
        """
        from bankcore.account_type_registry import AccountTypeRegistry, ConfigProfile
        if not account_type or not account_type.strip():
            raise ValueError("Account type identifier cannot be empty.")
        AccountTypeRegistry.register(
            name=account_type,
            creator=creator,
            profile=ConfigProfile(account_type=account_type),
        )

    @classmethod
    def available_types(cls) -> list[str]:
        """Return all registered account type identifiers via AccountTypeRegistry (Day 07)."""
        from bankcore.account_type_registry import AccountTypeRegistry
        return AccountTypeRegistry.available()

    @classmethod
    def _reset_registry(cls) -> None:
        """
        Reset the registry to default state.
        For testing only — never call in production.
        Delegates entirely to AccountTypeRegistry (Day 07 — OCP), which
        owns and registers the three built-in account types itself.
        """
        from bankcore.account_type_registry import AccountTypeRegistry
        AccountTypeRegistry._reset()
        AccountTypeRegistry._register_defaults()


# ---------------------------------------------------------------------------
# Quick demo — run: python -m bankcore.account_factory
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=== BankCore — AccountFactory Demo ===\n")

    # Create one of each type
    accounts = [
        AccountFactory.create("current", "Alice Martin", initial_deposit=1_000.0),
        AccountFactory.create("savings", "Bob Dupont",   initial_deposit=5_000.0),
        AccountFactory.create("pro",     "Acme Corp",    initial_deposit=20_000.0),
    ]

    for account in accounts:
        info = account.get_info()
        print(f"[{info['account_type'].upper():8}] {info['owner_name']:15} "
              f"ID: {info['account_id']}  Balance: {info['balance']:>10,.2f} EUR")

    print()

    # Demonstrate that the factory enforces business rules
    savings = accounts[1]
    print(f"Savings balance: {savings.balance:.2f} EUR")
    print(f"Withdraw 4 960 EUR (would breach 50 EUR minimum): "
          f"{'OK' if savings.withdraw(4_960.0) else 'REFUSED'}")
    print(f"Withdraw 100 EUR: {'OK' if savings.withdraw(100.0) else 'REFUSED'}")
    print(f"Savings balance after: {savings.balance:.2f} EUR")

    print()

    # Demonstrate extensibility — register a new type without modifying AccountFactory
    class YouthAccount(CurrentAccount):
        """Example: a new account type added without touching AccountFactory."""
        DAILY_LIMIT = 500.0
        MONTHLY_FEE = 0.0

        @property
        def account_type(self) -> str:
            return "youth"

    AccountFactory.register(
        "youth",
        lambda owner, deposit: YouthAccount(owner, deposit, daily_limit=500.0)
    )

    youth = AccountFactory.create("youth", "Charlie (16)", initial_deposit=200.0)
    print(f"New type registered and created: {youth}")
    print(f"Available types: {AccountFactory.available_types()}")
