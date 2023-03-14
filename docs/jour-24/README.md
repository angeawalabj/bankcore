# Jour 24 — Circuit Breaker

## Le problème concret

```
AccountService répond en 0.5ms en temps normal.
Incident réseau : AccountService répond en 5s (timeout).

Sans Circuit Breaker:
  - Chaque appel bloque 5s
  - 100 requêtes simultanées = 100 threads bloqués
  - File d'attente s'accumule → mémoire épuisée → crash TransactionService

Avec Circuit Breaker:
  - Les 3 premiers appels échouent en 5s (CLOSED → OPEN)
  - Les appels suivants échouent en <1ms (circuit ouvert)
  - Après 30s, 1 appel test (HALF-OPEN)
  - Si succès → CLOSED. Si échec → OPEN 30s de plus.
```

---

## Les trois états

```
                  successes < threshold
    ┌──────────────────────────────────────────┐
    │                                          │
    ▼          failures >= threshold           │
CLOSED ──────────────────────────────────> OPEN
    ▲                                       │
    │                                       │ after recovery_timeout
    │           probe succeeds              ▼
    └──────────────────────────────── HALF-OPEN
                                           │
                                           │ probe fails
                                           ▼
                                         OPEN (reset timer)
```

---

## Paramètres configurables

| Paramètre | Défaut | Description |
|-----------|--------|-------------|
| `failure_threshold` | 5 | Échecs consécutifs avant OPEN |
| `recovery_timeout` | 30s | Durée OPEN avant HALF-OPEN |
| `success_threshold` | 2 | Succès consécutifs en HALF-OPEN pour CLOSED |

---

## Dégradation gracieuse

Quand le circuit est OPEN, plusieurs stratégies possibles :
1. **Fail fast** : retourner immédiatement une erreur (défaut)
2. **Fallback** : retourner une valeur par défaut ou depuis le cache
3. **Queue** : mettre en file d'attente pour retry plus tard

BankCore J24 implémente fail fast + fallback optionnel.
Le Circuit Breaker wraps `ServiceClient` — même interface.

---

## Connexion avec les jours précédents

- **J16 (ServiceClient)** : CircuitBreakerClient wrappe ServiceClient
- **J17 (Cache)** : fallback = servir depuis le cache si circuit ouvert
- **J20 (Metrics)** : circuit state changes → métriques + alertes
- **J24 wraps J16** : `TransactionMicroservice` reçoit un
  `CircuitBreakerClient` à la place du `ServiceClient` direct
