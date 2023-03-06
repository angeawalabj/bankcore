"""
BankCore — Day 18: Message Consumers
=======================================
Concrete consumer implementations for BankCore's MessageBus.

Each consumer is a microservice subscriber that reacts to domain events.
They implement process() and are completely decoupled from TransactionService.

Consumers implemented:
  - FraudDetectionConsumer  : flags suspicious transactions
  - NotificationConsumer    : sends SMS/email alerts
  - AnalyticsConsumer       : records transaction metrics
  - CacheInvalidationConsumer: invalidates stale cache entries (J17 + J18)
  - AuditConsumer           : append-only compliance log

Connection to Day 03 (Observer):
  These consumers ARE AlertObservers, but at microservice scale.
  Day 03 observers reacted synchronously in the same process.
  Day 18 consumers react asynchronously across service boundaries.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from bankcore.infrastructure.messaging.message_bus import Consumer, Message


# ---------------------------------------------------------------------------
# Topic constants — single source of truth for event names
# ---------------------------------------------------------------------------

class Topics:
    """
    Centralized topic name registry.
    Prevents typos: use Topics.TRANSFER_COMPLETED, not 'transaction.completed'.
    """
    # Transaction events
    TRANSFER_COMPLETED   = "transaction.completed"
    TRANSFER_FAILED      = "transaction.failed"
    DEPOSIT_COMPLETED    = "transaction.deposit"
    WITHDRAWAL_COMPLETED = "transaction.withdrawal"

    # Account events
    ACCOUNT_CREATED      = "account.created"
    BALANCE_UPDATED      = "account.balance.updated"

    # Alert events
    FRAUD_SUSPECTED      = "alert.fraud"
    LOW_BALANCE          = "alert.low_balance"


# ---------------------------------------------------------------------------
# FraudDetectionConsumer
# ---------------------------------------------------------------------------

@dataclass
class FraudAlert:
    """A flagged transaction for human review."""
    tx_id:       str
    reason:      str
    amount:      float
    account_id:  str
    detected_at: str = field(default_factory=lambda: datetime.now().isoformat())


class FraudDetectionConsumer(Consumer):
    """
    Analyses completed transactions for suspicious patterns.
    Subscribes to: transaction.*

    Rules (simplified — Day 21 adds ML-based detection):
      - Amount > threshold → flag
      - Same account more than N transactions in window → flag
    """

    def __init__(
        self,
        amount_threshold: float = 5_000.0,
        max_tx_per_minute: int  = 5,
    ) -> None:
        self._threshold     = amount_threshold
        self._max_per_min   = max_tx_per_minute
        self._alerts:  list[FraudAlert] = []
        self._tx_times: dict[str, list[datetime]] = {}   # account_id → timestamps

    def process(self, message: Message) -> None:
        payload    = message.payload
        amount     = payload.get("amount", 0)
        account_id = payload.get("from_account_id") or payload.get("account_id", "")
        tx_id      = payload.get("tx_id", "")

        # Rule 1: Large transaction
        if amount > self._threshold:
            self._alerts.append(FraudAlert(
                tx_id=tx_id,
                reason=f"Large transaction: {amount:.2f} > threshold {self._threshold:.2f}",
                amount=amount,
                account_id=account_id,
            ))

        # Rule 2: High frequency
        if account_id:
            now    = datetime.now()
            cutoff = now.replace(second=max(0, now.second - 60))
            times  = self._tx_times.get(account_id, [])
            recent = [t for t in times if t >= cutoff]
            recent.append(now)
            self._tx_times[account_id] = recent

            if len(recent) > self._max_per_min:
                self._alerts.append(FraudAlert(
                    tx_id=tx_id,
                    reason=(
                        f"High frequency: {len(recent)} transactions "
                        f"in last minute (max {self._max_per_min})"
                    ),
                    amount=amount,
                    account_id=account_id,
                ))

    @property
    def alerts(self) -> list[FraudAlert]:
        return list(self._alerts)

    def alert_count(self) -> int:
        return len(self._alerts)

    @property
    def name(self) -> str:
        return "FraudDetectionConsumer"


# ---------------------------------------------------------------------------
# NotificationConsumer
# ---------------------------------------------------------------------------

@dataclass
class Notification:
    """A notification sent to an account holder."""
    account_id: str
    channel:    str   # "sms", "email", "push"
    message:    str
    sent_at:    str = field(default_factory=lambda: datetime.now().isoformat())


class NotificationConsumer(Consumer):
    """
    Sends notifications to account holders.
    Subscribes to: transaction.*, alert.*

    In production: calls SMS gateway, email service.
    Here: records notifications for testing.
    """

    def __init__(self) -> None:
        self._notifications: list[Notification] = []

    def process(self, message: Message) -> None:
        payload    = message.payload
        account_id = (
            payload.get("from_account_id") or
            payload.get("account_id") or
            "unknown"
        )
        amount = payload.get("amount", 0)

        if message.topic == Topics.TRANSFER_COMPLETED:
            text = (
                f"Transfer of {amount:.2f} EUR completed. "
                f"New balance: {payload.get('from_balance_after', 'N/A'):.2f} EUR."
            )
            self._notifications.append(
                Notification(account_id=account_id, channel="sms", message=text)
            )

        elif message.topic == Topics.DEPOSIT_COMPLETED:
            text = f"Deposit of {amount:.2f} EUR received."
            self._notifications.append(
                Notification(account_id=account_id, channel="sms", message=text)
            )

        elif message.topic == Topics.FRAUD_SUSPECTED:
            text = f"Security alert: suspicious activity on your account."
            self._notifications.append(
                Notification(account_id=account_id, channel="email", message=text)
            )

    @property
    def notifications(self) -> list[Notification]:
        return list(self._notifications)

    def notification_count(self) -> int:
        return len(self._notifications)

    def for_account(self, account_id: str) -> list[Notification]:
        return [n for n in self._notifications if n.account_id == account_id]

    @property
    def name(self) -> str:
        return "NotificationConsumer"


# ---------------------------------------------------------------------------
# AnalyticsConsumer
# ---------------------------------------------------------------------------

class AnalyticsConsumer(Consumer):
    """
    Records transaction metrics for reporting.
    Subscribes to: transaction.*

    Tracks:
      - Total transaction volume
      - Transaction count by type
      - Average transaction amount
    """

    def __init__(self) -> None:
        self._records:      list[dict] = []
        self._volume_by_type: dict[str, float] = {}
        self._count_by_type:  dict[str, int]   = {}

    def process(self, message: Message) -> None:
        payload = message.payload
        amount  = float(payload.get("amount", 0))
        tx_type = message.topic.split(".")[-1]   # "completed", "deposit", etc.

        self._records.append({
            "tx_id":    payload.get("tx_id", ""),
            "type":     tx_type,
            "amount":   amount,
            "recorded": datetime.now().isoformat(),
        })

        self._volume_by_type[tx_type] = self._volume_by_type.get(tx_type, 0) + amount
        self._count_by_type[tx_type]  = self._count_by_type.get(tx_type, 0) + 1

    @property
    def total_volume(self) -> float:
        return sum(r["amount"] for r in self._records)

    @property
    def total_count(self) -> int:
        return len(self._records)

    def volume_by_type(self, tx_type: str) -> float:
        return self._volume_by_type.get(tx_type, 0.0)

    def count_by_type(self, tx_type: str) -> int:
        return self._count_by_type.get(tx_type, 0)

    @property
    def average_amount(self) -> float:
        if not self._records:
            return 0.0
        return self.total_volume / self.total_count

    @property
    def name(self) -> str:
        return "AnalyticsConsumer"


# ---------------------------------------------------------------------------
# CacheInvalidationConsumer
# ---------------------------------------------------------------------------

class CacheInvalidationConsumer(Consumer):
    """
    Invalidates cache entries when account data changes.
    Subscribes to: account.balance.updated

    Connects Day 17 (Cache) with Day 18 (Message Queue):
    TransactionService publishes balance updates → this consumer
    invalidates the CachingServiceClient's entries.

    This eliminates the need for TransactionService to know about
    the cache — pure decoupling through messaging.
    """

    def __init__(self, caching_client) -> None:
        self._client = caching_client
        self._invalidated: list[str] = []

    def process(self, message: Message) -> None:
        account_id = message.payload.get("account_id")
        if account_id:
            self._client.invalidate(account_id)
            self._invalidated.append(account_id)

    @property
    def invalidated_accounts(self) -> list[str]:
        return list(self._invalidated)

    def invalidation_count(self) -> int:
        return len(self._invalidated)

    @property
    def name(self) -> str:
        return "CacheInvalidationConsumer"


# ---------------------------------------------------------------------------
# AuditConsumer
# ---------------------------------------------------------------------------

class AuditConsumer(Consumer):
    """
    Compliance-grade audit log. Subscribes to ALL events (#).
    Every message is appended — records are never deleted.
    Idempotent: duplicate messages are ignored via message_id.
    """

    def __init__(self) -> None:
        self._log:         list[dict] = []
        self._seen_ids:    set[str]   = set()

    def process(self, message: Message) -> None:
        # Idempotency guard (belt-and-suspenders on top of MessageBus's own guard)
        if message.message_id in self._seen_ids:
            return
        self._seen_ids.add(message.message_id)

        self._log.append({
            "message_id":  message.message_id,
            "topic":       message.topic,
            "source":      message.source,
            "payload":     message.payload,
            "received_at": datetime.now().isoformat(),
            "retry_count": message.retry_count,
        })

    @property
    def log(self) -> list[dict]:
        return list(self._log)

    def log_count(self) -> int:
        return len(self._log)

    def entries_for_topic(self, topic: str) -> list[dict]:
        return [e for e in self._log if e["topic"] == topic]

    @property
    def name(self) -> str:
        return "AuditConsumer"


# ---------------------------------------------------------------------------
# BrokenConsumer — for testing DLQ and resilience
# ---------------------------------------------------------------------------

class BrokenConsumer(Consumer):
    """Test double: always fails — used to verify DLQ behaviour."""

    def __init__(self, error_msg: str = "Simulated consumer failure") -> None:
        self._error_msg = error_msg

    def process(self, message: Message) -> None:
        raise RuntimeError(self._error_msg)

    @property
    def max_retries(self) -> int:
        return 1   # fail fast in tests

    @property
    def name(self) -> str:
        return "BrokenConsumer"
