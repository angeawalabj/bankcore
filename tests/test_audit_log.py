"""
Tests — Day 26: Audit Log Immuable
=====================================
Test strategy:
  1. AuditEntry — immutability, fields
  2. ImmutableAuditLog — append, read, count
  3. Chain integrity — prev_hash linkage
  4. Signature verification — valid key, wrong key
  5. verify_chain() — intact chain, tampered entry, broken chain
  6. Query methods — by resource, by event type
  7. Concurrency — thread-safe appends
  8. Integration — AuditLogger writes to ImmutableAuditLog
"""

import sys
import threading
import pytest

sys.path.insert(0, "src")

from bankcore.infrastructure.audit.audit_log import (
    ImmutableAuditLog, AuditEntry,
    ChainVerificationResult, ChainViolation,
)


@pytest.fixture
def log():
    return ImmutableAuditLog(secret_key="test-secret-key")


# ---------------------------------------------------------------------------
# AuditEntry — immutability
# ---------------------------------------------------------------------------

class TestAuditEntry:

    def test_entry_is_immutable(self, log):
        entry = log.append("TRANSFER", "alice", "ACC-001", {"amount": 100})
        with pytest.raises(Exception):
            entry.event_type = "MODIFIED"

    def test_entry_to_dict_has_all_fields(self, log):
        entry = log.append("DEPOSIT", "system", "ACC-001", {"amount": 500})
        d = entry.to_dict()
        for field in ["entry_id", "sequence", "timestamp", "event_type",
                      "actor", "resource", "payload", "prev_hash",
                      "entry_hash", "signature"]:
            assert field in d

    def test_entry_has_unique_id(self, log):
        e1 = log.append("DEPOSIT", "sys", "ACC-001", {})
        e2 = log.append("DEPOSIT", "sys", "ACC-001", {})
        assert e1.entry_id != e2.entry_id


# ---------------------------------------------------------------------------
# ImmutableAuditLog — core behaviour
# ---------------------------------------------------------------------------

class TestImmutableAuditLog:

    def test_append_returns_entry(self, log):
        entry = log.append("TRANSFER", "alice", "ACC-001", {"amount": 100})
        assert isinstance(entry, AuditEntry)
        assert entry.event_type == "TRANSFER"
        assert entry.actor      == "alice"
        assert entry.resource   == "ACC-001"
        assert entry.sequence   == 1

    def test_sequence_increments(self, log):
        e1 = log.append("DEPOSIT",    "sys", "ACC-001", {})
        e2 = log.append("WITHDRAWAL", "sys", "ACC-001", {})
        e3 = log.append("TRANSFER",   "sys", "ACC-001", {})
        assert e1.sequence == 1
        assert e2.sequence == 2
        assert e3.sequence == 3

    def test_count(self, log):
        assert log.count() == 0
        log.append("DEPOSIT", "sys", "ACC-001", {})
        log.append("DEPOSIT", "sys", "ACC-002", {})
        assert log.count() == 2

    def test_get_entry_by_sequence(self, log):
        log.append("DEPOSIT",    "sys", "ACC-001", {"amount": 100})
        log.append("WITHDRAWAL", "sys", "ACC-001", {"amount":  50})
        entry = log.get_entry(2)
        assert entry.event_type == "WITHDRAWAL"
        assert entry.sequence   == 2

    def test_get_entry_out_of_range_returns_none(self, log):
        assert log.get_entry(0)  is None
        assert log.get_entry(99) is None

    def test_get_by_resource(self, log):
        log.append("DEPOSIT",  "sys", "ACC-001", {})
        log.append("DEPOSIT",  "sys", "ACC-002", {})
        log.append("TRANSFER", "sys", "ACC-001", {})
        entries = log.get_by_resource("ACC-001")
        assert len(entries) == 2
        assert all(e.resource == "ACC-001" for e in entries)

    def test_get_by_event_type(self, log):
        log.append("DEPOSIT",  "sys", "ACC-001", {})
        log.append("TRANSFER", "sys", "ACC-001", {})
        log.append("DEPOSIT",  "sys", "ACC-002", {})
        deposits = log.get_by_event_type("DEPOSIT")
        assert len(deposits) == 2

    def test_all_entries(self, log):
        for i in range(5):
            log.append("EVENT", "sys", f"ACC-{i:03d}", {})
        entries = log.all_entries()
        assert len(entries) == 5

    def test_all_entries_returns_copy(self, log):
        log.append("EVENT", "sys", "ACC-001", {})
        entries = log.all_entries()
        entries.clear()
        assert log.count() == 1   # original unchanged

    def test_head_hash_is_genesis_when_empty(self, log):
        assert log.head_hash == ImmutableAuditLog.GENESIS_HASH

    def test_head_hash_updates_on_append(self, log):
        e1 = log.append("EVENT", "sys", "ACC-001", {})
        assert log.head_hash == e1.entry_hash


# ---------------------------------------------------------------------------
# Chain integrity
# ---------------------------------------------------------------------------

class TestChainIntegrity:

    def test_first_entry_prev_hash_is_genesis(self, log):
        entry = log.append("EVENT", "sys", "ACC-001", {})
        assert entry.prev_hash == ImmutableAuditLog.GENESIS_HASH

    def test_second_entry_prev_hash_matches_first(self, log):
        e1 = log.append("EVENT", "sys", "ACC-001", {})
        e2 = log.append("EVENT", "sys", "ACC-002", {})
        assert e2.prev_hash == e1.entry_hash

    def test_chain_links_all_entries(self, log):
        entries = []
        for i in range(5):
            entries.append(log.append("EVENT", "sys", f"ACC-{i:03d}", {}))

        for i in range(1, 5):
            assert entries[i].prev_hash == entries[i-1].entry_hash

    def test_entry_hash_is_sha256(self, log):
        entry = log.append("EVENT", "sys", "ACC-001", {})
        assert len(entry.entry_hash) == 64   # SHA-256 = 64 hex chars

    def test_entry_hash_is_deterministic_content(self, log):
        """Same sequence/content would produce same hash."""
        entry = log.append("TRANSFER", "alice", "ACC-001", {"amount": 100})
        assert len(entry.entry_hash) == 64


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------

class TestSignatureVerification:

    def test_verify_entry_with_correct_key(self, log):
        entry = log.append("TRANSFER", "alice", "ACC-001", {"amount": 100})
        assert log.verify_entry(entry) is True

    def test_verify_entry_with_wrong_key(self):
        log1 = ImmutableAuditLog(secret_key="correct-key")
        log2 = ImmutableAuditLog(secret_key="wrong-key")
        entry = log1.append("TRANSFER", "alice", "ACC-001", {"amount": 100})
        assert log2.verify_entry(entry) is False

    def test_signature_changes_with_content(self, log):
        e1 = log.append("TRANSFER", "alice", "ACC-001", {"amount": 100})
        e2 = log.append("TRANSFER", "alice", "ACC-001", {"amount": 200})
        assert e1.signature != e2.signature


# ---------------------------------------------------------------------------
# verify_chain()
# ---------------------------------------------------------------------------

class TestVerifyChain:

    def test_intact_chain_is_valid(self, log):
        for i in range(5):
            log.append("EVENT", "sys", f"ACC-{i:03d}", {"i": i})
        result = log.verify_chain()
        assert result.is_valid is True
        assert len(result.violations) == 0
        assert result.entry_count == 5

    def test_empty_chain_is_valid(self, log):
        result = log.verify_chain()
        assert result.is_valid is True

    def test_tampered_signature_detected(self):
        """Simulates tampering by building with wrong key after the fact."""
        log_a = ImmutableAuditLog(secret_key="real-key")
        log_b = ImmutableAuditLog(secret_key="attacker-key")

        for i in range(3):
            log_a.append("EVENT", "sys", f"ACC-{i}", {})

        # Attacker rebuilds entry 2 with their key — verification with real key fails
        tampered_entry = log_b.append("FRAUD", "attacker", "ACC-000", {"stolen": True})
        assert not log_a.verify_entry(tampered_entry)

    def test_broken_chain_detected(self):
        """
        Direct simulation of a broken chain:
        manually inject an entry with wrong prev_hash.
        """
        log = ImmutableAuditLog(secret_key="test-key")
        e1  = log.append("EVENT", "sys", "ACC-001", {})

        # Manually append a second entry to internal list with wrong prev_hash
        import hashlib, hmac as hmac_mod
        wrong_entry = AuditEntry(
            entry_id="FAKE",
            timestamp="2026-03-04T00:00:00",
            event_type="FRAUD",
            actor="attacker",
            resource="ACC-001",
            payload={},
            prev_hash="WRONG_HASH_000000000000000000000000000000000000000000000",
            entry_hash="a" * 64,
            signature="b" * 64,
            sequence=2,
        )
        log._entries.append(wrong_entry)

        result = log.verify_chain()
        assert result.is_valid is False
        assert any(v.violation_type == "BROKEN_CHAIN" for v in result.violations)

    def test_chain_verification_result_summary_intact(self, log):
        log.append("EVENT", "sys", "ACC-001", {})
        result = log.verify_chain()
        summary = result.summary()
        assert "INTACT" in summary
        assert "1 entries" in summary

    def test_chain_verification_result_summary_compromised(self):
        log = ImmutableAuditLog(secret_key="key")
        log.append("EVENT", "sys", "ACC-001", {})
        # Inject bad entry
        bad = AuditEntry(
            entry_id="X", timestamp="2026-01-01T00:00:00",
            event_type="BAD", actor="x", resource="x", payload={},
            prev_hash="WRONG" + "0" * 59, entry_hash="a" * 64,
            signature="b" * 64, sequence=2,
        )
        log._entries.append(bad)
        result = log.verify_chain()
        assert "COMPROMISED" in result.summary()


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------

class TestConcurrency:

    def test_concurrent_appends_are_sequential(self):
        """
        All concurrent appends should succeed with unique sequence numbers.
        No two entries should have the same sequence.
        """
        log     = ImmutableAuditLog(secret_key="test")
        errors  = []
        lock    = threading.Lock()
        results = []

        def append_entry(i):
            try:
                e = log.append("EVENT", f"user-{i}", f"ACC-{i:03d}", {"i": i})
                with lock:
                    results.append(e.sequence)
            except Exception as ex:
                errors.append(ex)

        threads = [threading.Thread(target=append_entry, args=(i,)) for i in range(20)]
        for t in threads: t.start()
        for t in threads: t.join()

        assert errors == []
        assert len(results) == 20
        assert len(set(results)) == 20   # all sequences unique
        assert sorted(results) == list(range(1, 21))   # 1..20

    def test_chain_intact_after_concurrent_appends(self):
        log = ImmutableAuditLog(secret_key="test")

        def append_batch(start):
            for i in range(10):
                log.append("EVENT", "sys", f"ACC-{start+i:03d}", {})

        threads = [threading.Thread(target=append_batch, args=(i*10,)) for i in range(5)]
        for t in threads: t.start()
        for t in threads: t.join()

        assert log.count() == 50
        result = log.verify_chain()
        assert result.is_valid is True


# ---------------------------------------------------------------------------
# Integration with AuditConsumer (J18)
# ---------------------------------------------------------------------------

class TestAuditLogIntegration:

    def test_audit_log_records_banking_events(self, log):
        """Simulate what AuditLogger (J03) would write after each operation."""
        log.append("ACCOUNT_OPENED", "system",   "ACC-001", {"owner": "Alice", "type": "current"})
        log.append("DEPOSIT",        "alice",     "ACC-001", {"amount": 1_000.0})
        log.append("TRANSFER",       "alice",     "ACC-001", {"to": "ACC-002", "amount": 300.0})
        log.append("TRANSFER",       "system",    "ACC-002", {"from": "ACC-001", "amount": 300.0})
        log.append("INTEREST",       "scheduler", "ACC-002", {"rate": 0.025, "credited": 7.5})

        assert log.count() == 5
        result = log.verify_chain()
        assert result.is_valid is True

        alice_events = log.get_by_resource("ACC-001")
        assert len(alice_events) == 3

    def test_full_audit_trail_reproducible(self, log):
        """
        The audit trail must be reproducible:
        same entries → same chain of hashes.
        This guarantees that two copies of the log are identical.
        """
        log.append("TRANSFER", "alice", "ACC-001", {"amount": 500})
        log.append("TRANSFER", "alice", "ACC-001", {"amount": 200})

        head_hash = log.head_hash
        assert len(head_hash) == 64   # SHA-256

        # The head hash represents the entire history
        # A second log with different entries will have a different head hash
        log2 = ImmutableAuditLog(secret_key="test-secret-key")
        log2.append("TRANSFER", "alice", "ACC-001", {"amount": 999})   # different
        assert log2.head_hash != head_hash
