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

from typing import Callable, Optional
from bankcore.account import Account, CurrentAccount, SavingsAccount, ProAccount
from bankcore.account_config import AccountConfigResolver
from bankcore.config_manager import ConfigManager


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

    # Registry: maps account type strings to creator functions.
    # Using a dict instead of if/elif means adding a new type
    # requires zero changes to this class (Open/Closed — Day 07).
    _creators: dict[str, AccountCreator] = {}

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
        cls._creators[account_type] = creator
        # Also register in AccountTypeRegistry so create() delegates correctly
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
        Delegates to AccountTypeRegistry (Day 07 — OCP).
        """
        from bankcore.account_type_registry import AccountTypeRegistry
        AccountTypeRegistry._reset()
        AccountTypeRegistry._register_defaults()
        cls._creators = {}
        cls._register_defaults()

    @classmethod
    def _register_defaults(cls) -> None:
        """Register the three built-in account types.
        Day 06: uses AccountConfigResolver instead of reading ConfigManager directly.
        """
        resolver = AccountConfigResolver()

        def create_current(owner: str, deposit: float) -> CurrentAccount:
            return CurrentAccount(
                owner_name=owner,
                initial_deposit=deposit,
                daily_limit=resolver.resolve_daily_limit("current"),
            )

        def create_savings(owner: str, deposit: float) -> SavingsAccount:
            return SavingsAccount(
                owner_name=owner,
                initial_deposit=deposit,
                interest_rate=resolver.resolve_interest_rate("savings"),
                min_balance=resolver.resolve_min_balance("savings"),
            )

        def create_pro(owner: str, deposit: float) -> ProAccount:
            return ProAccount(
                owner_name=owner,
                initial_deposit=deposit,
                overdraft_limit=resolver.resolve_overdraft("pro"),
                daily_limit=resolver.resolve_daily_limit("pro"),
            )

        cls._creators["current"] = create_current
        cls._creators["savings"] = create_savings
        cls._creators["pro"] = create_pro


# ---------------------------------------------------------------------------
# Initialize the factory with default account types at import time
# ---------------------------------------------------------------------------
AccountFactory._register_defaults()


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
