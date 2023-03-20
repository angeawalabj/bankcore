"""
Tests — Day 28: Secrets Management
=====================================
Test strategy:
  1. InMemorySecretsProvider — get, exists, not found, access log
  2. EnvSecretsProvider — key mapping, env lookup, missing
  3. RotatingSecretsProvider — versioning, rotation, deactivation
  4. SecretKeys — constants coverage
  5. SecretsAwareMixin — audit log factory with injected key
  6. Security — secrets never in repr/str, access logged
  7. Integration — ImmutableAuditLog key from SecretsProvider
"""

import sys
import os
import pytest

sys.path.insert(0, "src")

from bankcore.infrastructure.secrets.secrets_provider import (
    SecretsProvider, SecretNotFoundError,
    InMemorySecretsProvider, EnvSecretsProvider,
    RotatingSecretsProvider, SecretKeys, SecretsAwareMixin,
)
from bankcore.infrastructure.audit.audit_log import ImmutableAuditLog


# ---------------------------------------------------------------------------
# InMemorySecretsProvider
# ---------------------------------------------------------------------------

class TestInMemorySecretsProvider:

    def test_get_existing_secret(self):
        provider = InMemorySecretsProvider({SecretKeys.AUDIT_HMAC_KEY: "my-secret"})
        assert provider.get(SecretKeys.AUDIT_HMAC_KEY) == "my-secret"

    def test_get_missing_raises(self):
        provider = InMemorySecretsProvider()
        with pytest.raises(SecretNotFoundError) as exc_info:
            provider.get("nonexistent.key")
        assert "nonexistent.key" in str(exc_info.value)

    def test_exists_true(self):
        provider = InMemorySecretsProvider({"key": "value"})
        assert provider.exists("key") is True

    def test_exists_false(self):
        provider = InMemorySecretsProvider()
        assert provider.exists("missing") is False

    def test_get_or_default_found(self):
        provider = InMemorySecretsProvider({"key": "real-value"})
        assert provider.get_or_default("key", "default") == "real-value"

    def test_get_or_default_missing(self):
        provider = InMemorySecretsProvider()
        assert provider.get_or_default("missing", "fallback") == "fallback"

    def test_set_adds_secret(self):
        provider = InMemorySecretsProvider()
        provider.set("new.key", "new-value")
        assert provider.get("new.key") == "new-value"

    def test_delete_removes_secret(self):
        provider = InMemorySecretsProvider({"key": "value"})
        provider.delete("key")
        assert provider.exists("key") is False

    def test_access_log_records_keys_not_values(self):
        provider = InMemorySecretsProvider({SecretKeys.AUDIT_HMAC_KEY: "super-secret"})
        provider.get(SecretKeys.AUDIT_HMAC_KEY)
        log = provider.access_log
        assert len(log) == 1
        assert log[0]["key"] == SecretKeys.AUDIT_HMAC_KEY
        # Verify the secret VALUE is not in the log entry
        assert "super-secret" not in str(log[0])

    def test_access_count(self):
        provider = InMemorySecretsProvider({"key": "value"})
        provider.get("key")
        provider.get("key")
        provider.get("key")
        assert provider.access_count("key") == 3

    def test_access_log_records_not_found(self):
        provider = InMemorySecretsProvider()
        try:
            provider.get("missing")
        except SecretNotFoundError:
            pass
        log = provider.access_log
        assert len(log) == 1
        assert log[0]["found"] is False


# ---------------------------------------------------------------------------
# EnvSecretsProvider
# ---------------------------------------------------------------------------

class TestEnvSecretsProvider:

    def test_key_mapping_dots_to_underscores(self):
        provider = EnvSecretsProvider()
        env_key = provider.env_key_for("bankcore.audit.hmac_key")
        assert env_key == "BANKCORE_AUDIT_HMAC_KEY"

    def test_key_mapping_with_prefix(self):
        provider = EnvSecretsProvider(prefix="APP")
        env_key = provider.env_key_for("db.password")
        assert env_key == "APP_DB_PASSWORD"

    def test_get_from_env(self, monkeypatch):
        monkeypatch.setenv("BANKCORE_AUDIT_HMAC_KEY", "env-secret-value")
        provider = EnvSecretsProvider()
        value    = provider.get(SecretKeys.AUDIT_HMAC_KEY)
        assert value == "env-secret-value"

    def test_get_missing_env_raises(self):
        provider = EnvSecretsProvider()
        # Use a key that definitely won't be in the test environment
        with pytest.raises(SecretNotFoundError):
            provider.get("bankcore.definitely.not.set.xyz.abc.123")

    def test_exists_true(self, monkeypatch):
        monkeypatch.setenv("BANKCORE_TEST_KEY", "present")
        provider = EnvSecretsProvider()
        assert provider.exists("bankcore.test_key") is True

    def test_exists_false(self):
        provider = EnvSecretsProvider()
        assert provider.exists("bankcore.never.set.xyz.abc.123") is False


# ---------------------------------------------------------------------------
# RotatingSecretsProvider
# ---------------------------------------------------------------------------

class TestRotatingSecretsProvider:

    def test_add_and_get_first_version(self):
        provider = RotatingSecretsProvider()
        provider.add_version(SecretKeys.AUDIT_HMAC_KEY, "v1-secret")
        assert provider.get(SecretKeys.AUDIT_HMAC_KEY) == "v1-secret"

    def test_get_returns_latest_version(self):
        provider = RotatingSecretsProvider()
        provider.add_version(SecretKeys.AUDIT_HMAC_KEY, "v1-secret")
        provider.add_version(SecretKeys.AUDIT_HMAC_KEY, "v2-secret")
        assert provider.get(SecretKeys.AUDIT_HMAC_KEY) == "v2-secret"

    def test_get_specific_version(self):
        provider = RotatingSecretsProvider()
        provider.add_version(SecretKeys.AUDIT_HMAC_KEY, "v1-secret")
        provider.add_version(SecretKeys.AUDIT_HMAC_KEY, "v2-secret")
        assert provider.get_version(SecretKeys.AUDIT_HMAC_KEY, 1) == "v1-secret"
        assert provider.get_version(SecretKeys.AUDIT_HMAC_KEY, 2) == "v2-secret"

    def test_version_number_increments(self):
        provider = RotatingSecretsProvider()
        v1 = provider.add_version(SecretKeys.AUDIT_HMAC_KEY, "v1")
        v2 = provider.add_version(SecretKeys.AUDIT_HMAC_KEY, "v2")
        assert v1 == 1
        assert v2 == 2

    def test_deactivate_old_version(self):
        provider = RotatingSecretsProvider()
        provider.add_version(SecretKeys.AUDIT_HMAC_KEY, "v1-secret")
        provider.add_version(SecretKeys.AUDIT_HMAC_KEY, "v2-secret")
        provider.deactivate_version(SecretKeys.AUDIT_HMAC_KEY, 1)

        # Latest active is still v2
        assert provider.get(SecretKeys.AUDIT_HMAC_KEY) == "v2-secret"

        # Old version still accessible by number (for verifying old signatures)
        assert provider.get_version(SecretKeys.AUDIT_HMAC_KEY, 1) == "v1-secret"

    def test_get_missing_raises(self):
        provider = RotatingSecretsProvider()
        with pytest.raises(SecretNotFoundError):
            provider.get("nonexistent.key")

    def test_get_missing_version_raises(self):
        provider = RotatingSecretsProvider()
        provider.add_version(SecretKeys.AUDIT_HMAC_KEY, "v1")
        with pytest.raises(SecretNotFoundError):
            provider.get_version(SecretKeys.AUDIT_HMAC_KEY, 99)

    def test_list_versions_hides_values(self):
        provider = RotatingSecretsProvider()
        provider.add_version(SecretKeys.AUDIT_HMAC_KEY, "super-secret-v1")
        versions = provider.list_versions(SecretKeys.AUDIT_HMAC_KEY)
        assert len(versions) == 1
        assert "super-secret-v1" not in str(versions)
        assert "version" in versions[0]
        assert "is_active" in versions[0]

    def test_current_version_number(self):
        provider = RotatingSecretsProvider()
        provider.add_version(SecretKeys.AUDIT_HMAC_KEY, "v1")
        provider.add_version(SecretKeys.AUDIT_HMAC_KEY, "v2")
        assert provider.current_version_number(SecretKeys.AUDIT_HMAC_KEY) == 2

    def test_exists_false_when_all_deactivated(self):
        provider = RotatingSecretsProvider()
        provider.add_version(SecretKeys.AUDIT_HMAC_KEY, "v1")
        provider.deactivate_version(SecretKeys.AUDIT_HMAC_KEY, 1)
        assert provider.exists(SecretKeys.AUDIT_HMAC_KEY) is False

    def test_rotation_workflow(self):
        """
        Full rotation workflow:
        1. Add v1 (active)
        2. Add v2 (both active — transition period)
        3. Deactivate v1 (rotation complete)
        4. v1 still readable by version number (for old signature verification)
        """
        provider = RotatingSecretsProvider()

        # Step 1: initial key
        provider.add_version(SecretKeys.AUDIT_HMAC_KEY, "old-key")
        assert provider.get(SecretKeys.AUDIT_HMAC_KEY) == "old-key"

        # Step 2: add new key (transition)
        provider.add_version(SecretKeys.AUDIT_HMAC_KEY, "new-key")
        assert provider.get(SecretKeys.AUDIT_HMAC_KEY) == "new-key"   # latest

        # Step 3: deactivate old key
        provider.deactivate_version(SecretKeys.AUDIT_HMAC_KEY, 1)

        # Step 4: old key still readable for legacy verification
        assert provider.get_version(SecretKeys.AUDIT_HMAC_KEY, 1) == "old-key"
        assert provider.get(SecretKeys.AUDIT_HMAC_KEY) == "new-key"


# ---------------------------------------------------------------------------
# SecretKeys constants
# ---------------------------------------------------------------------------

class TestSecretKeys:

    def test_all_keys_are_strings(self):
        for attr in dir(SecretKeys):
            if not attr.startswith("_"):
                value = getattr(SecretKeys, attr)
                if isinstance(value, str):
                    assert "." in value, f"Key {attr} should use dot notation"

    def test_audit_hmac_key_defined(self):
        assert SecretKeys.AUDIT_HMAC_KEY == "bankcore.audit.hmac_key"

    def test_database_password_defined(self):
        assert SecretKeys.DATABASE_PASSWORD == "bankcore.db.password"


# ---------------------------------------------------------------------------
# SecretsAwareMixin — audit log factory
# ---------------------------------------------------------------------------

class TestSecretsAwareMixin:

    def test_create_audit_log_with_provider_key(self):
        class MyFactory(SecretsAwareMixin):
            pass

        provider = InMemorySecretsProvider({
            SecretKeys.AUDIT_HMAC_KEY: "production-hmac-key"
        })
        factory   = MyFactory()
        audit_log = factory.create_audit_log(provider)
        assert isinstance(audit_log, ImmutableAuditLog)

    def test_create_audit_log_uses_default_when_key_missing(self):
        class MyFactory(SecretsAwareMixin):
            pass

        provider  = InMemorySecretsProvider()   # no keys
        factory   = MyFactory()
        audit_log = factory.create_audit_log(provider)
        # Falls back to default key — still creates a valid audit log
        assert isinstance(audit_log, ImmutableAuditLog)

    def test_audit_log_signed_with_provider_key(self):
        """
        Two audit logs with different keys from providers produce different signatures.
        """
        class MyFactory(SecretsAwareMixin):
            pass

        p1 = InMemorySecretsProvider({SecretKeys.AUDIT_HMAC_KEY: "key-one"})
        p2 = InMemorySecretsProvider({SecretKeys.AUDIT_HMAC_KEY: "key-two"})

        factory = MyFactory()
        log1    = factory.create_audit_log(p1)
        log2    = factory.create_audit_log(p2)

        e1 = log1.append("TRANSFER", "alice", "ACC-001", {"amount": 100})
        e2 = log2.append("TRANSFER", "alice", "ACC-001", {"amount": 100})

        # Same content, different keys → different signatures
        assert e1.signature != e2.signature

        # Each log verifies its own entries
        assert log1.verify_entry(e1) is True
        assert log2.verify_entry(e2) is True

        # Cross-verification fails (different keys)
        assert log1.verify_entry(e2) is False
        assert log2.verify_entry(e1) is False


# ---------------------------------------------------------------------------
# Integration — full flow with all three providers
# ---------------------------------------------------------------------------

class TestSecretsIntegration:

    def test_in_memory_provider_satisfies_protocol(self):
        provider = InMemorySecretsProvider()
        assert isinstance(provider, SecretsProvider)

    def test_env_provider_satisfies_protocol(self):
        provider = EnvSecretsProvider()
        assert isinstance(provider, SecretsProvider)

    def test_rotating_provider_satisfies_protocol(self):
        provider = RotatingSecretsProvider()
        assert isinstance(provider, SecretsProvider)

    def test_secret_not_found_error_carries_key(self):
        err = SecretNotFoundError("my.secret.key", "TestProvider")
        assert "my.secret.key" in str(err)
        assert "TestProvider" in str(err)

    def test_provider_swap_is_transparent(self):
        """
        The same code works with any SecretsProvider implementation.
        DIP (J10): depend on the abstraction, not the implementation.
        """
        def get_hmac_key(provider: SecretsProvider) -> str:
            return provider.get_or_default(
                SecretKeys.AUDIT_HMAC_KEY, "default-key"
            )

        # InMemory provider
        mem_provider = InMemorySecretsProvider({
            SecretKeys.AUDIT_HMAC_KEY: "mem-key"
        })
        assert get_hmac_key(mem_provider) == "mem-key"

        # Rotating provider
        rot_provider = RotatingSecretsProvider()
        rot_provider.add_version(SecretKeys.AUDIT_HMAC_KEY, "rot-key")
        assert get_hmac_key(rot_provider) == "rot-key"

        # Empty provider falls back to default
        empty_provider = InMemorySecretsProvider()
        assert get_hmac_key(empty_provider) == "default-key"
