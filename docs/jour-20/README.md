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
AccountService    ─── metrics ──> MetricsCollector
TransactionService ─── traces ──> Tracer
MessageBus        ─── events ──> EventMonitor
                                       │
                                       ▼
                               MonitoringDashboard
                               (summary, alerts, health)
```

---

## Trace Context Propagation

Quand TransactionService appelle AccountService,
il passe un `trace_id` dans le header HTTP :
```
X-Trace-ID: abc123
X-Span-ID:  def456
```
AccountService crée un span enfant avec ces IDs.
On peut ainsi reconstituer l'arbre complet d'une requête.

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

```json
GET /health
{
  "status": "healthy",
  "uptime_seconds": 3600,
  "checks": {
    "database":    {"status": "ok", "latency_ms": 1.2},
    "cache":       {"status": "ok", "hit_rate": 0.73},
    "message_bus": {"status": "ok", "dlq_depth": 0}
  },
  "metrics": {
    "requests_total": 15234,
    "error_rate": 0.002
  }
}
```

---

## Complexité aujourd'hui

- 3 fichiers : `monitoring/tracer.py`, `monitoring/metrics.py`,
  `monitoring/health_check.py`
- Intégration dans ServiceClient (auto-trace des appels)
- Tests : `test_monitoring.py`
- 723 tests existants : **tous verts**
