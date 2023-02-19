"""
BankCore — Day 07: AccountTypeRegistry
========================================
Formalizes the extension point for account types.

Before Day 07: adding a new account type required modifying
  AccountFactory._register_defaults() AND AccountConfigResolver._DEFAULTS.

After Day 07: adding a new account type means calling
  AccountTypeRegistry.register(...) — zero existing files modified.

This is Open/Closed Principle applied concretely:
  - Open  : register() accepts any new AccountCreator + ConfigProfile
  - Closed : AccountFactory, AccountConfigResolver, all services are unchanged

The registry is the single source of truth for:
  1. How to instantiate each account type (creator function)
  2. What parameters apply to each account type (ConfigProfile)
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable, Optional

from bankcore.account import Account


# ---------------------------------------------------------------------------
# ConfigProfile — replaces the hardcoded _DEFAULTS dict in AccountConfigResolver
# ---------------------------------------------------------------------------

@dataclass
class ConfigProfile:
    """
    Configuration profile for one account type.
    Carries all parameters that AccountConfigResolver used to hardcode.

    Immutable by design: a profile is a specification, not a mutable config.
    If parameters change, register a new profile — don't mutate an existing one.
    """
    account_type:  str
    daily_limit:   float = 10_000.0
    overdraft:     float = 0.0
    min_balance:   float = 0.0
    monthly_fee:   float = 0.0
    interest_rate: float = 0.0

    def to_dict(self) -> dict:
        return {
            "daily_limit":   self.daily_limit,
            "overdraft":     self.overdraft,
            "min_balance":   self.min_balance,
            "monthly_fee":   self.monthly_fee,
            "interest_rate": self.interest_rate,
        }


# Type alias for creator functions
AccountCreator = Callable[[str, float], Account]


# ---------------------------------------------------------------------------
# AccountTypeRegistry
# ---------------------------------------------------------------------------

class AccountTypeRegistry:
    """
    Registry of all account types known to BankCore.

    Acts as the single extension point for account types.
    AccountFactory delegates to this registry — it no longer hardcodes types.

    Thread-safe: uses a lock for registration (write operations).
    Read operations (create, get_profile) are safe after startup.

    Usage — registering a new type (OCP: no existing file modified):
        AccountTypeRegistry.register(
            name="youth",
            creator=lambda owner, deposit: YouthAccount(owner, deposit),
            profile=ConfigProfile("youth", daily_limit=500.0, monthly_fee=0.0),
        )
    """

    _lock: threading.Lock = threading.Lock()
    _creators:  dict[str, AccountCreator] = {}
    _profiles:  dict[str, ConfigProfile]  = {}

    @classmethod
    def register(
        cls,
        name: str,
        creator: AccountCreator,
        profile: Optional[ConfigProfile] = None,
    ) -> None:
        """
        Register a new account type.

        Args:
            name    : unique identifier (e.g. "youth", "premium")
            creator : callable(owner_name, initial_deposit) → Account
            profile : ConfigProfile with limits/fees. Defaults to standard current profile.
        """
        if not name or not name.strip():
            raise ValueError("Account type name cannot be empty.")

        with cls._lock:
            cls._creators[name] = creator
            cls._profiles[name] = profile or ConfigProfile(account_type=name)

    @classmethod
    def create(cls, name: str, owner: str, initial_deposit: float = 0.0) -> Account:
        """
        Instantiate an account by type name.
        Raises ValueError if the type is not registered.
        """
        creator = cls._creators.get(name)
        if creator is None:
            available = ", ".join(sorted(cls._creators.keys()))
            raise ValueError(
                f"Unknown account type: '{name}'. Available: {available}"
            )
        return creator(owner, initial_deposit)

    @classmethod
    def get_profile(cls, name: str) -> ConfigProfile:
        """
        Return the ConfigProfile for an account type.
        Used by AccountConfigResolver as the source of truth.
        """
        profile = cls._profiles.get(name)
        if profile is None:
            raise ValueError(f"No profile registered for account type: '{name}'")
        return profile

    @classmethod
    def available(cls) -> list[str]:
        """Return all registered account type names."""
        return sorted(cls._creators.keys())

    @classmethod
    def is_registered(cls, name: str) -> bool:
        return name in cls._creators

    @classmethod
    def _reset(cls) -> None:
        """For testing only. Clears all registrations."""
        with cls._lock:
            cls._creators.clear()
            cls._profiles.clear()

    @classmethod
    def _register_defaults(cls) -> None:
        """
        Register the three built-in account types.
        Creators read AccountConfigResolver at instantiation time so that
        ConfigManager overrides (e.g. from env vars) are always respected.
        """
        from bankcore.account import CurrentAccount, SavingsAccount, ProAccount

        def create_current(owner, deposit):
            from bankcore.account_config import AccountConfigResolver
            resolver = AccountConfigResolver()
            return CurrentAccount(owner, deposit,
                                  daily_limit=resolver.resolve_daily_limit("current"))

        def create_savings(owner, deposit):
            from bankcore.account_config import AccountConfigResolver
            resolver = AccountConfigResolver()
            return SavingsAccount(owner, deposit,
                                  interest_rate=resolver.resolve_interest_rate("savings"),
                                  min_balance=resolver.resolve_min_balance("savings"))

        def create_pro(owner, deposit):
            from bankcore.account_config import AccountConfigResolver
            resolver = AccountConfigResolver()
            return ProAccount(owner, deposit,
                              overdraft_limit=resolver.resolve_overdraft("pro"),
                              daily_limit=resolver.resolve_daily_limit("pro"))

        cls.register("current", create_current,
            profile=ConfigProfile("current", daily_limit=10_000.0, monthly_fee=2.0))
        cls.register("savings", create_savings,
            profile=ConfigProfile("savings", daily_limit=float("inf"),
                                  min_balance=50.0, interest_rate=0.025))
        cls.register("pro", create_pro,
            profile=ConfigProfile("pro", daily_limit=50_000.0,
                                  overdraft=-5_000.0, monthly_fee=15.0))


# Initialize on import
AccountTypeRegistry._register_defaults()
