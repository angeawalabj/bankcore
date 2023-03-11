# Jour 21 — Event Sourcing

## Le principe

> "Ne stocker que les événements. L'état est une projection."

Au lieu de :
```sql
UPDATE account SET balance = 1500 WHERE id = 'ACC-001'
```

On fait :
```python
store.append(MoneyDeposited(aggregate_id="ACC-001", amount=Money.eur(500)))
```

Le solde 1500 EUR n'est jamais stocké directement.
Il est calculé en rejouant tous les événements du compte.

---

## Pourquoi Event Sourcing dans BankCore

Un système bancaire a des exigences d'auditabilité légales :
- **Qui** a fait **quoi** sur **quel compte** à **quelle heure** ?
- **Pourquoi** le solde est-il de X EUR maintenant ?
- **Pouvez-vous prouver** qu'aucune manipulation n'a eu lieu ?

Avec l'état mutable : impossible sans un audit log séparé (toujours
synchronisé ? Toujours complet ?).

Avec Event Sourcing : la réponse est dans le store. Les événements
sont immuables, ordonnés, et exhaustifs.

---

## Architecture

```
Client
  │
  ▼
AccountCommandHandler
  │ append(MoneyDeposited)
  ▼
EventStore ──── source of truth ────────────────────────────────
  │
  ├── AccountProjection ──> balance, owner, type (current state)
  ├── BalanceHistoryProjection ──> balance over time (reporting)
  └── AuditProjection ──> all events for compliance
```

---

## Les trois concepts clés

### 1. EventStore — append-only
```python
store.append(event)       # seule opération d'écriture
store.get_events("ACC-001")  # lecture chronologique
# JAMAIS: store.delete(), store.update()
```

### 2. Aggregate — reconstruit depuis les events
```python
account = AccountAggregate.from_events(
    store.get_events("ACC-001")
)
# account.balance est calculé, pas stocké
```

### 3. Projection — vue matérialisée
```python
projection = BalanceProjection()
for event in store.get_events("ACC-001"):
    projection.apply(event)
balance = projection.current_balance   # 1500 EUR
```

---

## Différence avec DomainEvent (J12)

`DomainEvent` (J12) : concept domaine abstrait — "quelque chose s'est passé".
`SourcedEvent` (J21) : événement persisté dans l'EventStore avec
  séquence, version, et checksum pour la détection de corruption.

---

## Ce que J21 livre

- `EventStore` : append-only avec version d'aggregate (optimistic locking)
- `AccountAggregate` : reconstruit depuis événements, zero état persisté
- `AccountProjection` : vue courante calculée depuis l'event stream
- `BalanceHistoryProjection` : évolution du solde dans le temps
- `AccountCommandHandler` : orchestre Command → Events → Store
- Tests : `test_event_sourcing.py`

---

## Connexion avec les jours précédents

- **J12 (DomainEvents)** : `MoneyDeposited`, `MoneyTransferred` sont
  exactement les événements persistés par l'EventStore
- **J14 (Repository)** : `EventStore` est un `DomainEventStorePort` (J12 port)
- **J22 (CQRS)** : les projections deviennent les "Read Models" de CQRS
