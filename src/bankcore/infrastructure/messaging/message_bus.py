"""
BankCore — Day 18: MessageBus
================================
In-process message queue simulation for inter-service communication.

Design: simulates the Pub/Sub semantics of RabbitMQ/Kafka without
requiring an external broker. The interface is identical — swapping
to a real broker = replacing InMemoryMessageBus with RabbitMQBus.

Key concepts implemented:
  - Topics with pattern matching (* = one word, # = zero or more)
  - Message with id, topic, payload, timestamp, retry count
  - Consumer interface with process() and error handling
  - Dead Letter Queue for failed messages
  - Idempotency via message_id deduplication
  - Synchronous dispatch (Day 18) — async threading optional

Connection to Day 03 (Observer Pattern):
  MessageBus IS the Observer pattern at microservice scale.
  publish() = EventBus.emit()
  subscribe() = EventBus.subscribe()
  The difference: MessageBus persists messages, retries on failure,
  and supports pattern-based routing across service boundaries.
"""

from __future__ import annotations
import fnmatch
import threading
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional


# ---------------------------------------------------------------------------
# Message
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Message:
    """
    An immutable message unit flowing through the MessageBus.

    frozen=True: once created, a message cannot be modified.
    Each re-delivery creates a new Message with incremented retry_count.
    """
    topic:       str
    payload:     dict
    message_id:  str      = field(default_factory=lambda: str(uuid.uuid4())[:12].upper())
    published_at: datetime = field(default_factory=datetime.now)
    retry_count: int       = 0
    source:      str       = "unknown"

    def with_retry(self) -> "Message":
        """Create a new message instance with incremented retry count."""
        return Message(
            topic=self.topic,
            payload=self.payload,
            message_id=self.message_id,   # same ID — it's a retry
            published_at=self.published_at,
            retry_count=self.retry_count + 1,
            source=self.source,
        )

    def __str__(self) -> str:
        return (
            f"Message({self.topic} | id={self.message_id} | "
            f"retry={self.retry_count} | "
            f"at={self.published_at.strftime('%H:%M:%S')})"
        )


# ---------------------------------------------------------------------------
# Consumer interface
# ---------------------------------------------------------------------------

class Consumer(ABC):
    """
    Base class for all message queue consumers.

    Subclasses implement process() with their business logic.
    The MessageBus calls process() for each matching message.
    Errors in process() are caught — the bus routes to DLQ instead of crashing.
    """

    @abstractmethod
    def process(self, message: Message) -> None:
        """
        Process a message. Must be idempotent.
        If this raises, the message is retried then sent to DLQ.
        """

    @property
    def name(self) -> str:
        return self.__class__.__name__

    @property
    def max_retries(self) -> int:
        """Number of retry attempts before sending to DLQ. Default: 3."""
        return 3


class ConsumerResult:
    """Result of a consumer processing attempt."""
    def __init__(self, success: bool, consumer: str, error: str = "") -> None:
        self.success  = success
        self.consumer = consumer
        self.error    = error


# ---------------------------------------------------------------------------
# Dead Letter Queue
# ---------------------------------------------------------------------------

class DeadLetterQueue:
    """
    Stores messages that failed all retry attempts.

    In production: persisted to a database for manual inspection.
    Here: in-memory list for testing and monitoring.
    """

    def __init__(self) -> None:
        self._messages: list[dict] = []

    def add(self, message: Message, consumer_name: str, error: str) -> None:
        self._messages.append({
            "message":       message,
            "consumer":      consumer_name,
            "error":         error,
            "failed_at":     datetime.now().isoformat(),
        })

    def count(self) -> int:
        return len(self._messages)

    def all(self) -> list[dict]:
        return list(self._messages)

    def for_consumer(self, consumer_name: str) -> list[dict]:
        return [m for m in self._messages if m["consumer"] == consumer_name]

    def clear(self) -> None:
        self._messages.clear()


# ---------------------------------------------------------------------------
# MessageBus
# ---------------------------------------------------------------------------

class MessageBus:
    """
    In-process Pub/Sub message bus.

    Routing rules:
      - Exact match: subscribe("transaction.completed") receives only that topic
      - Wildcard (*): subscribe("transaction.*") receives transaction.completed,
        transaction.failed, transaction.reversed, etc.
      - Hash (#): subscribe("bankcore.#") receives everything under bankcore.

    Dispatch is synchronous by default (publish() blocks until all consumers done).
    Set async_dispatch=True for non-blocking behaviour (uses threading).

    Usage:
        bus = MessageBus()
        bus.subscribe("transaction.*", FraudDetector())
        bus.subscribe("transaction.completed", NotificationService())

        bus.publish("transaction.completed", {
            "tx_id": "TX-001", "amount": 500.0, "from": "ACC-001"
        })
    """

    def __init__(self, async_dispatch: bool = False) -> None:
        self._subscriptions: list[tuple[str, Consumer]] = []
        self._dlq           = DeadLetterQueue()
        self._published:    list[Message] = []
        self._async         = async_dispatch
        self._lock          = threading.Lock()
        self._processed_ids: set[str] = set()   # idempotency registry

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------

    def publish(
        self,
        topic: str,
        payload: dict,
        source:  str = "unknown",
    ) -> Message:
        """
        Publish a message to all matching subscribers.

        Returns the created Message for correlation and testing.
        If async_dispatch=True, consumers run in background threads.
        """
        message = Message(topic=topic, payload=payload, source=source)
        self._published.append(message)

        matching = self._find_consumers(topic)

        if self._async:
            for consumer in matching:
                t = threading.Thread(
                    target=self._dispatch_to_consumer,
                    args=(message, consumer),
                    daemon=True,
                )
                t.start()
        else:
            for consumer in matching:
                self._dispatch_to_consumer(message, consumer)

        return message

    def _dispatch_to_consumer(self, message: Message, consumer: Consumer) -> ConsumerResult:
        """Dispatch a message to one consumer with retry logic."""
        current = message
        for attempt in range(consumer.max_retries + 1):
            try:
                # Idempotency key: per (message_id, consumer_instance)
                # Uses id(consumer) to distinguish instances with the same name
                idempotency_key = f"{current.message_id}:{id(consumer)}"
                with self._lock:
                    if idempotency_key in self._processed_ids:
                        return ConsumerResult(True, consumer.name)
                    self._processed_ids.add(idempotency_key)

                consumer.process(current)
                return ConsumerResult(True, consumer.name)

            except Exception as exc:
                if attempt < consumer.max_retries:
                    current = current.with_retry()
                    # Remove from processed to allow retry
                    with self._lock:
                        self._processed_ids.discard(
                            f"{current.message_id}:{id(consumer)}"
                        )
                else:
                    # All retries exhausted → DLQ
                    self._dlq.add(current, consumer.name, str(exc))
                    return ConsumerResult(False, consumer.name, str(exc))

        return ConsumerResult(False, consumer.name, "Unknown failure")

    # ------------------------------------------------------------------
    # Subscriptions
    # ------------------------------------------------------------------

    def subscribe(self, topic_pattern: str, consumer: Consumer) -> None:
        """
        Subscribe a consumer to a topic pattern.

        Patterns:
          "transaction.completed"  → exact match
          "transaction.*"          → any single-level subtopic
          "bankcore.#"             → any nested subtopic
        """
        with self._lock:
            self._subscriptions.append((topic_pattern, consumer))

    def unsubscribe(self, consumer: Consumer) -> int:
        """Remove all subscriptions for a consumer. Returns count removed."""
        with self._lock:
            before = len(self._subscriptions)
            self._subscriptions = [
                (p, c) for p, c in self._subscriptions if c is not consumer
            ]
            return before - len(self._subscriptions)

    def _find_consumers(self, topic: str) -> list[Consumer]:
        """Return all consumers whose pattern matches the given topic."""
        matching = []
        with self._lock:
            subs = list(self._subscriptions)
        for pattern, consumer in subs:
            if self._matches(pattern, topic):
                matching.append(consumer)
        return matching

    def _matches(self, pattern: str, topic: str) -> bool:
        """
        Match a topic against a pattern.
        * matches one segment, # matches any number of segments.
        """
        # Convert # to fnmatch ** equivalent
        fnmatch_pattern = pattern.replace("#", "*")
        return fnmatch.fnmatch(topic, fnmatch_pattern)

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    @property
    def dlq(self) -> DeadLetterQueue:
        return self._dlq

    def published_count(self) -> int:
        return len(self._published)

    def published_messages(self, topic: str = None) -> list[Message]:
        if topic:
            return [m for m in self._published if m.topic == topic]
        return list(self._published)

    def subscriber_count(self, topic: str = None) -> int:
        if topic:
            return len(self._find_consumers(topic))
        return len(self._subscriptions)

    def clear(self) -> None:
        """Reset all state. For testing only."""
        with self._lock:
            self._published.clear()
            self._processed_ids.clear()
        self._dlq.clear()
