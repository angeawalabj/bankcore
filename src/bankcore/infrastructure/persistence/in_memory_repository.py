"""
BankCore — Day 12: InMemoryAccountRepository (Infrastructure Adapter)
=======================================================================
Implements AccountRepositoryPort using a plain Python dict.

This is the first Infrastructure Adapter in BankCore's Clean Architecture.

Clean Architecture rule:
  - Port defined in Application: AccountRepositoryPort
  - Adapter defined in Infrastructure: InMemoryAccountRepository
  - Application imports the Port; Infrastructure imports the Port AND implements it
  - Application NEVER imports InMemoryAccountRepository directly

Swapping to SQLiteAccountRepository (Day 14):
  - Zero changes in Use Cases
  - Zero changes in the Port
  - Only the container wiring changes (one line)

This is the Clean Architecture promise made concrete.
"""

from __future__ import annotations
from typing import Optional, List

from bankcore.application.ports import AccountRepositoryPort


class InMemoryAccountRepository(AccountRepositoryPort):
    """
    In-memory implementation of AccountRepositoryPort.

    Day 14 update: supports find(spec, page, page_size) with
    Specification Pattern and pagination.
    """

    def __init__(self) -> None:
        self._store: dict[str, object] = {}

    def save(self, account) -> None:
        """Insert or update an account by its ID."""
        self._store[account.account_id] = account

    def find_by_id(self, account_id: str) -> Optional[object]:
        return self._store.get(account_id)

    def find_all(self) -> List[object]:
        return list(self._store.values())

    def find_by_owner(self, owner_name: str) -> List[object]:
        name = owner_name.strip().lower()
        return [
            a for a in self._store.values()
            if a.owner_name.lower() == name
        ]

    def count(self) -> int:
        return len(self._store)

    def exists(self, account_id: str) -> bool:
        return account_id in self._store

    def find(self, spec=None, page: int = 1, page_size: int = 20):
        """
        Find accounts matching a specification, with pagination.
        Day 14 (Repository Pattern): Specification Pattern integration.
        """
        from bankcore.application.specifications import AllSpec, Page
        spec = spec or AllSpec()
        matching = [a for a in self._store.values() if spec.is_satisfied_by(a)]
        total = len(matching)
        start = (page - 1) * page_size
        end   = start + page_size
        return Page(items=matching[start:end], total=total, page=page, page_size=page_size)

    def find_one(self, spec=None):
        """Return first account matching spec, or None."""
        from bankcore.application.specifications import AllSpec
        spec = spec or AllSpec()
        for account in self._store.values():
            if spec.is_satisfied_by(account):
                return account
        return None

    def count_spec(self, spec=None) -> int:
        """Count accounts matching a specification."""
        from bankcore.application.specifications import AllSpec
        spec = spec or AllSpec()
        return sum(1 for a in self._store.values() if spec.is_satisfied_by(a))

    def delete(self, account_id: str) -> bool:
        """Remove an account. Returns True if it existed."""
        if account_id in self._store:
            del self._store[account_id]
            return True
        return False

    def clear(self) -> None:
        """Remove all accounts. For testing only."""
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)

    def __repr__(self) -> str:
        return f"InMemoryAccountRepository({len(self._store)} accounts)"


class InMemoryDomainEventStore:
    """
    In-memory implementation of DomainEventStorePort.

    Stores domain events by aggregate_id.
    Day 21 (Event Sourcing) will replace this with an append-only
    SQLite store where events are never deleted or modified.
    """

    def __init__(self) -> None:
        self._events: dict[str, list] = {}

    def append(self, event) -> None:
        agg_id = str(event.aggregate_id)
        if agg_id not in self._events:
            self._events[agg_id] = []
        self._events[agg_id].append(event)

    def get_events_for(self, aggregate_id: str) -> list:
        return list(self._events.get(aggregate_id, []))

    def count(self) -> int:
        return sum(len(evts) for evts in self._events.values())

    def count_for(self, aggregate_id: str) -> int:
        return len(self._events.get(aggregate_id, []))

    def all_events(self) -> list:
        events = []
        for evts in self._events.values():
            events.extend(evts)
        return sorted(events, key=lambda e: e.occurred_at)

    def clear(self) -> None:
        self._events.clear()
