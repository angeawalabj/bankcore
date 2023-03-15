# Jour 25 — Bulkhead + Retry avec Backoff Exponentiel

## Bulkhead Pattern

> "Compartimenter la navire : si un compartiment est inondé,
> les autres restent étanches."
> — Naval architecture → Michael Nygard, Release It! (2007)

**Le problème sans Bulkhead :**
```
AccountService répond lentement (2s au lieu de 5ms)

Thread pool: [T1][T2][T3][T4][T5][T6][T7][T8]

T1 → AccountService.get_account (bloqué 2s)
T2 → AccountService.get_account (bloqué 2s)
...
T8 → AccountService.get_account (bloqué 2s)

Tous les threads bloqués → TransactionService ne peut
plus traiter AUCUNE requête, même celles qui n'ont pas
besoin d'AccountService (ex: listing des transactions)
```

**Avec Bulkhead :**
```
Thread pool: [T1..T4 → AccountService] [T5..T8 → autres]

Si AccountService sature : T1-T4 bloqués, T5-T8 libres
TransactionService continue à répondre sur les autres routes
```

---

## Retry avec Backoff Exponentiel

**Le problème sans Retry :**
```
AccountService fait un GC de 200ms
T1 → AccountService.get_account → timeout → ECHEC DEFINITIF
→ Virement échoue alors qu'un retry 300ms plus tard aurait marché
```

**Avec Retry + Backoff :**
```
Tentative 1 → ECHEC → wait 100ms
Tentative 2 → ECHEC → wait 200ms
Tentative 3 → ECHEC → wait 400ms
Tentative 4 → SUCCES ✓
```

**Pourquoi le backoff exponentiel (pas fixe) :**
Si 1000 clients retirent en même temps, un délai fixe les fait
tous retenter au même instant → thundering herd → service surchargé.
Le backoff exponentiel + jitter étale les retries dans le temps.

---

## Jitter

```
backoff = base * (2^attempt)
jitter  = random(0, backoff * 0.1)
wait    = backoff + jitter
```

100ms → (200ms ± 20ms) → (400ms ± 40ms) → (800ms ± 80ms)

---

## Combinaison : Retry wrappé dans Bulkhead

```
BulkheadRetryClient
  │
  ├── Bulkhead: max 4 concurrent calls to AccountService
  │
  └── Retry: up to 3 attempts with exponential backoff
       │
       └── CircuitBreaker (J24): open if failures persist
```

---

## Ce que J25 livre

- `Bulkhead`: semaphore-based concurrency limiter
- `RetryPolicy`: backoff exponentiel + jitter + max retries
- `BulkheadRetryClient`: Decorator (J05) qui combine les deux
- Tests: `test_bulkhead_retry.py`
