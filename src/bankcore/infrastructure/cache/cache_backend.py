"""
BankCore — Day 17: Cache Backend
==================================
Abstract cache interface (Protocol) and in-memory implementation.

Design decisions:
  - Protocol-based (DIP, Day 10): InMemoryCache and RedisCache are
    interchangeable without any code change in CachingServiceClient.
  - TTL enforcement: expired entries are never returned, even if
    the eviction hasn't run yet (lazy expiry).
  - Thread-safe InMemoryCache: uses threading.Lock for concurrent reads.
  - CacheStats: every cache operation is instrumented.

Production upgrade path:
    # Development / tests
    cache = InMemoryCache()

    # Production (Redis)
    import redis
    redis_client = redis.Redis(host="redis", port=6379, db=0)
    cache = RedisCache(redis_client)

    # CachingServiceClient doesn't change — same interface
    caching_client = CachingServiceClient(base_client, cache)
"""

from __future__ import annotations
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Cache entry
# ---------------------------------------------------------------------------

@dataclass
class CacheEntry:
    """
    A single cached value with its expiry time.
    Stored internally by InMemoryCache.
    """
    value:      Any
    created_at: float = field(default_factory=time.monotonic)
    ttl:        int   = 60     # seconds

    @property
    def expires_at(self) -> float:
        return self.created_at + self.ttl

    @property
    def is_expired(self) -> bool:
        return time.monotonic() > self.expires_at

    @property
    def ttl_remaining(self) -> float:
        remaining = self.expires_at - time.monotonic()
        return max(0.0, remaining)


# ---------------------------------------------------------------------------
# CacheStats
# ---------------------------------------------------------------------------

@dataclass
class CacheStats:
    """Instrumentation for cache performance."""
    hits:      int   = 0
    misses:    int   = 0
    sets:      int   = 0
    deletes:   int   = 0
    evictions: int   = 0    # expired entries removed on access

    @property
    def total_requests(self) -> int:
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.hits / self.total_requests

    @property
    def miss_rate(self) -> float:
        return 1.0 - self.hit_rate

    @property
    def saved_calls(self) -> int:
        """Number of downstream service calls avoided."""
        return self.hits

    def summary(self) -> str:
        return (
            f"CacheStats: {self.hits}/{self.total_requests} hits "
            f"({self.hit_rate * 100:.1f}%), "
            f"{self.saved_calls} calls saved, "
            f"{self.evictions} evictions"
        )

    def reset(self) -> None:
        self.hits = self.misses = self.sets = self.deletes = self.evictions = 0


# ---------------------------------------------------------------------------
# InMemoryCache
# ---------------------------------------------------------------------------

class InMemoryCache:
    """
    Thread-safe in-memory cache with TTL support.

    Uses lazy eviction: expired entries are detected and removed
    when accessed, not by a background sweep thread.
    This keeps the implementation simple and dependency-free.

    Production replacement: RedisCache (same interface, see docstring above).
    """

    def __init__(self) -> None:
        self._store: dict[str, CacheEntry] = {}
        self._lock  = threading.Lock()
        self.stats  = CacheStats()

    def get(self, key: str) -> Optional[Any]:
        """Return cached value, or None if not found / expired."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self.stats.misses += 1
                return None

            if entry.is_expired:
                del self._store[key]
                self.stats.evictions += 1
                self.stats.misses    += 1
                return None

            self.stats.hits += 1
            return entry.value

    def set(self, key: str, value: Any, ttl_seconds: int = 60) -> None:
        """Store a value with a TTL (in seconds)."""
        with self._lock:
            self._store[key] = CacheEntry(value=value, ttl=ttl_seconds)
            self.stats.sets += 1

    def delete(self, key: str) -> bool:
        """Remove a key. Returns True if it existed."""
        with self._lock:
            if key in self._store:
                del self._store[key]
                self.stats.deletes += 1
                return True
            return False

    def delete_pattern(self, prefix: str) -> int:
        """Remove all keys starting with prefix. Returns count deleted."""
        with self._lock:
            keys_to_delete = [k for k in self._store if k.startswith(prefix)]
            for key in keys_to_delete:
                del self._store[key]
            self.stats.deletes += len(keys_to_delete)
            return len(keys_to_delete)

    def clear(self) -> None:
        """Remove all entries."""
        with self._lock:
            self._store.clear()

    def size(self) -> int:
        """Return number of (possibly expired) entries."""
        return len(self._store)

    def active_size(self) -> int:
        """Return number of non-expired entries."""
        with self._lock:
            return sum(1 for e in self._store.values() if not e.is_expired)

    def ttl_remaining(self, key: str) -> Optional[float]:
        """Return seconds until expiry, or None if not found."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None or entry.is_expired:
                return None
            return entry.ttl_remaining

    def __repr__(self) -> str:
        return (
            f"InMemoryCache(size={self.size()}, active={self.active_size()}, "
            f"hit_rate={self.stats.hit_rate:.1%})"
        )
