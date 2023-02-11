"""
Tests — Day 01: ConfigManager Singleton
========================================
These tests verify the three guarantees of the Singleton pattern:
  1. Uniqueness       — only one instance exists
  2. Global access    — reachable from anywhere without passing a reference
  3. Lazy init        — instance created only when first needed

Architecture note: we use _reset() between tests to avoid state leakage.
This is the trade-off documented in config_manager.py: testability requires
a controlled backdoor into the Singleton.
"""

import os
import pytest

# Adjust path if running from repo root
import sys
sys.path.insert(0, "src")

from bankcore.config_manager import ConfigManager


@pytest.fixture(autouse=True)
def reset_singleton():
    """
    Reset the Singleton before every test.
    Ensures each test starts with a clean, isolated instance.
    """
    ConfigManager._reset()
    yield
    ConfigManager._reset()


class TestSingletonBehavior:
    """Core Singleton guarantees."""

    def test_returns_same_instance(self):
        """Two calls to get_instance() must return the exact same object."""
        instance_a = ConfigManager.get_instance()
        instance_b = ConfigManager.get_instance()
        assert instance_a is instance_b

    def test_state_shared_across_references(self):
        """A change made through one reference is visible through all others."""
        config_a = ConfigManager.get_instance()
        config_b = ConfigManager.get_instance()

        config_a.set("environment", "production")

        assert config_b.get("environment") == "production"

    def test_reset_creates_new_instance(self):
        """After _reset(), the next get_instance() returns a fresh object."""
        first = ConfigManager.get_instance()
        ConfigManager._reset()
        second = ConfigManager.get_instance()

        assert first is not second


class TestDefaultConfiguration:
    """Verify the bank's default config values are sensible."""

    def test_default_database_url(self):
        config = ConfigManager.get_instance()
        assert config.get("database.url") == "sqlite:///bankcore.db"

    def test_default_fee_rates_are_positive(self):
        config = ConfigManager.get_instance()
        assert config.get("fees.standard_transfer") > 0
        assert config.get("fees.international_transfer") > 0

    def test_default_max_transfer_limit(self):
        config = ConfigManager.get_instance()
        assert config.get("limits.max_transfer_amount") == 50_000.0

    def test_default_environment_is_development(self):
        config = ConfigManager.get_instance()
        assert config.get("environment") == "development"

    def test_missing_key_returns_default(self):
        config = ConfigManager.get_instance()
        result = config.get("nonexistent.key", "fallback")
        assert result == "fallback"

    def test_missing_key_without_default_returns_none(self):
        config = ConfigManager.get_instance()
        result = config.get("nonexistent.key")
        assert result is None


class TestRuntimeOverrides:
    """Config values can be changed at runtime."""

    def test_set_overrides_default(self):
        config = ConfigManager.get_instance()
        config.set("limits.max_transfer_amount", 100_000.0)
        assert config.get("limits.max_transfer_amount") == 100_000.0

    def test_set_new_key(self):
        config = ConfigManager.get_instance()
        config.set("feature.dark_mode", True)
        assert config.get("feature.dark_mode") is True

    def test_all_returns_snapshot(self):
        """all() should return a copy, not a live reference."""
        config = ConfigManager.get_instance()
        snapshot = config.all()
        config.set("environment", "production")

        # Snapshot should not reflect the change
        assert snapshot["environment"] == "development"
        assert config.get("environment") == "production"


class TestEnvironmentVariableLoading:
    """Config can be driven by environment variables for deployment flexibility."""

    def test_loads_database_url_from_env(self, monkeypatch):
        monkeypatch.setenv("BANKCORE_DATABASE_URL", "postgresql://prod:5432/bank")
        config = ConfigManager.get_instance()
        assert config.get("database.url") == "postgresql://prod:5432/bank"

    def test_loads_environment_from_env(self, monkeypatch):
        monkeypatch.setenv("BANKCORE_ENVIRONMENT", "production")
        config = ConfigManager.get_instance()
        assert config.get("environment") == "production"

    def test_loads_max_transfer_as_float(self, monkeypatch):
        monkeypatch.setenv("BANKCORE_MAX_TRANSFER", "200000")
        config = ConfigManager.get_instance()
        value = config.get("limits.max_transfer_amount")
        assert value == 200_000.0
        assert isinstance(value, float)

    def test_missing_env_var_keeps_default(self, monkeypatch):
        monkeypatch.delenv("BANKCORE_DATABASE_URL", raising=False)
        config = ConfigManager.get_instance()
        assert config.get("database.url") == "sqlite:///bankcore.db"


class TestThreadSafety:
    """The Singleton must be safe under concurrent access."""

    def test_concurrent_get_instance_returns_same_object(self):
        import threading

        instances = []
        lock = threading.Lock()

        def fetch():
            instance = ConfigManager.get_instance()
            with lock:
                instances.append(instance)

        threads = [threading.Thread(target=fetch) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All threads must have received the exact same instance
        assert all(i is instances[0] for i in instances)
