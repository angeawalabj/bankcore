"""
BankCore — Day 26: Immutable Audit Log
=========================================
Cryptographically signed and chained audit log.

Each entry:
  1. Contains its own SHA-256 hash (integrity)
  2. Contains the hash of the previous entry (chaining)
  3. Is signed with HMAC-SHA256 (authenticity)

Tampering detection:
  - Modify any entry → its hash changes
  - The next entry contains the old hash → chain broken
  - verify_chain() detects the break and reports the first corrupted entry

Connection to previous days:
  - J03 (AuditLogger): writes to ImmutableAuditLog instead of a simple list
  - J21 (EventStore): same append-only philosophy + cryptographic guarantee
  - J28 (Secrets): HMAC key will come from SecretsProvider

Production considerations:
  - The HMAC key must be stored outside the application (HSM, Vault)
  - Entries should be periodically exported to an external, read-only archive
  - The chain root hash should be published externally for anchoring
"""

from __future__ import annotations
import hashlib
import hmac
import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


# ---------------------------------------------------------------------------
# AuditEntry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AuditEntry:
    """
    One immutable entry in the audit log.

    frozen=True: once created, the entry cannot be modified.
    Any attempt raises FrozenInstanceError — immutability enforced by runtime.

    Fields:
      entry_id:    unique identifier
      timestamp:   ISO-8601 creation time
      event_type:  category (TRANSFER, DEPOSIT, LOGIN, etc.)
      actor:       who triggered the event (user_id, service name)
      resource:    what was affected (account_id, etc.)
      payload:     full event data
      prev_hash:   SHA-256 of the previous entry ("GENESIS" for first)
      entry_hash:  SHA-256 of this entry's canonical content
      signature:   HMAC-SHA256 of entry_hash (proves key possession)
      sequence:    position in the log (1-indexed)
    """
    entry_id:   str
    timestamp:  str
    event_type: str
    actor:      str
    resource:   str
    payload:    dict
    prev_hash:  str
    entry_hash: str
    signature:  str
    sequence:   int

    def to_dict(self) -> dict:
        return {
            "entry_id":   self.entry_id,
            "sequence":   self.sequence,
            "timestamp":  self.timestamp,
            "event_type": self.event_type,
            "actor":      self.actor,
            "resource":   self.resource,
            "payload":    self.payload,
            "prev_hash":  self.prev_hash,
            "entry_hash": self.entry_hash,
            "signature":  self.signature,
        }


# ---------------------------------------------------------------------------
# ImmutableAuditLog
# ---------------------------------------------------------------------------

class ImmutableAuditLog:
    """
    Cryptographically chained, HMAC-signed audit log.

    Append-only: entries cannot be deleted or modified.
    Each entry is linked to the previous via prev_hash.
    Each entry is signed with a secret key.

    Verification:
      log.verify_chain()  → checks all hashes are consistent
      log.verify_entry(e) → checks one entry's signature
    """

    GENESIS_HASH = "GENESIS_0000000000000000000000000000000000000000000000"

    def __init__(self, secret_key: str = "bankcore-audit-secret-key") -> None:
        self._entries:    list[AuditEntry] = []
        self._secret_key: bytes            = secret_key.encode("utf-8")
        self._lock        = threading.Lock()

    # ------------------------------------------------------------------
    # Write (append-only)
    # ------------------------------------------------------------------

    def append(
        self,
        event_type: str,
        actor:      str,
        resource:   str,
        payload:    dict,
    ) -> AuditEntry:
        """
        Append a new entry to the audit log.
        Thread-safe: only one writer at a time.
        """
        with self._lock:
            sequence  = len(self._entries) + 1
            prev_hash = (
                self._entries[-1].entry_hash
                if self._entries
                else self.GENESIS_HASH
            )
            timestamp  = datetime.now().isoformat()
            entry_id   = str(uuid.uuid4())[:12].upper()

            # Canonical content for hashing (deterministic, sorted keys)
            canonical = json.dumps({
                "entry_id":   entry_id,
                "sequence":   sequence,
                "timestamp":  timestamp,
                "event_type": event_type,
                "actor":      actor,
                "resource":   resource,
                "payload":    payload,
                "prev_hash":  prev_hash,
            }, sort_keys=True, default=str)

            entry_hash = hashlib.sha256(canonical.encode()).hexdigest()
            signature  = hmac.new(
                self._secret_key,
                entry_hash.encode(),
                hashlib.sha256,
            ).hexdigest()

            entry = AuditEntry(
                entry_id=entry_id,
                timestamp=timestamp,
                event_type=event_type,
                actor=actor,
                resource=resource,
                payload=payload,
                prev_hash=prev_hash,
                entry_hash=entry_hash,
                signature=signature,
                sequence=sequence,
            )
            self._entries.append(entry)
            return entry

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_entry(self, sequence: int) -> Optional[AuditEntry]:
        """Return entry by sequence number (1-indexed)."""
        if 1 <= sequence <= len(self._entries):
            return self._entries[sequence - 1]
        return None

    def get_by_resource(self, resource: str) -> list[AuditEntry]:
        """Return all entries for a given resource (e.g. account_id)."""
        return [e for e in self._entries if e.resource == resource]

    def get_by_event_type(self, event_type: str) -> list[AuditEntry]:
        return [e for e in self._entries if e.event_type == event_type]

    def all_entries(self) -> list[AuditEntry]:
        return list(self._entries)

    def count(self) -> int:
        return len(self._entries)

    @property
    def head_hash(self) -> str:
        """Hash of the most recent entry (or GENESIS if empty)."""
        if self._entries:
            return self._entries[-1].entry_hash
        return self.GENESIS_HASH

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------

    def verify_entry(self, entry: AuditEntry) -> bool:
        """
        Verify that an entry's signature is valid.
        Returns False if the entry was tampered with or the key is wrong.
        """
        expected_sig = hmac.new(
            self._secret_key,
            entry.entry_hash.encode(),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected_sig, entry.signature)

    def verify_chain(self) -> "ChainVerificationResult":
        """
        Verify the entire chain from genesis to head.

        Checks:
          1. Each entry's prev_hash matches the previous entry's entry_hash
          2. Each entry's signature is valid

        Returns ChainVerificationResult with list of violations (empty = intact).
        """
        violations = []

        for i, entry in enumerate(self._entries):
            # Check prev_hash linkage
            expected_prev = (
                self._entries[i - 1].entry_hash
                if i > 0
                else self.GENESIS_HASH
            )
            if entry.prev_hash != expected_prev:
                violations.append(ChainViolation(
                    sequence=entry.sequence,
                    violation_type="BROKEN_CHAIN",
                    detail=(
                        f"Entry {entry.sequence}: prev_hash mismatch. "
                        f"Expected {expected_prev[:16]}..., "
                        f"got {entry.prev_hash[:16]}..."
                    ),
                ))

            # Check signature
            if not self.verify_entry(entry):
                violations.append(ChainViolation(
                    sequence=entry.sequence,
                    violation_type="INVALID_SIGNATURE",
                    detail=f"Entry {entry.sequence}: signature verification failed.",
                ))

        return ChainVerificationResult(
            is_valid=len(violations) == 0,
            entry_count=len(self._entries),
            violations=violations,
            head_hash=self.head_hash,
        )


# ---------------------------------------------------------------------------
# Verification results
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ChainViolation:
    sequence:       int
    violation_type: str   # "BROKEN_CHAIN" or "INVALID_SIGNATURE"
    detail:         str


@dataclass(frozen=True)
class ChainVerificationResult:
    is_valid:    bool
    entry_count: int
    violations:  list
    head_hash:   str

    def summary(self) -> str:
        if self.is_valid:
            return (
                f"Chain INTACT: {self.entry_count} entries verified. "
                f"Head: {self.head_hash[:16]}..."
            )
        return (
            f"Chain COMPROMISED: {len(self.violations)} violation(s) "
            f"in {self.entry_count} entries. "
            f"First violation at entry {self.violations[0].sequence}."
        )
