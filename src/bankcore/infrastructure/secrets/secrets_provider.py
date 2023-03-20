"""
BankCore — Day 28: Secrets Management
========================================
Manages sensitive credentials outside of ConfigManager and source code.

Problem: API keys, HMAC secrets, DB passwords in config files or env vars
are visible in logs, process lists, and container images.

Solution: SecretsProvider Protocol — a typed abstraction for secret access.
  - EnvSecretsProvider: reads from environment variables (production-safe)
  - InMemorySecretsProvider: in-memory store for tests (zero env dependency)
  - RotatingSecretsProvider: supports secret rotation with versioning

Connection to previous days:
  - J01 (ConfigManager): ConfigManager handles non-sensitive config;
    SecretsProvider handles sensitive values only
  - J10 (DIP): SecretsProvider is a Protocol — injectable, testable
  - J26 (Audit Log): AuditLog HMAC key comes from SecretsProvider
  - J27 (RBAC): JWT signing key (future) would come from SecretsProvider
  - J19 (Docker): ENV vars are the production delivery mechanism

Security principles:
  - Never log secret values
  - Secrets are fetched lazily (not loaded at startup)
  - get() raises SecretNotFoundError rather than returning None
    (callers must handle missing secrets explicitly)
"""

from __future__ import annotations
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class SecretNotFoundError(Exception):
    """Raised when a requested secret does not exist."""

    def __init__(self, key: str, provider: str = "") -> None:
        self.key      = key
        self.provider = provider
        super().__init__(
            f"Secret '{key}' not found"
            + (f" in {provider}" if provider else "") + "."
        )


class SecretAccessError(Exception):
    """Raised when a secret exists but cannot be retrieved (permissions, etc.)."""


# ---------------------------------------------------------------------------
# SecretsProvider Protocol
# ---------------------------------------------------------------------------

class SecretsProvider(ABC):
    """
    Abstract interface for secret retrieval.

    Implementations must never log secret values.
    get() raises SecretNotFoundError if the secret does not exist.
    """

    @abstractmethod
    def get(self, key: str) -> str:
        """Return the value of a secret. Raises SecretNotFoundError if absent."""

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Return True if the secret exists (without revealing its value)."""

    def get_or_default(self, key: str, default: str) -> str:
        """Return the secret value, or default if not found."""
        try:
            return self.get(key)
        except SecretNotFoundError:
            return default


# ---------------------------------------------------------------------------
# Secret keys constants — single source of truth
# ---------------------------------------------------------------------------

class SecretKeys:
    """
    Centralized registry of secret key names.
    Prevents typos: use SecretKeys.AUDIT_HMAC_KEY, not "audit_hmac_key".
    """
    AUDIT_HMAC_KEY      = "bankcore.audit.hmac_key"
    DATABASE_PASSWORD   = "bankcore.db.password"
    RABBITMQ_PASSWORD   = "bankcore.rabbitmq.password"
    REDIS_PASSWORD      = "bankcore.redis.password"
    JWT_SIGNING_KEY     = "bankcore.auth.jwt_signing_key"
    API_ENCRYPTION_KEY  = "bankcore.api.encryption_key"


# ---------------------------------------------------------------------------
# InMemorySecretsProvider — for tests
# ---------------------------------------------------------------------------

class InMemorySecretsProvider(SecretsProvider):
    """
    In-memory secrets store for testing.

    Usage:
        provider = InMemorySecretsProvider({
            SecretKeys.AUDIT_HMAC_KEY: "test-hmac-secret",
            SecretKeys.JWT_SIGNING_KEY: "test-jwt-secret",
        })
        key = provider.get(SecretKeys.AUDIT_HMAC_KEY)
    """

    def __init__(self, secrets: dict[str, str] = None) -> None:
        self._secrets: dict[str, str] = dict(secrets or {})
        self._access_log: list[dict]  = []

    def get(self, key: str) -> str:
        self._access_log.append({
            "key":       key,
            "found":     key in self._secrets,
            "timestamp": datetime.now().isoformat(),
        })
        if key not in self._secrets:
            raise SecretNotFoundError(key, "InMemorySecretsProvider")
        return self._secrets[key]

    def exists(self, key: str) -> bool:
        return key in self._secrets

    def set(self, key: str, value: str) -> None:
        """Test utility — add or update a secret."""
        self._secrets[key] = value

    def delete(self, key: str) -> None:
        """Test utility — remove a secret."""
        self._secrets.pop(key, None)

    @property
    def access_log(self) -> list[dict]:
        """Returns access log WITHOUT secret values (keys only)."""
        return list(self._access_log)

    def access_count(self, key: str) -> int:
        return sum(1 for e in self._access_log if e["key"] == key)


# ---------------------------------------------------------------------------
# EnvSecretsProvider — for production
# ---------------------------------------------------------------------------

class EnvSecretsProvider(SecretsProvider):
    """
    Reads secrets from environment variables.

    Key mapping: "bankcore.audit.hmac_key" → "BANKCORE_AUDIT_HMAC_KEY"
    (dots and dashes become underscores, uppercased)

    Production usage:
        export BANKCORE_AUDIT_HMAC_KEY="$(vault kv get -field=value secret/bankcore/audit)"
        provider = EnvSecretsProvider()
        key = provider.get(SecretKeys.AUDIT_HMAC_KEY)

    Docker/Kubernetes: inject via secret volumes or sealed secrets.
    Never put actual secret values in Dockerfiles or compose files.
    """

    def __init__(self, prefix: str = "") -> None:
        self._prefix = prefix.upper()

    def _env_key(self, key: str) -> str:
        """Convert secret key to environment variable name."""
        normalized = key.upper().replace(".", "_").replace("-", "_")
        if self._prefix:
            return f"{self._prefix}_{normalized}"
        return normalized

    def get(self, key: str) -> str:
        env_key = self._env_key(key)
        value   = os.environ.get(env_key)
        if value is None:
            raise SecretNotFoundError(key, f"EnvSecretsProvider(env={env_key})")
        return value

    def exists(self, key: str) -> bool:
        return os.environ.get(self._env_key(key)) is not None

    def env_key_for(self, key: str) -> str:
        """Return the environment variable name for a given secret key."""
        return self._env_key(key)


# ---------------------------------------------------------------------------
# RotatingSecretsProvider — supports versioned secret rotation
# ---------------------------------------------------------------------------

@dataclass
class SecretVersion:
    """A versioned secret value."""
    version:    int
    value:      str
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    is_active:  bool = True


class RotatingSecretsProvider(SecretsProvider):
    """
    Supports secret rotation with versioning.

    Rotation without downtime:
      1. Add new version (both old and new are active)
      2. Migrate all clients to new version
      3. Deactivate old version

    Used for HMAC key rotation in the Audit Log (J26):
      - Old entries remain verifiable with old key version
      - New entries use the current key version
    """

    def __init__(self) -> None:
        self._secrets: dict[str, list[SecretVersion]] = {}

    def add_version(self, key: str, value: str) -> int:
        """Add a new version of a secret. Returns the new version number."""
        versions = self._secrets.setdefault(key, [])
        version  = len(versions) + 1
        versions.append(SecretVersion(version=version, value=value))
        return version

    def get(self, key: str) -> str:
        """Return the latest active version."""
        versions = self._secrets.get(key, [])
        active   = [v for v in versions if v.is_active]
        if not active:
            raise SecretNotFoundError(key, "RotatingSecretsProvider")
        return active[-1].value   # latest active version

    def get_version(self, key: str, version: int) -> str:
        """Return a specific version (for verifying old signatures)."""
        versions = self._secrets.get(key, [])
        for v in versions:
            if v.version == version:
                return v.value
        raise SecretNotFoundError(f"{key}@v{version}", "RotatingSecretsProvider")

    def exists(self, key: str) -> bool:
        versions = self._secrets.get(key, [])
        return any(v.is_active for v in versions)

    def deactivate_version(self, key: str, version: int) -> None:
        """Mark an old version as inactive (after rotation completes)."""
        for v in self._secrets.get(key, []):
            if v.version == version:
                v.is_active = False
                return

    def current_version_number(self, key: str) -> int:
        """Return the current (latest active) version number."""
        versions = self._secrets.get(key, [])
        active   = [v for v in versions if v.is_active]
        if not active:
            raise SecretNotFoundError(key, "RotatingSecretsProvider")
        return active[-1].version

    def list_versions(self, key: str) -> list[dict]:
        """Return version metadata WITHOUT values."""
        return [
            {
                "version":    v.version,
                "is_active":  v.is_active,
                "created_at": v.created_at,
            }
            for v in self._secrets.get(key, [])
        ]


# ---------------------------------------------------------------------------
# SecretsBankContainer — extends BankContainer with secrets
# ---------------------------------------------------------------------------

class SecretsAwareMixin:
    """
    Mixin that adds SecretsProvider access to any service.

    Usage:
        class AuditLogFactory(SecretsAwareMixin):
            def create(self, provider: SecretsProvider):
                key = self.get_secret(provider, SecretKeys.AUDIT_HMAC_KEY,
                                      default="dev-default-key")
                return ImmutableAuditLog(secret_key=key)
    """

    def get_secret(
        self,
        provider: SecretsProvider,
        key: str,
        default: Optional[str] = None,
    ) -> str:
        if default is not None:
            return provider.get_or_default(key, default)
        return provider.get(key)

    def create_audit_log(self, provider: SecretsProvider):
        """Factory: create an ImmutableAuditLog with HMAC key from SecretsProvider."""
        from bankcore.infrastructure.audit.audit_log import ImmutableAuditLog
        hmac_key = provider.get_or_default(
            SecretKeys.AUDIT_HMAC_KEY,
            default="bankcore-default-dev-key-not-for-production",
        )
        return ImmutableAuditLog(secret_key=hmac_key)
