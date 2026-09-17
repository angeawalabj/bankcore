# Jour 30 — Diagramme C4 & Rétrospective Finale

---

## Diagramme C4 — Niveau 1 : Contexte Système

```mermaid
C4Context
    title BankCore — Contexte Système

    Person(customer, "Client Bancaire", "Consulte ses comptes,\nfait des virements")
    Person(teller, "Guichetier (Teller)", "Dépose/retire de l'argent\npour les clients")
    Person(manager, "Manager", "Virements, rapports,\nfermeture de comptes")
    Person(admin, "Administrateur", "Création de comptes,\ngestion des utilisateurs")

    System(bankcore, "BankCore", "Système bancaire:\ngestion des comptes,\ntransactions, audit")

    System_Ext(fx_service, "FxService", "Taux de change\n(virements internationaux)")
    System_Ext(notification, "NotificationService", "SMS / Email")
    System_Ext(compliance, "Compliance Archive", "Archivage légal\naudit log externe")

    Rel(customer, bankcore, "Consulte balance,\nhistorique")
    Rel(teller, bankcore, "Dépôt / retrait")
    Rel(manager, bankcore, "Virement, rapport")
    Rel(admin, bankcore, "Gestion comptes")
    Rel(bankcore, fx_service, "Conversion devise")
    Rel(bankcore, notification, "Alertes SMS/email")
    Rel(bankcore, compliance, "Export audit log")
```

---

## Diagramme C4 — Niveau 2 : Conteneurs

```mermaid
C4Container
    title BankCore — Conteneurs

    Person(user, "Utilisateur", "Teller / Manager / Admin")

    Container(account_svc, "AccountService", "Python 3.12\nDocker :8001", "Gestion des comptes:\ncréation, solde, profil")
    Container(tx_svc, "TransactionService", "Python 3.12\nDocker :8002", "Traitement des transactions:\ndépôt, retrait, virement")
    Container(redis, "Cache (Redis)", "Redis 7\nDocker :6379", "Référence uniquement (ADR-001)\nnon connecté — InMemoryCache tient ce rôle")
    Container(rabbit, "Message Queue (RabbitMQ)", "RabbitMQ 3\nDocker :5672", "Référence uniquement (ADR-001)\nnon connecté — MessageBus tient ce rôle")

    ContainerDb(account_db, "AccountDB", "SQLite", "Comptes, propriétaires,\nhistorique transactions")
    ContainerDb(tx_log, "TransactionLog", "In-Memory\n(SQLite en prod)", "Journal des transactions\npar service")
    ContainerDb(audit_db, "AuditLog", "Append-only\nHMAC-SHA256", "Audit trail immuable\nchaîné cryptographiquement")

    Rel(user, account_svc, "HTTP REST :8001")
    Rel(user, tx_svc, "HTTP REST :8002")
    Rel(tx_svc, account_svc, "HTTP GET/PATCH\n(ServiceClient + CircuitBreaker, auto-tracé)")
    Rel(account_svc, account_db, "SQLite")
    Rel(tx_svc, tx_log, "Append-only")
```

---

## Diagramme C4 — Niveau 3 : Composants (AccountService)

```mermaid
C4Component
    title AccountService — Composants internes

    Component(api_handler, "BankAPIHandler", "Presentation Layer\n(J15 Hexagonal)", "Adapte HTTP → Commands\nPrimary Adapter")
    Component(app_svc, "BankApplicationService", "Application Layer\n(J11 Layered)", "Facade sur les Use Cases")
    Component(use_cases, "Use Cases", "Application Layer\n(J11)", "CreateAccount\nDeposit, Withdraw\nApplyInterest")
    Component(rbac, "SecuredBankAppService", "Application Layer\n(J27 RBAC)", "Vérifie permissions\navant chaque opération")
    Component(domain, "Account Aggregate", "Domain Layer\n(J21 Event Sourcing)", "Règles métier pures\nÉtat = projection d'events")
    Component(repo, "SQLiteAccountRepository", "Infrastructure\n(J13 + J14)", "Implémente AccountRepositoryPort\nSchéma 5 tables, 6 index")
    Component(audit, "ImmutableAuditLog", "Infrastructure\n(J26)", "HMAC-SHA256\nChaîné, append-only")
    Component(secrets, "SecretsProvider", "Infrastructure\n(J28)", "Clé HMAC hors du code\nEnvVar / Rotating")

    Rel(api_handler, rbac, "Command + Principal")
    Rel(rbac, app_svc, "Autorisé → délègue")
    Rel(app_svc, use_cases, "Orchestre")
    Rel(use_cases, domain, "Commands → Events")
    Rel(use_cases, repo, "AccountRepositoryPort")
    Rel(use_cases, audit, "Log chaque opération")
    Rel(audit, secrets, "Clé HMAC")
```

---

## Rétrospective Finale

### Ce que BankCore a construit

```
Semaine 1  J01-J05   Design Patterns GoF         155 tests
Semaine 2  J06-J10   Principes SOLID              183 tests
Semaine 3  J11-J15   Architectures                190 tests
Semaine 4  J16-J20   Scalabilité & Production     254 tests
Semaine 5  J21-J28   Patterns Avancés             268 tests
J29-J30    ADR + C4  Documentation d'architecte   —
──────────────────────────────────────────────────────────
Total                                             1050+ tests
```

---

### Ce qui ne passerait PAS en production tel quel

**1. SQLite → PostgreSQL obligatoire**
SQLite est mono-thread en écriture. Sous charge concurrente,
les virements se bloqueraient mutuellement. Le schéma (J13) est conçu
pour PostgreSQL — la migration est une ligne dans le Container.

**2. InMemoryCache → Redis réel**
`InMemoryCache` ne survit pas aux redémarrages et n'est pas partagé
entre plusieurs instances. L'interface `CachingServiceClient` est
identique avec un `RedisCache` — c'est le point.

**3. InProcessMessageBus → RabbitMQ réel**
Le `MessageBus` J18 est synchrone et in-process. En production :
`TransactionService` publie sur RabbitMQ, `FraudDetector` consomme
dans un process séparé. L'interface `Consumer` est identique.

**4. `_interest_rate` non persisté (ADR-009)**
La dette technique documentée : le taux d'intérêt doit être un événement
de domaine explicite (`InterestRateSet`) pour survivre aux reconstructions
d'agrégat depuis l'EventStore.

**5. SecretProvider → HashiCorp Vault ou AWS Secrets Manager**
`EnvSecretsProvider` est production-safe pour un démarrage simple,
mais une rotation de clé HMAC en production nécessite Vault ou équivalent.

**6. Observabilité : pas de scraping, pas de propagation inter-process**
`MetricsRegistry`/`Tracer`/`HealthChecker` (J20) sont réels mais internes
à chaque process : rien n'expose `/metrics` en HTTP (pas de scraping
Prometheus possible tel quel), et un `Trace` ne franchit pas la frontière
réseau entre `account-service` et `transaction-service` — chaque
`ServiceClient` ne voit que ses propres appels, pas l'arbre complet
d'une requête. Voir docs/jour-20 pour le détail de ce qui est câblé et
de ce qui ne l'est pas.

---

### Ce qui EST production-ready

**Architecture :** Clean Architecture + Hexagonale + CQRS + Event Sourcing.
Ces patterns sont indépendants de l'implémentation. Changer SQLite pour
PostgreSQL ne touche pas un seul Use Case.

**Tests :** 1050+ tests, 0 test fragile, 0 mock global, 0 patching de Singleton.
Chaque test est isolé par injection de dépendances (J10 DIP).

**Résilience :** Circuit Breaker + Bulkhead + Retry.
Un service lent ne bloque pas les autres. Les pannes transitoires
se récupèrent automatiquement.

**Sécurité :** RBAC + Audit Log immuable + Secrets séparés.
Chaque opération est autorisée, tracée, et non-répudiable.

**Observabilité :** `MetricsRegistry` compte réellement chaque virement/
dépôt/retrait (branché dans les Use Cases), `ServiceClient` trace
réellement chaque appel inter-service, `HealthChecker` vérifie réellement
la base d'AccountService sur `/ready`. Ce qui manque pour une vraie prod :
un point 6 ci-dessous.

---

### La vraie leçon architecturale

```
J01 : ConfigManager — 80 lignes, simple, suffisant
J30 : 55+ fichiers, 1050+ tests, patterns de niveau enterprise

La différence n'est pas la complexité initiale.
C'est la présence de règles dès le début.
```

**SRP J06** : sans cette règle, `Account` aurait absorbé
`TransactionHistory`, `FeeCalculator`, `EventBuilder`...
et `transfer()` ferait 200 lignes.

**DIP J10** : sans cette règle, aucun test ne serait isolable.
Chaque test aurait besoin de l'AlertSystem réel, du ConfigManager réel,
de la BDD réelle. Les tests prendraient 10 minutes au lieu de 10 secondes.

**ADR J29** : sans documentation des décisions, le `id(consumer)` du J18
serait "corrigé" par le prochain développeur en `consumer.name` —
recréant silencieusement le bug de collision.

---

### À un futur lecteur de ce code

Ce projet répond à une question que tout développeur se pose :

> "Pourquoi est-ce qu'on passe autant de temps à l'architecture
> alors qu'on pourrait juste coder ?"

La réponse est dans la progression J01 → J30.

Le code du J01 est simple parce que le problème est simple.
Le code du J30 est structuré parce que le problème a grandi.

La structure n'a pas été imposée dès le J01 — elle a émergé des règles.
Les règles ont été définies avant d'en avoir besoin — c'est le travail de l'architecte.

**Un architecte n'est pas un développeur qui code plus vite.
C'est quelqu'un qui crée les conditions pour que le code reste
maintenable quand la complexité arrive.**

Et la complexité arrive toujours.
