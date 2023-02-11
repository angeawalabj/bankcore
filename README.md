# BankCore — Challenge Architecture 30 Jours

> **Un système bancaire Python construit progressivement sur 30 jours.**  
> Chaque jour introduit un pattern ou principe architectural réel.  
> Pas un tutoriel — un portfolio qui prouve une pensée d'architecte.

---

## Résultats finaux

| Métrique | Valeur |
|----------|--------|
| Fichiers source Python | 64 |
| Fichiers de tests | 28 |
| ADR (Architecture Decision Records) | 10 |
| Lignes de code source | 12 119 |
| Lignes de tests | 11 483 |
| **Total lignes** | **23 602** |
| **Tests passés** | **1 050 / 1 050** |
| Dépendances externes | `pytest`, `pyyaml` |
| Frameworks web | aucun (stdlib uniquement) |

---

## Les 30 jours

### Semaine 1 — Design Patterns GoF
| Jour | Pattern | Fichier clé |
|------|---------|-------------|
| J01 | **Singleton** | `config_manager.py` — double-checked locking |
| J02 | **Factory** | `account_factory.py` — registre dynamique |
| J03 | **Observer** | `alert_system.py` — 4 observateurs découplés |
| J04 | **Strategy** | `fee_calculator.py` — 5 stratégies interchangeables |
| J05 | **Decorator** | `transaction_decorators.py` — pipeline stackable |

### Semaine 2 — Principes SOLID
| Jour | Principe | Démonstration |
|------|----------|---------------|
| J06 | **SRP** | Extraction `TransactionHistory`, `AccountConfigResolver`, `EventBuilder` |
| J07 | **OCP** | `AccountTypeRegistry` — extension sans modification |
| J08 | **LSP** | `AccountContractVerifier` — 6 invariants prouvés |
| J09 | **ISP** | 8 interfaces ségrégées — `InterestBearing` résout un problème LSP |
| J10 | **DIP** | `ConfigProtocol`, `FakeConfig`, `SpyAlertSystem`, `BankContainer` |

### Semaine 3 — Architectures
| Jour | Architecture | Livrable |
|------|--------------|----------|
| J11 | **Layered** | Commands, Use Cases, `BankApplicationService` |
| J12 | **Clean** | `Money`, `AccountId`, Ports, Domain Events |
| J13 | **BDD** | Schéma SQLite 5 tables, 6 index, CHECK constraints |
| J14 | **Repository** | Specification Pattern, Pagination, Unit of Work |
| J15 | **Hexagonale** | `TestDriver`, `InterestScheduler`, `BankAPIHandler` |

### Semaine 4 — Scalabilité & Production
| Jour | Technologie | Livrable |
|------|-------------|----------|
| J16 | **Microservices** | `AccountService` + `TransactionMicroservice` |
| J17 | **Cache** | `CachingServiceClient` Decorator, TTL, invalidation |
| J18 | **Message Queue** | `MessageBus` Pub/Sub, DLQ, idempotency |
| J19 | **Docker** | Multi-stage build, healthchecks, `depends_on: healthy` |
| J20 | **Monitoring** | Counter/Gauge/Histogram, Distributed Tracing, Health Checks |

### Semaine 5 — Patterns Avancés
| Jour | Pattern | Livrable |
|------|---------|----------|
| J21 | **Event Sourcing** | `EventStore`, `AccountAggregate`, Projections |
| J22 | **CQRS** | Commands → EventStore, Queries → ReadModels |
| J23 | **Saga** | `SagaOrchestrator` avec compensation automatique |
| J24 | **Circuit Breaker** | `CircuitBreakerClient`, fail-fast, HALF-OPEN probe |
| J25 | **Bulkhead + Retry** | Semaphore isolation + backoff exponentiel + jitter |
| J26 | **Audit Log** | HMAC-SHA256 + chaînage cryptographique |
| J27 | **RBAC** | Teller / Manager / Admin + `@requires_permission` |
| J28 | **Secrets** | `SecretsProvider` Protocol + rotation versionnée |
| J29 | **ADR** | 10 Architecture Decision Records formels |
| J30 | **C4 + Rétro** | Diagrammes + rétrospective honnête |

---

## Lancer les tests

```bash
pip install pytest pyyaml
PYTHONPATH=src python -m pytest tests/ -v
```

---

## Lancer avec Docker

```bash
cd docker
docker-compose up --build
curl http://localhost:8001/health
curl http://localhost:8002/ready
```

---

## La leçon architecturale

Ce projet répond à une question que tout développeur se pose :

> "Pourquoi passe-t-on autant de temps sur l'architecture
> alors qu'on pourrait juste coder ?"

La réponse est dans la progression J01 → J30.

Le code du J01 est simple parce que le problème est simple.  
Le code du J30 est structuré parce que le problème a grandi.

La structure n'a pas été imposée dès J01 — elle a émergé des règles.  
Les règles ont été définies avant d'en avoir besoin.  
**C'est le travail de l'architecte.**

Un architecte ne code pas plus vite.  
Il crée les conditions pour que le code reste maintenable quand la complexité arrive.  
Et la complexité arrive toujours.

---

*BankCore — 30 jours · 1050 tests · 23 602 lignes · 0 réécriture complète*
