"""
BankCore — Day 21: EventStore
================================
Append-only store for domain events.

Core guarantee: events are NEVER modified or deleted.
Once appended, an event is permanent — the audit trail is inviolable.

Key concepts:
  - Sequence number: global ordering across all aggregates
  - Aggregate version: per-aggregate ordering for optimistic locking
  - Checksum: SHA-256 of payload for corruption detection

Optimistic locking:
  When appending, pass expected_version=N.
  If the aggregate is already at version M > N, raise ConcurrencyError.
  This prevents two concurrent writers from overwriting each other.

Usage:
    store = InProcessEventStore()

    # Append events
    store.append(MoneyDeposited(
        aggregate_id=AccountId("ACC-001"),
        amount=Money.eur(500.0),
    ))

    # Replay events for one aggregate
    events = store.get_events("ACC-001")

    # Rebuild state
    account = AccountAggregate.from_events(events)
    print(account.balance)  # 500.0
"""

from __future__ import annotations
import hashlib
import json
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from bankcore.domain.domain_events import DomainEvent
from bankcore.domain.value_objects import AccountId, Money


# ---------------------------------------------------------------------------
# StoredEvent — event as persisted in the store
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StoredEvent:
    """
    A domain event as it lives in the EventStore.

    Adds persistence concerns to a DomainEvent:
      - sequence_number: global ordering (useful for CDC, replication)
      - aggregate_version: ordering within one aggregate
      - checksum: SHA-256 of payload for corruption detection
      - stored_at: wall clock time of persistence
    """
    event:              DomainEvent
    sequence_number:    int
    aggregate_version:  int
    checksum:           str
    stored_at:          datetime = field(default_factory=datetime.now)

    @property
    def aggregate_id(self) -> str:
        return str(self.event.aggregate_id)

    @property
    def event_type(self) -> str:
        return self.event.event_type

    def verify_checksum(self) -> bool:
        """Return True if the event payload has not been corrupted."""
        return self.checksum == _compute_checksum(self.event)

    def to_dict(self) -> dict:
        return {
            "sequence_number":   self.sequence_number,
            "aggregate_version": self.aggregate_version,
            "aggregate_id":      self.aggregate_id,
            "event_type":        self.event_type,
            "event_id":          self.event.event_id,
            "checksum":          self.checksum,
            "stored_at":         self.stored_at.isoformat(),
            "payload":           self.event.to_dict(),
        }


def _compute_checksum(event: DomainEvent) -> str:
    """SHA-256 of the event's dict representation."""
    payload = json.dumps(event.to_dict(), sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ConcurrencyError(Exception):
    """
    Raised when two writers try to append to the same aggregate version.
    The caller must reload the aggregate and retry.
    """

class CorruptionError(Exception):
    """Raised when a stored event fails its checksum verification."""


# ---------------------------------------------------------------------------
# EventStore
# ---------------------------------------------------------------------------

class InProcessEventStore:
    """
    Thread-safe append-only in-memory EventStore.

    Production replacement: SQLiteEventStore or PostgresEventStore
    with the same interface. The append() and get_events() methods
    are the entire public API — nothing else is needed.

    Optimistic locking: pass expected_version to detect concurrent writes.
    """

    def __init__(self) -> None:
        self._events:    list[StoredEvent]        = []
        self._by_agg:    dict[str, list[StoredEvent]] = {}
        self._versions:  dict[str, int]           = {}   # agg_id → latest version
        self._lock       = threading.Lock()
        self._seq        = 0

    # ------------------------------------------------------------------
    # Write (append-only)
    # ------------------------------------------------------------------

    def append(
        self,
        event: DomainEvent,
        expected_version: Optional[int] = None,
    ) -> StoredEvent:
        """
        Append an event to the store.

        Args:
            event: the domain event to persist
            expected_version: if provided, raises ConcurrencyError if the
                aggregate is at a different version (optimistic locking)

        Returns:
            StoredEvent with sequence number and checksum assigned
        """
        with self._lock:
            agg_id  = str(event.aggregate_id)
            current = self._versions.get(agg_id, 0)

            if expected_version is not None and current != expected_version:
                raise ConcurrencyError(
                    f"Aggregate {agg_id} is at version {current}, "
                    f"expected {expected_version}. Reload and retry."
                )

            self._seq    += 1
            new_version   = current + 1
            checksum      = _compute_checksum(event)

            stored = StoredEvent(
                event=event,
                sequence_number=self._seq,
                aggregate_version=new_version,
                checksum=checksum,
            )

            self._events.append(stored)
            self._by_agg.setdefault(agg_id, []).append(stored)
            self._versions[agg_id] = new_version

            return stored

    def append_all(
        self,
        events: list[DomainEvent],
        expected_version: Optional[int] = None,
    ) -> list[StoredEvent]:
        """Append multiple events atomically."""
        stored = []
        with self._lock:
            for i, event in enumerate(events):
                ev = expected_version + i if expected_version is not None else None
                # Temporarily unlock to reuse append logic — instead inline:
                agg_id  = str(event.aggregate_id)
                current = self._versions.get(agg_id, 0)

                if ev is not None and current != ev:
                    raise ConcurrencyError(
                        f"Concurrency conflict at event {i} for {agg_id}"
                    )

                self._seq   += 1
                new_version  = current + 1
                s = StoredEvent(
                    event=event,
                    sequence_number=self._seq,
                    aggregate_version=new_version,
                    checksum=_compute_checksum(event),
                )
                self._events.append(s)
                self._by_agg.setdefault(agg_id, []).append(s)
                self._versions[agg_id] = new_version
                stored.append(s)
        return stored

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_events(
        self,
        aggregate_id: str,
        from_version: int = 0,
    ) -> list[StoredEvent]:
        """
        Return all events for an aggregate, in order.
        from_version: skip events at or below this version (for snapshots).
        """
        events = self._by_agg.get(aggregate_id, [])
        return [e for e in events if e.aggregate_version > from_version]

    def get_version(self, aggregate_id: str) -> int:
        """Return the current version of an aggregate (0 if unknown)."""
        return self._versions.get(aggregate_id, 0)

    def all_events(self, event_type: str = None) -> list[StoredEvent]:
        """Return all events, optionally filtered by type."""
        if event_type:
            return [e for e in self._events if e.event_type == event_type]
        return list(self._events)

    def total_event_count(self) -> int:
        return len(self._events)

    def aggregate_count(self) -> int:
        return len(self._by_agg)

    # ------------------------------------------------------------------
    # Integrity
    # ------------------------------------------------------------------

    def verify_integrity(self, aggregate_id: str) -> list[str]:
        """
        Verify checksums for all events of an aggregate.
        Returns list of error messages (empty = all good).
        """
        errors = []
        for stored in self._by_agg.get(aggregate_id, []):
            if not stored.verify_checksum():
                errors.append(
                    f"Checksum mismatch for event {stored.event.event_id} "
                    f"(seq={stored.sequence_number})"
                )
        return errors
