# Jour 23 — Saga Pattern

## Le problème

Un virement international traverse plusieurs services :

```
1. Débit compte source (AccountService France)
2. Appel service de conversion EUR → GBP (FxService)
3. Crédit compte destination (AccountService UK)
4. Notification (NotificationService)
5. Archivage compliance (AuditService)
```

**Le problème :** sans mécanisme de coordination, si l'étape 3 échoue,
l'étape 1 est déjà exécutée — Alice est débitée, Bob n'est pas crédité.

**La solution classique (2PC - Two-Phase Commit) :**
```
Phase 1 : tous les services votent "prêt"
Phase 2 : coordinateur envoie "commit" ou "rollback"
```
Problème : bloquant, couplé, ne passe pas à l'échelle des microservices.

---

## La solution : Saga Pattern

> "Une séquence de transactions locales, chacune publiante un événement
> ou message pour déclencher la prochaine transaction.
> Si une étape échoue, la saga exécute des transactions compensatrices."
> — Hector Garcia-Molina, Kenneth Salem (1987)

**Deux variantes :**
- **Choreography** : chaque service écoute les events et réagit
- **Orchestration** : un orchestrateur centralisé dirige les étapes

BankCore J23 implémente **l'orchestration** — plus lisible, plus facile
à déboguer, plus naturel pour un système bancaire régulé.

---

## Saga d'un virement international

```
InternationalTransferSaga
  │
  ├── Step 1: DebitSourceStep
  │     execute()    → alice.withdraw(100 EUR)
  │     compensate() → alice.deposit(100 EUR)   ← annulation
  │
  ├── Step 2: ConvertCurrencyStep
  │     execute()    → fx_service.convert(100 EUR → 87 GBP)
  │     compensate() → (rien — pas d'argent déplacé)
  │
  ├── Step 3: CreditDestinationStep
  │     execute()    → bob.deposit(87 GBP)
  │     compensate() → bob.withdraw(87 GBP)     ← annulation
  │
  └── Step 4: NotifyStep
        execute()    → send_notification()
        compensate() → send_cancellation_notice()
```

**Si Step 3 échoue :**
```
Compensation: Step 2 → (rien), Step 1 → alice.deposit(100 EUR)
Alice retrouve ses 100 EUR. Bob n'est jamais crédité.
```

---

## États de la Saga

```
PENDING → RUNNING → COMPLETED
                  → COMPENSATING → COMPENSATED
                                 → FAILED (compensation aussi échouée)
```

---

## Connexion avec les jours précédents

- **J16 (Microservices)** : chaque Step appelle un ServiceClient (J16)
- **J18 (MessageBus)** : la Saga publie des events à chaque étape
- **J21 (EventStore)** : l'état de la Saga est lui-même event-sourcé
- **J24 (Circuit Breaker)** : les Steps utilisent le Circuit Breaker
  pour détecter les services indisponibles avant de tenter
