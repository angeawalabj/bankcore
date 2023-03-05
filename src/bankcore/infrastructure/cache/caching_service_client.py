"""
BankCore — Day 17: CachingServiceClient
=========================================
Decorator (Day 04 pattern) that adds caching to any ServiceClient.

Design decision: CachingServiceClient wraps ServiceClient — same interface.
TransactionService doesn't know it's talking to a cached client.
This is the Decorator pattern (Day 04) applied at the microservices layer.

Cache strategy:
  - GET requests: cacheable (profile data, not balances)
  - POST/PATCH/DELETE: never cached, always invalidate related keys

Key design for banking:
  - NEVER cache balance: it changes on every transaction
  - Cache profile data (owner_name, account_type, min_possible_balance): 60s TTL
  - Cache transaction records: indefinitely (they're immutable)
  - Invalidate on PATCH /accounts/{id}/balance: remove profile cache too

Usage:
    base_client    = registry.get("account-service")
    cache          = InMemoryCache()
    cached_client  = CachingServiceClient(base_client, cache, ttl=60)

    # TransactionService uses cached_client identically to base_client
    response = cached_client.get("/accounts/ACC-001")  # may be cached
"""

from __future__ import annotations
from typing import Optional

from bankcore.services.shared.service_client import (
    ServiceClient, ServiceResponse, ServiceRequest,
)
from bankcore.infrastructure.cache.cache_backend import InMemoryCache, CacheStats


class CachingServiceClient:
    """
    Decorator over ServiceClient that adds transparent caching.

    Implements the same interface as ServiceClient so it's a drop-in.
    All GET requests to cacheable paths are served from cache on HIT.
    POST/PATCH/DELETE requests bypass cache and invalidate related keys.

    Banking-specific rules:
      - /accounts/{id} profile → cacheable, TTL configurable
      - /accounts/{id}/balance → NEVER cached (included in patch invalidation)
      - /transactions/{id}     → cacheable forever (immutable records)
    """

    # Paths that should NEVER be cached (even on GET)
    NEVER_CACHE_PATTERNS = [
        "/balance",    # balance sub-resource is always live
    ]

    def __init__(
        self,
        client: ServiceClient,
        cache:  Optional[InMemoryCache] = None,
        ttl:    int = 60,
    ) -> None:
        self._client = client
        self._cache  = cache or InMemoryCache()
        self._ttl    = ttl

    # ------------------------------------------------------------------
    # Public interface (mirrors ServiceClient)
    # ------------------------------------------------------------------

    def get(self, path: str, params: dict = None) -> ServiceResponse:
        """
        GET with caching.
        Returns cached response on HIT; calls service and caches on MISS.
        """
        if self._is_cacheable(path):
            cache_key = self._make_key("GET", path, params or {})
            cached    = self._cache.get(cache_key)
            if cached is not None:
                return ServiceResponse(
                    status_code=cached["status_code"],
                    body=cached["body"],
                )

            # Cache MISS — call the service
            response = self._client.get(path, params)

            # Only cache successful responses
            if response.ok:
                self._cache.set(
                    cache_key,
                    {"status_code": response.status_code, "body": response.body},
                    ttl_seconds=self._ttl,
                )
            return response

        # Non-cacheable path — pass through directly
        return self._client.get(path, params)

    def post(self, path: str, body: dict = None) -> ServiceResponse:
        """POST always bypasses cache and invalidates on success."""
        response = self._client.post(path, body)
        if response.ok:
            self._invalidate_for_path(path, body or {})
        return response

    def patch(self, path: str, body: dict = None) -> ServiceResponse:
        """PATCH always bypasses cache and invalidates related keys."""
        response = self._client.patch(path, body)
        if response.ok:
            self._invalidate_for_path(path, body or {})
        return response

    def delete(self, path: str) -> ServiceResponse:
        """DELETE always bypasses cache and invalidates the resource."""
        response = self._client.delete(path)
        if response.ok:
            self._invalidate_for_path(path, {})
        return response

    # ------------------------------------------------------------------
    # Cache management
    # ------------------------------------------------------------------

    def invalidate(self, account_id: str) -> int:
        """
        Explicitly invalidate all cache entries for an account.
        Called when AccountService signals a profile change.
        """
        prefix  = f"GET:/accounts/{account_id}"
        deleted = self._cache.delete_pattern(prefix)
        return deleted

    def invalidate_all(self) -> None:
        """Clear the entire cache. For testing and emergency flush."""
        self._cache.clear()

    @property
    def stats(self) -> CacheStats:
        return self._cache.stats

    @property
    def cache(self) -> InMemoryCache:
        return self._cache

    @property
    def call_count(self) -> int:
        """Number of actual downstream calls (cache misses + non-cacheable)."""
        return self._client.call_count

    @property
    def service_name(self) -> str:
        return self._client.service_name

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_cacheable(self, path: str) -> bool:
        """Return True if this path can be cached."""
        for pattern in self.NEVER_CACHE_PATTERNS:
            if pattern in path:
                return False
        return True

    def _make_key(self, method: str, path: str, params: dict) -> str:
        """Generate a deterministic cache key."""
        params_str = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        key = f"{method}:{path}"
        if params_str:
            key += f"?{params_str}"
        return key

    def _invalidate_for_path(self, path: str, body: dict) -> None:
        """
        Invalidate cache entries related to the modified path.

        Rules:
          - POST /accounts       → invalidate GET:/accounts (list)
          - PATCH /accounts/{id} → invalidate GET:/accounts/{id}
          - PATCH /accounts/{id}/balance → invalidate GET:/accounts/{id}
        """
        path = path.rstrip("/")

        # List invalidation
        if path == "/accounts":
            self._cache.delete("GET:/accounts")
            return

        # Account-specific invalidation
        if "/accounts/" in path:
            # Extract account_id from path like /accounts/ACC-001 or /accounts/ACC-001/balance
            parts      = path.split("/accounts/")
            account_id = parts[1].split("/")[0] if len(parts) > 1 else None
            if account_id:
                # Invalidate the specific account and the list
                self._cache.delete_pattern(f"GET:/accounts/{account_id}")
                self._cache.delete("GET:/accounts")
