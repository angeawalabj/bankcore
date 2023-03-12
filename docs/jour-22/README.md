# Jour 22 — CQRS (Command Query Responsibility Segregation)

## Le principe

> "Un objet ne devrait pas avoir de méthodes qui causent des effets de bord
> ET des méthodes qui retournent des valeurs sans effets de bord."
> — Bertrand Meyer (CQS, 1988)

CQRS est l'application de ce principe à l'échelle architecturale.

**Command** : modifie l'état. Ne retourne pas de données.
**Query** : lit l'état. N'a aucun effet de bord.

Les deux chemins sont complètement séparés.

---

## Pourquoi CQRS dans BankCore

Le `BankApplicationService` (J11) utilise le même `AccountRegistry`
pour lire et écrire. Problèmes en production :

```
Dashboard : 10 000 GET /accounts/balance en 30 secondes
Virements : 500 POST /transfers en 30 secondes

→ Les lectures bloquent les écritures sur le même objet
→ Impossible d'optimiser le Read Model sans impacter le Write Model
→ Impossible de scaler les reads indépendamment des writes
```

---

## Architecture CQRS dans BankCore

```
┌──────────────────────────────────────────────────────────┐
│                    Write Side                             │
│                                                          │
│  TransferCommand ──> AccountCommandHandler               │
│                         │ append events                  │
│                         ▼                                │
│                    EventStore (J21)                       │
│                         │ publish events                 │
│                         ▼                                │
│                    MessageBus (J18)                       │
└──────────────────────────────────────────────────────────┘
                          │ consume events
┌──────────────────────────────────────────────────────────┐
│                    Read Side                             │
│                                                          │
│  BalanceReadModel ◄── ProjectionUpdater                  │
│  AccountListReadModel                                     │
│  TransactionHistoryReadModel                             │
│                                                          │
│  BalanceQuery ──> QueryHandler ──> ReadModel             │
└──────────────────────────────────────────────────────────┘
```

---

## Cohérence éventuelle

Dans CQRS, le Read Model est **éventuellement cohérent** avec le Write Model.

```
1. Transfer command received
2. Events appended to EventStore     ← Write completed ✓
3. Response returned to client       ← Client gets confirmation
4. [async] Projection updated        ← Read Model updated (ms later)
5. Next GET /balance returns new balance
```

Gap entre 3 et 5 : le solde affiché peut être légèrement en retard.
Acceptable pour un dashboard. Inacceptable pour le processeur de transaction
(qui lit toujours depuis l'EventStore, pas le Read Model).

---

## Read Models implémentés

| Read Model | Optimisé pour |
|-----------|--------------|
| `BalanceReadModel` | GET /accounts/{id}/balance — milliseconde |
| `AccountSummaryReadModel` | Dashboard — liste paginée avec soldes |
| `TransactionHistoryReadModel` | Historique — tri, filtre, pagination |

---

## Connexion avec les jours précédents

- **J11 (Use Cases)** : Commands et Queries remplacent certains Use Cases
- **J21 (Event Sourcing)** : Write side utilise l'EventStore de J21
- **J18 (Message Queue)** : les events publiés mettent à jour les Read Models
- **J14 (Specification)** : les Queries utilisent les Specs de J14 pour filtrer
