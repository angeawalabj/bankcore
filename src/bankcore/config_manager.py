"""
BankCore — Day 01: Singleton Pattern
=====================================
ConfigManager: the single source of truth for all bank configuration.

Problem solved: multiple modules need access to the same configuration
(DB url, fee rates, transaction limits). Without a Singleton, each module
could hold a different version of the config — a silent bug waiting to happen.

Design decision: thread-safe Singleton using a class-level lock.
Trade-off: global state makes unit testing harder → solved via _reset() method.
"""

import os
import threading
from typing import Any


class ConfigManager:
    """
    Singleton configuration manager for BankCore.

    Usage:
        config = ConfigManager.get_instance()
        db_url = config.get("database.url")

    Only one instance exists for the lifetime of the application.
    All modules share the same configuration state.
    """

    _instance: "ConfigManager | None" = None
    _lock: threading.Lock = threading.Lock()

    # Default configuration — overridable via environment variables or set()
    _DEFAULTS: dict = {
        "database.url": "sqlite:///bankcore.db",
        "database.pool_size": 5,
        "fees.standard_transfer": 0.001,   # 0.1% per transfer
        "fees.international_transfer": 0.02, # 2% for international
        "fees.monthly_account": 0.0,         # free by default
        "limits.max_transfer_amount": 50_000.0,
        "limits.max_daily_transactions": 20,
        "limits.max_login_attempts": 3,
        "alerts.low_balance_threshold": 100.0,
        "alerts.large_transaction_threshold": 5_000.0,
        "environment": "development",
    }

    def __init__(self) -> None:
        # Private: use get_instance() instead
        self._config: dict = dict(self._DEFAULTS)

    @classmethod
    def get_instance(cls) -> "ConfigManager":
        """
        Return the single ConfigManager instance.
        Thread-safe: uses double-checked locking.
        """
        if cls._instance is None:
            with cls._lock:
                # Second check inside the lock — another thread may have
                # created the instance while we were waiting for the lock.
                if cls._instance is None:
                    cls._instance = cls()
                    cls._instance.load_from_env()
        return cls._instance

    def get(self, key: str, default: Any = None) -> Any:
        """
        Retrieve a configuration value by dot-notation key.

        Example:
            config.get("fees.standard_transfer")  # → 0.001
            config.get("missing.key", "fallback") # → "fallback"
        """
        return self._config.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """
        Override a configuration value at runtime.
        Useful for feature flags or dynamic reconfiguration.
        """
        self._config[key] = value

    def load_from_env(self) -> None:
        """
        Override defaults with environment variables.
        Convention: BANKCORE_DATABASE_URL → database.url

        Allows deployment-specific config without code changes.
        """
        env_mappings = {
            "BANKCORE_DATABASE_URL": "database.url",
            "BANKCORE_ENVIRONMENT": "environment",
            "BANKCORE_MAX_TRANSFER": "limits.max_transfer_amount",
            "BANKCORE_LOW_BALANCE_THRESHOLD": "alerts.low_balance_threshold",
        }
        for env_key, config_key in env_mappings.items():
            value = os.environ.get(env_key)
            if value is not None:
                # Attempt type coercion to match the default type
                default = self._config.get(config_key)
                if isinstance(default, float):
                    value = float(value)
                elif isinstance(default, int):
                    value = int(value)
                self._config[config_key] = value

    def all(self) -> dict:
        """Return a copy of the full configuration (read-only snapshot)."""
        return dict(self._config)

    @classmethod
    def _reset(cls) -> None:
        """
        Reset the Singleton for testing purposes ONLY.
        Never call this in production code.

        Why expose this? Because untestable code is untrustworthy code.
        We accept the trade-off: a test-only backdoor to avoid global state
        leaking between test cases.
        """
        with cls._lock:
            cls._instance = None

    def __repr__(self) -> str:
        env = self._config.get("environment", "unknown")
        return f"ConfigManager(env={env}, keys={len(self._config)})"


# ---------------------------------------------------------------------------
# Quick demo — run directly with: python -m bankcore.config_manager
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # First access — instance is created
    config = ConfigManager.get_instance()
    print(f"Instance created: {config}")

    # Second access — same instance returned
    config2 = ConfigManager.get_instance()
    print(f"Same instance? {config is config2}")  # → True

    # Read a value
    print(f"Max transfer: {config.get('limits.max_transfer_amount'):,.0f} EUR")
    print(f"Standard fee: {config.get('fees.standard_transfer') * 100:.1f}%")

    # Override at runtime
    config.set("environment", "production")
    print(f"Environment updated: {config.get('environment')}")

    # Verify the other reference also sees the change
    print(f"Seen from config2: {config2.get('environment')}")  # → production
