# Jour 19 — Dockerisation

## Le principe

> "Build once, run anywhere."

Un container Docker encapsule le code, ses dépendances, et sa configuration
dans une unité déployable reproductible. L'environnement du container est
identique sur le laptop du développeur, le serveur CI, et la production.

---

## Ce qu'on containerise

```
bankcore/
├── docker/
│   ├── account-service/
│   │   ├── Dockerfile
│   │   └── entrypoint.sh
│   ├── transaction-service/
│   │   ├── Dockerfile
│   │   └── entrypoint.sh
│   └── docker-compose.yml
```

**AccountService** → Port 8001
**TransactionService** → Port 8002
**Redis** → Port 6379 (exemple de topologie — l'app ne s'y connecte pas, voir J17)
**RabbitMQ** → Port 5672 (exemple de topologie — l'app ne s'y connecte pas, voir J18)

---

## Architecture des containers

```
┌─────────────────────────────────────────────┐
│              Docker Network: bankcore        │
│                                             │
│  ┌──────────────┐    ┌───────────────────┐  │
│  │ account-svc  │    │ transaction-svc   │  │
│  │ :8001        │◄───│ :8002             │  │
│  └──────────────┘    └───────────────────┘  │
│          │                    │              │
│  ┌───────┴──────┐   ┌────────┴──────────┐   │
│  │    redis     │   │     rabbitmq      │   │
│  │    :6379     │   │     :5672         │   │
│  └──────────────┘   └───────────────────┘   │
└─────────────────────────────────────────────┘
```

---

## Décisions de containerisation

### 1. Images légères (python:3.12-slim)
Pas `python:3.12` (930MB). `python:3.12-slim` = 150MB.
En production : `python:3.12-alpine` = 55MB mais incompatibilités possibles.

### 2. Non-root user
```dockerfile
RUN adduser --disabled-password --gecos '' bankcore
USER bankcore
```
Principe de moindre privilège : si le container est compromis,
l'attaquant n'a pas root sur le host.

### 3. Health checks
```dockerfile
HEALTHCHECK --interval=10s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/health')"
```
Docker Compose attend que AccountService soit `healthy`
avant de démarrer TransactionService.

### 4. Variables d'environnement pour la config
```dockerfile
ENV BANKCORE_DATABASE_URL=sqlite:///data/bankcore.db
ENV BANKCORE_ENVIRONMENT=production
```
ConfigManager (J01) lit ces variables — zero code change requis.

### 5. Volumes pour la persistance
```yaml
volumes:
  - account-data:/app/data   # SQLite database persiste entre restarts
```

---

## docker-compose.yml — orchestration locale

```yaml
version: '3.9'
services:
  account-service:
    build: ./docker/account-service
    ports: ["8001:8001"]
    healthcheck: ...

  transaction-service:
    build: ./docker/transaction-service
    ports: ["8002:8002"]
    depends_on:
      account-service:
        condition: service_healthy
    environment:
      ACCOUNT_SERVICE_URL: http://account-service:8001
```

La clé `depends_on` avec `condition: service_healthy` garantit
que TransactionService ne démarre qu'une fois AccountService prêt.

---

## Ce que J19 livre

Fichiers Docker prêts à l'emploi :
- `Dockerfile` pour chaque service (multi-stage build)
- `docker-compose.yml` complet avec health checks et volumes
- `entrypoint.sh` avec graceful shutdown (SIGTERM handling)
- `.dockerignore` pour exclure tests et docs des images
- `docker-compose.test.yml` pour les tests d'intégration en CI

---

## Connexion avec les jours précédents et suivants

- **J16 (Microservices)** : chaque service devient un container
- **J17 (Cache)** : le container `redis` illustre où un vrai cache
  externe s'insérerait ; l'app tourne avec `InMemoryCache` (ADR-001,
  pas de `redis-py`)
- **J18 (Message Queue)** : idem pour `rabbitmq` — `MessageBus`
  reste en mémoire, le broker n'est pas contacté
- **J20 (Monitoring)** : Prometheus + Grafana ajoutés au compose

---

## Complexité aujourd'hui

- Fichiers Docker : `Dockerfile` × 2, `docker-compose.yml`,
  `docker-compose.test.yml`, `.dockerignore` × 2, `entrypoint.sh` × 2
- Code Python : `health_check.py` endpoint pour chaque service
- Tests : `test_docker_config.py` — vérifie la validité des configs sans Docker
