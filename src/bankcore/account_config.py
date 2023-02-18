"""
BankCore — Day 06: AccountConfigResolver
==========================================
Extracted from AccountFactory as part of the SRP refactoring.

Before Day 06: AccountFactory read ConfigManager directly and decided
               which limits to apply to each account type.
After  Day 06: AccountConfigResolver owns that mapping logic.
               AccountFactory just calls resolver.resolve_*() methods.

Single responsibility: given an account type and the current configuration,
return the appropriate limits, fees, and rates.

This class becomes the single place to update when regulatory changes
affect account limits — AccountFactory doesn't need to change at all.
"""

from bankcore.config_manager import ConfigManager


class AccountConfigResolver:
    """
    Resolves account parameters (limits, fees, rates) from configuration.

    Day 07 (OCP): now reads ConfigProfile from AccountTypeRegistry
    instead of a hardcoded _DEFAULTS dict.
    Adding a new account type via AccountTypeRegistry automatically
    makes it visible here — zero modification required.
    """

    def __init__(self, config=None) -> None:
        # DIP: accept injected config; fall back to Singleton for backward compat
        if config is None:
            self._config = ConfigManager.get_instance()
        else:
            self._config = config

    def _profile(self, account_type: str):
        """Get ConfigProfile from AccountTypeRegistry (Day 07 — OCP)."""
        from bankcore.account_type_registry import AccountTypeRegistry, ConfigProfile
        try:
            return AccountTypeRegistry.get_profile(account_type)
        except ValueError:
            # Unknown type: return a safe default profile
            from bankcore.account_type_registry import ConfigProfile
            return ConfigProfile(account_type=account_type)

    def resolve_daily_limit(self, account_type: str) -> float:
        """
        Return the daily transfer limit for this account type.
        ConfigManager global override takes precedence over profile default.
        """
        global_limit = self._config.get("limits.max_transfer_amount")
        type_default = self._type_default(account_type, "daily_limit")
        if global_limit is not None:
            return min(global_limit, type_default)
        return type_default

    def resolve_overdraft(self, account_type: str) -> float:
        """Return the overdraft limit (negative number or 0.0)."""
        return self._type_default(account_type, "overdraft")

    def resolve_min_balance(self, account_type: str) -> float:
        """Return the minimum balance that must remain after a withdrawal."""
        return self._type_default(account_type, "min_balance")

    def resolve_monthly_fee(self, account_type: str) -> float:
        """Return the monthly maintenance fee in EUR."""
        config_fee = self._config.get("fees.monthly_account")
        if config_fee is not None:
            return config_fee
        return self._type_default(account_type, "monthly_fee")

    def resolve_interest_rate(self, account_type: str) -> float:
        """Return the annual interest rate (0.0 if not applicable)."""
        return self._type_default(account_type, "interest_rate")

    def resolve_all(self, account_type: str) -> dict:
        """Return all resolved parameters for an account type."""
        return {
            "daily_limit":   self.resolve_daily_limit(account_type),
            "overdraft":     self.resolve_overdraft(account_type),
            "min_balance":   self.resolve_min_balance(account_type),
            "monthly_fee":   self.resolve_monthly_fee(account_type),
            "interest_rate": self.resolve_interest_rate(account_type),
        }

    def _type_default(self, account_type: str, key: str) -> float:
        """Look up the default for a specific account type and parameter via registry."""
        profile = self._profile(account_type)
        return getattr(profile, key, 0.0)

    def supported_types(self) -> list[str]:
        """Returns all registered account types (Day 07 — OCP)."""
        from bankcore.account_type_registry import AccountTypeRegistry
        return AccountTypeRegistry.available()
