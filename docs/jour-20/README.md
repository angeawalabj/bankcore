# Jour 20 — Monitoring & Tracing Distribué

## Le problème concret

BankCore a maintenant 2 microservices, un cache, et une message queue.
Un virement traverse AccountService, TransactionService, le cache, et RabbitMQ.

```
Client → TransactionService → AccountService (GET ×2)
                            → AccountService (PATCH ×2)
                            → MessageBus (publish ×3)
                            → [FraudDetector, NotificationConsumer, AuditConsumer]
```

**Sans monitoring :**
- Un virement prend 2.3s. Pourquoi ? On ne sait pas.
- 5% des virements échouent. Quelle étape ? On ne sait pas.
- La charge a doublé. Quel service est le goulot ? On ne sait pas.

---

## Les trois piliers de l'observabilité

### 1. Métriques (Metrics)
Valeurs numériques agrégées dans le temps.
- `bankcore.transfers.count` : nombre de virements
- `bankcore.transfers.latency_p95` : P95 de latence
- `bankcore.cache.hit_rate` : taux de cache
- `bankcore.queue.depth` : messages en attente

### 2. Logs (Logs)
Enregistrements textuels d'événements.
- Structurés (JSON) plutôt que texte libre
- Corrélés par `trace_id` pour suivre une requête

### 3. Traces (Traces)
Chemin complet d'une requête à travers les services.

```
Trace: trace_id=abc123  duration=234ms
  └── Span: TransactionService.transfer  [0ms → 234ms]
       ├── Span: AccountService.GET /accounts/alice  [2ms → 45ms]
       ├── Span: AccountService.GET /accounts/bob    [47ms → 89ms]
       ├── Span: AccountService.PATCH /balance       [90ms → 180ms]
       └── Span: MessageBus.publish                  [181ms → 234ms]
```

---

## Architecture du monitoring BankCore

```
Use Cases (TransferUseCase, DepositUseCase, WithdrawUseCase)
                                       │
                                       ▼ counter().inc() / histogram().observe()
                               MetricsRegistry (Singleton, J01)
                                       │
ServiceClient._call() ──── span ────> Tracer (une instance par client)
                                       │
RepositoryHealthCheck, CacheHealthCheck,
MessageBusHealthCheck, MetricsHealthCheck ──> HealthChecker (composite)
```

Ce sont les trois classes réellement livrées : `MetricsRegistry`, `Tracer`,
`HealthChecker`. Il n'existe pas de tableau de bord centralisé qui les
agrège (pas de `MonitoringDashboard`) — chacune s'interroge séparément
(`metrics.snapshot()`, `tracer.recent_traces()`, `health_checker.check()`).

---

## Trace Context Propagation — ce qui est réel, ce qui ne l'est pas

**Réel :** chaque `ServiceClient` trace automatiquement ses propres appels
— `client.tracer.recent_traces()` montre chaque `GET`/`POST` émis par CE
client, avec méthode, chemin, statut et latence (voir `_call()` dans
`service_client.py`).

**Pas implémenté :** la propagation du contexte *entre* processus.
`ServiceRequest.headers` existe mais rien n'y écrit `X-Trace-ID`/`X-Span-ID`,
et le serveur HTTP réel (`docker/account-service/server.py`) ne les lit
jamais pour rattacher son propre traitement au trace de l'appelant. En
l'état, un `Trace` reste local au processus qui l'a créé — reconstituer
l'arbre complet `TransactionService → AccountService` à travers le réseau
demanderait que chaque service ait aussi son propre `Tracer` et lise ces
en-têtes, ce qui n'a pas été construit.

---

## Métriques clés BankCore

| Métrique | Type | Description |
|----------|------|-------------|
| `transfers_total` | Counter | Nombre total de virements |
| `transfers_failed_total` | Counter | Virements échoués |
| `transfer_latency_ms` | Histogram | Distribution des latences |
| `cache_hits_total` | Counter | Hits du cache |
| `cache_misses_total` | Counter | Misses du cache |
| `queue_messages_published` | Counter | Messages publiés |
| `queue_dlq_depth` | Gauge | Profondeur Dead Letter Queue |
| `active_accounts` | Gauge | Comptes actifs |

---

## Health Check étendu

`/health` reste un stub `{"status": "ok"}` volontairement bête : c'est la
sonde de *liveness* (le process tourne-t-il ?), et une liveness probe qui
vérifie des dépendances redémarre le container à chaque ralentissement de
la base — l'anti-pattern que `health_check.py` documente lui-même.
`/ready` (readiness) est le bon endroit pour un vrai check, et c'est là
qu'`AccountService` branche `HealthChecker` :

```json
GET /ready   (HTTP 200 — HTTP 503 si "status" != "healthy")
{
  "service": "account-service",
  "status": "healthy",
  "uptime_s": 3600.0,
  "checked_at": "...",
  "checks": {
    "database": {"status": "ok", "latency_ms": 1.2,
                  "message": "Repository accessible. 42 accounts."}
  }
}
```

`CacheHealthCheck` et `MessageBusHealthCheck` existent et sont testés
(`test_monitoring.py`), mais ne sont branchés nulle part : ni le cache ni
le message bus ne sont réellement utilisés par les microservices Docker
(voir J17/J18 — `InMemoryCache`/`MessageBus` tournent en mémoire dans le
process qui les instancie, pas partagés entre `account-service` et
`transaction-service`). Les câbler exigerait d'abord de câbler le cache et
le bus eux-mêmes dans ces services, ce qui est hors périmètre de J20.

---

## Complexité aujourd'hui

- 3 fichiers : `monitoring/tracer.py`, `monitoring/metrics.py`,
  `monitoring/health_check.py`
- Intégration dans ServiceClient (auto-trace des appels)
- Tests : `test_monitoring.py`
- 723 tests existants : **tous verts**
