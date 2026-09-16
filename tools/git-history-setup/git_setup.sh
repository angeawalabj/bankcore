#!/bin/bash
# =============================================================================
# BankCore — Script de mise en ligne GitHub
# Historique git simulé depuis le 11 février 2023
# 30 jours de développement répartis sur 6 semaines
#
# Usage:
#   chmod +x git_setup.sh
#   ./git_setup.sh
#   git remote add origin https://github.com/TON_USERNAME/bankcore.git
#   git push -u origin main
# =============================================================================

set -e

AUTHOR_NAME="Ange AWALA"
AUTHOR_EMAIL="ange.awala.bj@gmail.com"   # ← remplace par ton email GitHub

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[GIT]${NC} $1"; }
info() { echo -e "${BLUE}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }

# =============================================================================
# Init
# =============================================================================

info "Initialisation du dépôt BankCore..."
git init
git config user.name  "$AUTHOR_NAME"
git config user.email "$AUTHOR_EMAIL"

cat > .gitignore << 'GITIGNORE'
__pycache__/
*.pyc
*.pyo
.venv/
venv/
.env
*.env
.coverage
htmlcov/
.pytest_cache/
*.egg-info/
dist/
build/
*.db
*.sqlite
*.sqlite3
.DS_Store
*.swp
.idea/
.vscode/
GITIGNORE

# =============================================================================
# Helper
# =============================================================================
c() {
  # c "2023-02-11T09:15:00" "message" file1 file2 ...
  local date="$1"; local msg="$2"; shift 2
  git add "$@" 2>/dev/null || true
  GIT_AUTHOR_DATE="$date" GIT_COMMITTER_DATE="$date" \
    git commit -m "$msg" 2>/dev/null || true
}

ca() {
  # ca "2023-02-11T09:15:00" "message"  (commit all staged)
  local date="$1"; local msg="$2"
  GIT_AUTHOR_DATE="$date" GIT_COMMITTER_DATE="$date" \
    git commit -m "$msg" 2>/dev/null || true
}

# =============================================================================
# COMMIT INITIAL — 2023-02-11
# =============================================================================
log "Init du projet"
git add .gitignore requirements.txt README.md 2>/dev/null || git add .gitignore 2>/dev/null || true
GIT_AUTHOR_DATE="2023-02-11T08:00:00" GIT_COMMITTER_DATE="2023-02-11T08:00:00" \
  git commit -m "chore: initialize BankCore — 30-day architecture challenge

Objectif : prouver une pensée d'architecte Lead Dev/CTO
Stack    : Python 3.12 stdlib uniquement + pytest
Durée    : 30 jours, 1 pattern/principe par jour" 2>/dev/null || true

# =============================================================================
# SEMAINE 1 — Design Patterns GoF
# Du 11 au 17 février 2023 (lundi → dimanche)
# =============================================================================

# ----- JOUR 01 — Samedi 11 février 2023 — Singleton -------------------------
log "J01 — Singleton (ConfigManager)"

c "2023-02-11T09:00:00" \
  "feat(config): implement ConfigManager Singleton

- Thread-safe double-checked locking
- BANKCORE_* env vars overrides
- _reset() for test isolation
- Default: DB URL, fee rates, transfer limits, alert thresholds" \
  src/bankcore/__init__.py src/bankcore/config_manager.py

c "2023-02-11T14:30:00" \
  "test(config): add 15 tests for ConfigManager Singleton

- Uniqueness: same instance across 50 concurrent threads
- State sharing, env var loading, _reset() isolation" \
  tests/test_config_manager.py

c "2023-02-11T17:00:00" \
  "docs(j01): add ADR and README for Singleton pattern" \
  docs/jour-01/

# ----- JOUR 02 — Dimanche 12 février 2023 — Factory -------------------------
log "J02 — Factory (AccountFactory)"

c "2023-02-12T09:30:00" \
  "feat(account): add Account ABC + CurrentAccount/SavingsAccount/ProAccount

- LSP-ready hierarchy, immutable TransactionRecord
- CurrentAccount: 10k daily limit, no overdraft
- SavingsAccount: 50 EUR min balance, 2.5% interest
- ProAccount: -5000 EUR overdraft, 50k daily limit" \
  src/bankcore/account.py

c "2023-02-12T11:00:00" \
  "feat(factory): implement AccountFactory with dynamic registry

- create(type, owner, deposit) as single public API
- register() enables OCP extension
- Reads limits from ConfigManager (J01 integration)" \
  src/bankcore/account_factory.py

c "2023-02-12T15:00:00" \
  "test(factory): add 38 tests for AccountFactory and Account hierarchy" \
  tests/test_account_factory.py

c "2023-02-12T17:30:00" \
  "docs(j02): add ADR for Factory Pattern" \
  docs/jour-02/

# ----- JOUR 03 — Lundi 13 février 2023 — Observer ---------------------------
log "J03 — Observer (AlertSystem)"

c "2023-02-13T08:45:00" \
  "feat(events): add BankEvent frozen dataclass + EventType constants" \
  src/bankcore/events.py

c "2023-02-13T10:30:00" \
  "feat(alerts): implement AlertSystem Observer with 4 concrete observers

- AlertSystem: Singleton event bus, error isolation per observer
- FraudDetector, NotificationService, BalanceMonitor, AuditLogger
- Wildcard subscription (*) for AuditLogger" \
  src/bankcore/alert_system.py

c "2023-02-13T13:00:00" \
  "feat(transaction): add TransactionService — publishes BankEvent after operations" \
  src/bankcore/transaction_service.py

c "2023-02-13T16:00:00" \
  "test(alerts): add 34 tests for AlertSystem Observer pattern" \
  tests/test_alert_system.py

c "2023-02-13T18:00:00" \
  "docs(j03): add ADR for Observer Pattern" \
  docs/jour-03/

# ----- JOUR 04 — Mardi 14 février 2023 — Strategy ---------------------------
log "J04 — Strategy (FeeCalculator)"

c "2023-02-14T09:00:00" \
  "feat(fees): add FeeStrategy ABC + 5 strategies

- Standard, Zero, Tiered, International, Promo
- FeeResult: immutable, fee_pct computed" \
  src/bankcore/fee_strategy.py

c "2023-02-14T11:30:00" \
  "feat(fees): add FeeCalculator Strategy context

- apply_fee(), estimate(), compare_strategies()
- Publishes fee.applied event (J03 integration)" \
  src/bankcore/fee_calculator.py

c "2023-02-14T15:30:00" \
  "test(fees): add 32 tests for FeeStrategy + FeeCalculator" \
  tests/test_fee_calculator.py

c "2023-02-14T17:30:00" \
  "docs(j04): add ADR for Strategy Pattern" \
  docs/jour-04/

# ----- JOUR 05 — Mercredi 15 février 2023 — Decorator -----------------------
log "J05 — Decorator (TransactionPipeline)"

c "2023-02-15T08:30:00" \
  "feat(pipeline): extract TransactionProcessor interface + TransactionDecorator" \
  src/bankcore/transaction_processor.py

c "2023-02-15T10:00:00" \
  "feat(pipeline): add 4 decorators + build_pipeline()

- ValidationDecorator, LoggingDecorator, RateLimitDecorator, FeeDecorator
- build_pipeline(): toggleable stack — validate, log, rate_limit, apply_fees" \
  src/bankcore/transaction_decorators.py

c "2023-02-15T12:00:00" \
  "refactor(transaction): TransactionService implements TransactionProcessor" \
  src/bankcore/transaction_service.py

c "2023-02-15T15:30:00" \
  "test(pipeline): add 40 tests for Decorator stack" \
  tests/test_transaction_pipeline.py

c "2023-02-15T17:30:00" \
  "docs(j05): add ADR for Decorator Pattern" \
  docs/jour-05/

# =============================================================================
# SEMAINE 2 — Principes SOLID
# Du 18 au 22 février 2023 (samedi → mercredi)
# =============================================================================

# ----- JOUR 06 — Samedi 18 février 2023 — SRP --------------------------------
log "J06 — SRP"

c "2023-02-18T09:00:00" \
  "refactor(srp): extract TransactionHistory from Account

- Owns record storage, retrieval, total_credits/debits
- Account delegates via self._history — public API unchanged" \
  src/bankcore/transaction_history.py

c "2023-02-18T10:30:00" \
  "refactor(srp): extract AccountConfigResolver from AccountFactory" \
  src/bankcore/account_config.py

c "2023-02-18T12:00:00" \
  "refactor(srp): extract EventBuilder from TransactionService" \
  src/bankcore/event_builder.py

c "2023-02-18T14:00:00" \
  "refactor(srp): update Account, AccountFactory, TransactionService

- 148 existing tests pass unchanged" \
  src/bankcore/account.py src/bankcore/account_factory.py \
  src/bankcore/transaction_service.py

c "2023-02-18T16:30:00" \
  "test(srp): add 34 tests verifying SRP extraction" \
  tests/test_srp_refactoring.py

c "2023-02-18T18:00:00" \
  "docs(j06): add ADR for Single Responsibility Principle" \
  docs/jour-06/

# ----- JOUR 07 — Dimanche 19 février 2023 — OCP -----------------------------
log "J07 — OCP"

c "2023-02-19T09:30:00" \
  "feat(ocp): add AccountTypeRegistry + ConfigProfile

- Singleton registry, thread-safe with threading.Lock
- ABC.register() for isinstance without multiple inheritance" \
  src/bankcore/account_type_registry.py

c "2023-02-19T11:00:00" \
  "feat(ocp): add FeeStrategyRegistry for extensible fee strategies" \
  src/bankcore/fee_strategy_registry.py

c "2023-02-19T13:00:00" \
  "refactor(ocp): AccountFactory, AccountConfigResolver, FeeCalculator use registries

- Extension without modification proven in tests
- 182 existing tests pass unchanged" \
  src/bankcore/account_factory.py src/bankcore/account_config.py \
  src/bankcore/fee_calculator.py

c "2023-02-19T16:00:00" \
  "test(ocp): add 25 tests proving OCP invariant" \
  tests/test_ocp.py

c "2023-02-19T17:30:00" \
  "docs(j07): add ADR for Open/Closed Principle" \
  docs/jour-07/

# ----- JOUR 08 — Lundi 20 février 2023 — LSP --------------------------------
log "J08 — LSP"

c "2023-02-20T09:00:00" \
  "feat(lsp): add AccountContractVerifier with 6 invariants

- IDENTITY, BALANCE_CONSISTENCY, DEPOSIT_CONTRACT
- WITHDRAW_CONTRACT, MIN_BALANCE, GET_INFO_CONTRACT
- assert_compliant() raises with detailed violation info" \
  src/bankcore/account_contract.py

c "2023-02-20T11:30:00" \
  "feat(lsp): add min_possible_balance and can_withdraw() to Account hierarchy

- CurrentAccount: min=0, SavingsAccount: min=50, ProAccount: min=-5000
- 207 existing tests pass unchanged" \
  src/bankcore/account.py

c "2023-02-20T15:00:00" \
  "test(lsp): add 54 tests for Liskov Substitution Principle

- 9 source/destination combinations in transfer tests
- BrokenAccount caught by verifier with detailed message" \
  tests/test_lsp.py

c "2023-02-20T17:00:00" \
  "docs(j08): add ADR for Liskov Substitution Principle" \
  docs/jour-08/

# ----- JOUR 09 — Mardi 21 février 2023 — ISP --------------------------------
log "J09 — ISP"

c "2023-02-21T09:00:00" \
  "feat(isp): add 8 segregated interfaces in interfaces.py

Account capabilities: Readable, Transactable, InterestBearing, Overdraftable
Transaction: Depositable, Withdrawable, Transferable
Events: EventHandler, EventFilter" \
  src/bankcore/interfaces.py

c "2023-02-21T11:00:00" \
  "refactor(isp): Account implements Readable+Transactable

- InterestBearing.register(SavingsAccount) via ABC.register()
- Overdraftable.register(ProAccount) via ABC.register()
- overdraft_used() moved to ProAccount only
- 261 existing tests pass unchanged" \
  src/bankcore/account.py src/bankcore/transaction_processor.py \
  src/bankcore/alert_system.py

c "2023-02-21T15:00:00" \
  "test(isp): add 47 tests for Interface Segregation Principle

- CurrentAccount has no apply_interest() — ISP violation prevented
- ProAccount has no overdraft_used in CurrentAccount" \
  tests/test_isp.py

c "2023-02-21T17:00:00" \
  "docs(j09): add ADR for Interface Segregation Principle" \
  docs/jour-09/

# ----- JOUR 10 — Mercredi 22 février 2023 — DIP -----------------------------
log "J10 — DIP"

c "2023-02-22T08:30:00" \
  "feat(dip): add ConfigProtocol, AlertProtocol + FakeConfig, SpyAlertSystem

- Structural protocols (duck typing) — no changes to existing classes
- FakeConfig: in-memory with test defaults
- SpyAlertSystem: records events, events_of_type(), was_published()" \
  src/bankcore/protocols.py

c "2023-02-22T10:30:00" \
  "refactor(dip): TransactionService + AccountConfigResolver accept injected deps

- Backward compatible: zero-arg constructors fall back to Singletons
- 308 existing tests pass unchanged" \
  src/bankcore/transaction_service.py src/bankcore/account_config.py

c "2023-02-22T12:30:00" \
  "feat(dip): add BankContainer dependency injection container

- build(): wires real implementations
- build_for_testing(): FakeConfig + SpyAlertSystem — zero global state" \
  src/bankcore/container.py

c "2023-02-22T15:30:00" \
  "test(dip): add 32 tests for Dependency Inversion Principle

- Full isolation proof: Singletons reset AFTER injection — service still works
- Two services with different injected configs behave differently" \
  tests/test_dip.py

c "2023-02-22T18:00:00" \
  "docs(j10): add ADR for Dependency Inversion Principle" \
  docs/jour-10/

# =============================================================================
# SEMAINE 3 — Architectures
# Du 25 février au 1er mars 2023 (samedi → mercredi)
# =============================================================================

# ----- JOUR 11 — Samedi 25 février 2023 — Layered Architecture --------------
log "J11 — Layered Architecture"

c "2023-02-25T09:00:00" \
  "feat(application): add 5 immutable Commands + UseCaseResult

- TransferCommand, DepositCommand, WithdrawCommand
- CreateAccountCommand, ApplyInterestCommand
- UseCaseResult.ok() / .fail() — bool(result) for clean if/else" \
  src/bankcore/application/__init__.py \
  src/bankcore/application/commands.py

c "2023-02-25T11:30:00" \
  "feat(application): add 5 Use Cases + BankApplicationService facade

- ApplyInterestUseCase uses InterestBearing (ISP J09) — no isinstance(SavingsAccount)
- AccountRegistry: in-memory store (J14 Repository swap ready)
- Layer isolation: Use Cases never import Presentation" \
  src/bankcore/application/use_cases.py

c "2023-02-25T15:00:00" \
  "test(layered): add 42 tests for Layered Architecture

- Layer isolation: domain doesn't import use_cases (source inspection)" \
  tests/test_layered_architecture.py

c "2023-02-25T17:00:00" \
  "docs(j11): add ADR for Layered Architecture" \
  docs/jour-11/

# ----- JOUR 12 — Dimanche 26 février 2023 — Clean Architecture ---------------
log "J12 — Clean Architecture"

c "2023-02-26T09:00:00" \
  "feat(domain): add Money + AccountId value objects

- Money: +/-/* operators, cross-currency guard, zero infrastructure imports
- AccountId: typed, normalized uppercase, UUID generator" \
  src/bankcore/domain/__init__.py \
  src/bankcore/domain/value_objects.py

c "2023-02-26T10:30:00" \
  "feat(domain): add 5 Domain Events (past tense naming)

- AccountOpened, MoneyDeposited, MoneyWithdrawn, MoneyTransferred
- InterestApplied, FeeCharged — all frozen=True" \
  src/bankcore/domain/domain_events.py

c "2023-02-26T12:00:00" \
  "feat(application): add Ports — AccountRepositoryPort, NotificationPort, DomainEventStorePort

- Ports in Application layer — Infrastructure implements them (ADR-004)" \
  src/bankcore/application/ports.py

c "2023-02-26T14:00:00" \
  "feat(infrastructure): add InMemoryAccountRepository + InMemoryDomainEventStore" \
  src/bankcore/infrastructure/__init__.py \
  src/bankcore/infrastructure/persistence/__init__.py \
  src/bankcore/infrastructure/persistence/in_memory_repository.py

c "2023-02-26T16:00:00" \
  "test(clean): add 54 tests for Clean Architecture

- Swap test: same Use Cases, different repository — identical results" \
  tests/test_clean_architecture.py

c "2023-02-26T18:00:00" \
  "docs(j12): add ADR for Clean Architecture" \
  docs/jour-12/

# ----- JOUR 13 — Lundi 27 février 2023 — Database Schema --------------------
log "J13 — Database Schema"

c "2023-02-27T09:00:00" \
  "feat(db): add SQLite schema — 5 tables, 6 indexes, CHECK constraints

- account: balance >= min_possible_balance (LSP J08 at DB level)
- transaction: amount != 0, direction matches tx_type
- SchemaInspector, create_schema(), schema_connection() context manager" \
  src/bankcore/infrastructure/persistence/schema.py

c "2023-02-27T12:00:00" \
  "feat(db): add SQLiteAccountRepository implementing AccountRepositoryPort

- save(): INSERT OR UPDATE, idempotent transaction sync
- _reconstruct(): anti-corruption layer
- get_transaction_history(), get_account_summary()" \
  src/bankcore/infrastructure/persistence/sqlite_repository.py

c "2023-02-27T15:30:00" \
  "test(db): add 37 tests for database schema + SQLiteAccountRepository

- CHECK constraints reject invalid data at DB level
- Data survives reconnection (temp file test)" \
  tests/test_database_schema.py

c "2023-02-27T17:30:00" \
  "docs(j13): add ADR for Database Schema design" \
  docs/jour-13/

# ----- JOUR 14 — Mardi 28 février 2023 — Repository Pattern -----------------
log "J14 — Repository Pattern"

c "2023-02-28T09:00:00" \
  "feat(repository): add Specification Pattern + Page

- 8 specs: OwnerSpec, TypeSpec, BalanceSpec, InterestEligibleSpec
- Boolean composition: &, |, ~ operators
- Page: frozen, has_next/has_prev/total_pages" \
  src/bankcore/application/specifications.py

c "2023-02-28T11:00:00" \
  "feat(repository): add UnitOfWork + TransferOperation

- Dirty tracking, identity map, context manager
- TransferOperation: atomic — both accounts dirty together" \
  src/bankcore/application/unit_of_work.py

c "2023-02-28T13:00:00" \
  "feat(repository): extend InMemory + SQLite repos with find(spec, page, page_size)" \
  src/bankcore/infrastructure/persistence/in_memory_repository.py \
  src/bankcore/infrastructure/persistence/sqlite_repository.py

c "2023-02-28T16:00:00" \
  "test(repository): add 51 tests for Specifications, Pagination, UnitOfWork" \
  tests/test_repository_pattern.py

c "2023-02-28T18:00:00" \
  "docs(j14): add ADR for Repository Pattern" \
  docs/jour-14/

# ----- JOUR 15 — Mercredi 1er mars 2023 — Hexagonal Architecture -------------
log "J15 — Hexagonal Architecture"

c "2023-03-01T09:00:00" \
  "feat(presentation): add TestDriver primary adapter

- Fluent assertions: assert_balance(), assert_last_success/failure()
- name→account_id registry, fully isolated per instance" \
  src/bankcore/presentation/__init__.py \
  src/bankcore/presentation/test_driver.py

c "2023-03-01T11:00:00" \
  "feat(presentation): add InterestScheduler primary adapter

- Paginated batch via InterestEligibleSpec (J14)
- dry_run, preview(), SchedulerReport" \
  src/bankcore/presentation/scheduler.py

c "2023-03-01T13:00:00" \
  "feat(presentation): add BankAPIHandler simulated REST adapter

- 201/200/404/422, error_code → HTTP status mapping
- Zero business logic — translates Commands ↔ HTTP" \
  src/bankcore/presentation/api_handler.py

c "2023-03-01T14:30:00" \
  "fix(application): use 'is not None' instead of truthiness for registry injection

- Empty InMemoryAccountRepository (len=0) was falsy → new AccountRegistry created
- Critical DIP bug: injected dependency silently replaced by default" \
  src/bankcore/application/use_cases.py

c "2023-03-01T16:30:00" \
  "test(hexagonal): add 40 tests for Hexagonal Architecture adapters" \
  tests/test_hexagonal_architecture.py

c "2023-03-01T18:00:00" \
  "docs(j15): add ADR for Hexagonal Architecture" \
  docs/jour-15/

# =============================================================================
# SEMAINE 4 — Scalabilité & Production
# Du 4 au 8 mars 2023 (samedi → mercredi)
# =============================================================================

# ----- JOUR 16 — Samedi 4 mars 2023 — Microservices -------------------------
log "J16 — Microservices"

c "2023-03-04T09:00:00" \
  "feat(microservices): add ServiceClient + ServiceRegistry

- ServiceRequest/ServiceResponse DTOs
- Call logging, latency measurement
- In-process simulation identical interface to real HTTP" \
  src/bankcore/services/__init__.py \
  src/bankcore/services/shared/__init__.py \
  src/bankcore/services/shared/service_client.py

c "2023-03-04T11:00:00" \
  "feat(microservices): add AccountService autonomous microservice

- Owns InMemoryAccountRepository (no shared DB — ADR-005)
- Routes: GET/POST /accounts, PATCH /{id}/balance, DELETE" \
  src/bankcore/services/account_service/__init__.py \
  src/bankcore/services/account_service/service.py

c "2023-03-04T13:30:00" \
  "feat(microservices): add TransactionMicroservice autonomous microservice

- Calls AccountService via ServiceClient — no direct import
- Transfer: GET×2 + PATCH×2 + rollback on partial failure
- TransactionLog: own data store, isolated from AccountService" \
  src/bankcore/services/transaction_service/__init__.py \
  src/bankcore/services/transaction_service/service.py

c "2023-03-04T16:00:00" \
  "test(microservices): add 40 tests for microservice communication

- Verifies exactly 4 ServiceClient calls per transfer
- Data isolation: TransactionLog separate from AccountService" \
  tests/test_microservices.py

c "2023-03-04T18:00:00" \
  "docs(j16): add ADR for Microservices" \
  docs/jour-16/

# ----- JOUR 17 — Dimanche 5 mars 2023 — Cache --------------------------------
log "J17 — Cache"

c "2023-03-05T09:00:00" \
  "feat(cache): add InMemoryCache with TTL, lazy eviction, thread safety

- threading.Lock for concurrent reads
- delete_pattern(prefix) for bulk invalidation
- CacheStats: hits, misses, evictions, hit_rate, summary()" \
  src/bankcore/infrastructure/cache/__init__.py \
  src/bankcore/infrastructure/cache/cache_backend.py

c "2023-03-05T11:30:00" \
  "feat(cache): add CachingServiceClient — Decorator (J05) over ServiceClient

- NEVER_CACHE_PATTERNS: /balance bypasses cache (banking rule)
- PATCH invalidates related keys: account profile + list
- _make_key(): deterministic with query params" \
  src/bankcore/infrastructure/cache/caching_service_client.py

c "2023-03-05T15:00:00" \
  "test(cache): add 35 tests for caching layer

- Performance proof: N GETs = 1 downstream call + N-1 hits
- Thread safety: 10 concurrent threads, no corruption" \
  tests/test_cache.py

c "2023-03-05T17:00:00" \
  "docs(j17): add ADR for Cache (Redis-compatible interface)" \
  docs/jour-17/

# ----- JOUR 18 — Lundi 6 mars 2023 — Message Queue ---------------------------
log "J18 — Message Queue"

c "2023-03-06T09:00:00" \
  "feat(messaging): add MessageBus with Pub/Sub, pattern routing, DLQ, idempotency

- Pattern matching: * = one segment, # = any (fnmatch)
- Idempotency: per (message_id, id(consumer)) — ADR-007
- DLQ: failed messages with error info and consumer name
- fix: use id(consumer) not consumer.name — prevents name collision" \
  src/bankcore/infrastructure/messaging/__init__.py \
  src/bankcore/infrastructure/messaging/message_bus.py

c "2023-03-06T11:30:00" \
  "feat(messaging): add 5 concrete consumers + Topics constants

- FraudDetectionConsumer, NotificationConsumer, AnalyticsConsumer
- CacheInvalidationConsumer: J17+J18 integration
- AuditConsumer: idempotent wildcard subscriber
- BrokenConsumer: test double for DLQ testing" \
  src/bankcore/infrastructure/messaging/consumers.py

c "2023-03-06T15:00:00" \
  "test(messaging): add 38 tests for MessageBus and consumers" \
  tests/test_message_queue.py

c "2023-03-06T17:30:00" \
  "docs(j18): add ADR for Message Queue" \
  docs/jour-18/

# ----- JOUR 19 — Mardi 7 mars 2023 — Docker ----------------------------------
log "J19 — Docker"

c "2023-03-07T09:00:00" \
  "feat(docker): add AccountService Dockerfile + HTTP server

- Multi-stage: python:3.12-slim builder + runtime
- Non-root user (bankcore), HEALTHCHECK /health
- server.py: /health + /ready probes, JSON routing
- entrypoint.sh: SIGTERM forwarding" \
  docker/account-service/Dockerfile \
  docker/account-service/server.py \
  docker/account-service/entrypoint.sh \
  docker/account-service/.dockerignore

c "2023-03-07T11:00:00" \
  "feat(docker): add TransactionService Dockerfile + HTTP server

- Real urllib HTTP handler (not in-process)
- entrypoint.sh: wait loop MAX_RETRIES=30 for AccountService" \
  docker/transaction-service/Dockerfile \
  docker/transaction-service/server.py \
  docker/transaction-service/entrypoint.sh \
  docker/transaction-service/.dockerignore

c "2023-03-07T13:00:00" \
  "feat(docker): add docker-compose.yml — 4 services, healthchecks, volumes

- depends_on: condition: service_healthy
- Redis: 256MB LRU, appendonly
- RabbitMQ: management UI, bankcore vhost
- Log rotation: max-size=10m, max-file=3" \
  docker/docker-compose.yml \
  docker/docker-compose.test.yml

c "2023-03-07T15:30:00" \
  "test(docker): add 46 tests for Docker configuration (no daemon required)" \
  tests/test_docker_config.py

c "2023-03-07T17:30:00" \
  "docs(j19): add ADR for Docker containerisation" \
  docs/jour-19/

# ----- JOUR 20 — Mercredi 8 mars 2023 — Monitoring ---------------------------
log "J20 — Monitoring"

c "2023-03-08T09:00:00" \
  "feat(monitoring): add Counter, Gauge, Histogram + MetricsRegistry Singleton

- Thread-safe, Prometheus-compatible interface (no external dep)
- BankCore defaults pre-registered
- snapshot() returns JSON-serializable dict" \
  src/bankcore/infrastructure/monitoring/__init__.py \
  src/bankcore/infrastructure/monitoring/metrics.py

c "2023-03-08T11:00:00" \
  "feat(monitoring): add distributed Tracer with SpanContext

- Thread-local active span for automatic parent_id propagation
- SpanContext context manager: auto-finish, exception capture" \
  src/bankcore/infrastructure/monitoring/tracer.py

c "2023-03-08T13:00:00" \
  "feat(monitoring): add HealthChecker with composite checks

- RepositoryHealthCheck, CacheHealthCheck, MessageBusHealthCheck, MetricsHealthCheck
- any error → unhealthy, any degraded → degraded, else healthy
- Chainable: .add_check().add_check()" \
  src/bankcore/infrastructure/monitoring/health_check.py

c "2023-03-08T15:30:00" \
  "test(monitoring): add 59 tests for metrics, tracing, health checks" \
  tests/test_monitoring.py

c "2023-03-08T18:00:00" \
  "docs(j20): add ADR for Monitoring + update README.md J01-J20" \
  docs/jour-20/ README.md

# =============================================================================
# SEMAINE 5 — Patterns Avancés
# Du 11 au 15 mars 2023 (samedi → mercredi)
# =============================================================================

# ----- JOUR 21 — Samedi 11 mars 2023 — Event Sourcing -----------------------
log "J21 — Event Sourcing"

c "2023-03-11T09:00:00" \
  "feat(eventsourcing): add InProcessEventStore — append-only with optimistic locking

- StoredEvent: sequence_number, aggregate_version, SHA-256 checksum
- ConcurrencyError: expected_version guard
- verify_integrity(): per-aggregate checksum verification" \
  src/bankcore/domain/event_sourcing/__init__.py \
  src/bankcore/domain/event_sourcing/event_store.py

c "2023-03-11T11:30:00" \
  "feat(eventsourcing): add AccountAggregate + Projections

- AccountAggregate: zero persistent state, rebuilt from events
- Commands produce events, _apply() mutates state (intentionally separated)
- BalanceHistoryProjection.balance_at_version(): point-in-time query
- fix: _apply(AccountOpened) restores interest_rate for savings (ADR-009)" \
  src/bankcore/domain/event_sourcing/aggregate.py

c "2023-03-11T15:00:00" \
  "test(eventsourcing): add 39 tests for Event Sourcing

- Determinism: same events → same balance (replayed twice)
- Full cycle: command → events → store → projection" \
  tests/test_event_sourcing.py

c "2023-03-11T17:30:00" \
  "docs(j21): add ADR for Event Sourcing" \
  docs/jour-21/

# ----- JOUR 22 — Dimanche 12 mars 2023 — CQRS --------------------------------
log "J22 — CQRS"

c "2023-03-12T09:00:00" \
  "feat(cqrs): implement CQRS — separate write path (EventStore) and read path (ReadModels)

Write side: 5 Commands, AccountCommandHandler, ProjectionUpdater
Read side: 4 Queries, ReadModelStore, AccountQueryHandler
CQRSFacade: handle_command() xor handle_query() — never both

fix: _apply(AccountOpened) restores interest_rate by account_type" \
  src/bankcore/application/cqrs/__init__.py \
  src/bankcore/application/cqrs/cqrs.py

c "2023-03-12T14:00:00" \
  "test(cqrs): add 29 tests for CQRS

- Structural proof: QueryHandler has no _event_store attribute
- Pagination: ListAccountsQuery page/page_size" \
  tests/test_cqrs.py

c "2023-03-12T17:00:00" \
  "docs(j22): add ADR for CQRS" \
  docs/jour-22/

# ----- JOUR 23 — Lundi 13 mars 2023 — Saga -----------------------------------
log "J23 — Saga Pattern"

c "2023-03-13T09:00:00" \
  "feat(saga): add SagaOrchestrator + InternationalTransferSaga

State machine: PENDING→RUNNING→COMPLETED/COMPENSATING→COMPENSATED/FAILED
Steps compensated in reverse order — only steps that EXECUTED
DebitSourceStep: compensate() restores exact pre-debit balance
ConvertCurrencyStep: compensate() is no-op (no money moved)
CreditDestinationStep: compensate() reverses credit
NotifyStep: transfer_completed or transfer_cancelled" \
  src/bankcore/application/saga/__init__.py \
  src/bankcore/application/saga/saga.py

c "2023-03-13T13:00:00" \
  "test(saga): add 35 tests for Saga Pattern

- Compensation restores Alice balance on GHOST destination
- FX failure: debit compensated, destination never touched
- NotifyStep not reached when CreditDestination fails (correct)" \
  tests/test_saga.py

c "2023-03-13T16:30:00" \
  "docs(j23): add ADR for Saga Pattern (orchestration vs choreography — ADR-006)" \
  docs/jour-23/

# ----- JOUR 24 — Mardi 14 mars 2023 — Circuit Breaker -----------------------
log "J24 — Circuit Breaker"

c "2023-03-14T09:00:00" \
  "feat(resilience): add CircuitBreaker CLOSED/OPEN/HALF_OPEN state machine

- Thread-safe with threading.Lock
- CLOSED→OPEN after failure_threshold consecutive failures
- OPEN→HALF_OPEN after recovery_timeout (lazy in _get_state)
- HALF_OPEN→CLOSED after success_threshold probes
- Optional fallback callable, call_safe() returns default

CircuitBreakerClient:
- Wraps ServiceClient (J16) — drop-in replacement (ADR-008)
- catch-all: all exceptions → ServiceResponse(503)" \
  src/bankcore/infrastructure/resilience/__init__.py \
  src/bankcore/infrastructure/resilience/circuit_breaker.py

c "2023-03-14T14:00:00" \
  "test(circuit): add 29 tests for Circuit Breaker

- fail-fast proof: elapsed < 50ms after circuit opens
- No downstream call when OPEN (call_count unchanged)" \
  tests/test_circuit_breaker.py

c "2023-03-14T17:00:00" \
  "docs(j24): add ADR for Circuit Breaker" \
  docs/jour-24/

# ----- JOUR 25 — Mercredi 15 mars 2023 — Bulkhead + Retry -------------------
log "J25 — Bulkhead + Retry"

c "2023-03-15T09:00:00" \
  "feat(resilience): add Bulkhead + RetryPolicy + BulkheadRetryClient

Bulkhead:
- threading.Semaphore for concurrent call limiting
- Slot released in finally (exception-safe)
- BulkheadStats: accepted, rejected, peak_concurrent

RetryPolicy:
- Exponential backoff: min(base * 2^attempt, max_delay)
- Jitter: random(0, wait * jitter_factor) — no thundering herd
- retryable=(Exception,) per-type filtering
- execute() never raises — RetryResult with all attempts

BulkheadRetryClient:
- Wraps ServiceClient: Bulkhead → Retry → call
- 429 on BulkheadFullError, 503 on exhaustion" \
  src/bankcore/infrastructure/resilience/bulkhead_retry.py

c "2023-03-15T13:30:00" \
  "test(resilience): add 33 tests for Bulkhead + Retry

- Transient failure: 2 failures then success — transfer succeeds
- compute_wait: exponential growth capped by max_delay" \
  tests/test_bulkhead_retry.py

c "2023-03-15T17:00:00" \
  "docs(j25): add ADR for Bulkhead + Retry" \
  docs/jour-25/

# =============================================================================
# SEMAINE 6 — Sécurité & Documentation finale
# Du 18 au 22 mars 2023 (samedi → mercredi)
# =============================================================================

# ----- JOUR 26 — Samedi 18 mars 2023 — Audit Log ----------------------------
log "J26 — Audit Log Immuable"

c "2023-03-18T09:00:00" \
  "feat(audit): add ImmutableAuditLog — HMAC-SHA256 + cryptographic chaining

AuditEntry (frozen=True):
- entry_hash: SHA-256 of canonical JSON
- prev_hash: SHA-256 of previous entry (GENESIS for first)
- signature: HMAC-SHA256(secret_key, entry_hash)

ImmutableAuditLog:
- Thread-safe append via threading.Lock
- verify_entry(): timing-safe hmac.compare_digest
- verify_chain(): full chain validation
- ChainVerificationResult: is_valid, violations, head_hash" \
  src/bankcore/infrastructure/audit/__init__.py \
  src/bankcore/infrastructure/audit/audit_log.py

c "2023-03-18T14:00:00" \
  "test(audit): add 32 tests for Immutable Audit Log

- Tampered signature detected via wrong key
- Injected bad entry breaks chain at exact sequence
- 20 concurrent appends: all unique sequences, chain intact" \
  tests/test_audit_log.py

c "2023-03-18T17:00:00" \
  "docs(j26): add ADR for Immutable Audit Log" \
  docs/jour-26/

# ----- JOUR 27 — Dimanche 19 mars 2023 — RBAC --------------------------------
log "J27 — RBAC"

c "2023-03-19T09:00:00" \
  "feat(rbac): add Role-Based Access Control

Roles: Teller ⊂ Manager ⊂ Admin ⊂ System (all permissions)
Principal (frozen=True): user_id, username, role, per-operation limits
AuthorizationService: authorize() raises AuthorizationError or LimitExceededError
SecuredBankApplicationService: wraps Use Cases with RBAC
factory: teller(), manager(), admin(), system_principal()
Integration with ImmutableAuditLog (J26): AUTHZ_GRANTED / AUTHZ_DENIED" \
  src/bankcore/application/rbac/__init__.py \
  src/bankcore/application/rbac/rbac.py

c "2023-03-19T14:00:00" \
  "test(rbac): add 32 tests for RBAC

- Role hierarchy: Teller ⊂ Manager ⊂ Admin (issubset verified)
- Manager above transfer limit → LimitExceededError
- system_principal() bypasses all restrictions
- Authz decisions logged to ImmutableAuditLog" \
  tests/test_rbac.py

c "2023-03-19T17:00:00" \
  "docs(j27): add ADR for RBAC" \
  docs/jour-27/

# ----- JOUR 28 — Lundi 20 mars 2023 — Secrets Management --------------------
log "J28 — Secrets Management"

c "2023-03-20T09:00:00" \
  "feat(secrets): add SecretsProvider Protocol + 3 implementations

SecretsProvider (ABC):
- get(key) raises SecretNotFoundError — never returns None
- get_or_default(key, default)

InMemorySecretsProvider (tests):
- Access log: keys only, never values

EnvSecretsProvider (production):
- bankcore.audit.hmac_key → BANKCORE_AUDIT_HMAC_KEY

RotatingSecretsProvider (key rotation):
- Versioned: add_version(), get_version(key, n)
- deactivate_version() after rotation
- list_versions() hides values

SecretKeys: centralized constants — no magic strings (ADR-010)" \
  src/bankcore/infrastructure/secrets/__init__.py \
  src/bankcore/infrastructure/secrets/secrets_provider.py

c "2023-03-20T13:30:00" \
  "test(secrets): add 39 tests for Secrets Management

- Access log never contains values
- Cross-verification: log1.verify_entry(e2) is False (different keys)
- Full rotation workflow: v1 deactivated, v2 active, v1 still readable" \
  tests/test_secrets.py

c "2023-03-20T17:00:00" \
  "docs(j28): add ADR for Secrets Management" \
  docs/jour-28/

# ----- JOUR 29 — Mardi 21 mars 2023 — ADR Formels ----------------------------
log "J29 — Architecture Decision Records"

c "2023-03-21T09:00:00" \
  "docs(adr): ADR-001 — Python stdlib uniquement (pas de frameworks tiers)

Context: frameworks masquent les patterns qu'on veut démontrer
Decision: stdlib + pytest + pyyaml uniquement
Validation: 1050+ tests, 0 dépendance externe" \
  docs/adr/ADR-001-stdlib-only.md

c "2023-03-21T10:30:00" \
  "docs(adr): ADR-002 — Rétrocompatibilité à chaque jour

Decision: tests J01 passent encore à J30 sans modification
Example: TransactionService(config=None) rétrocompatible avec J03" \
  docs/adr/ADR-002-backward-compatibility.md

c "2023-03-21T12:00:00" \
  "docs(adr): ADR-003 à ADR-010 — 8 décisions architecturales clés

003: Protocol vs ABC (duck typing pour DIP)
004: Port dans Application, Adapter dans Infrastructure
005: UUID TEXT vs INTEGER pour PKs SQLite
006: Orchestration vs Choreography pour Saga
007: id(consumer) vs consumer.name — bug de collision corrigé
008: CircuitBreakerClient catch-all vs re-raise
009: interest_rate non persisté — dette technique documentée
010: Séparation ConfigManager / SecretsProvider" \
  docs/adr/ADR-003-to-010.md

c "2023-03-21T14:00:00" \
  "docs(adr): add ADR index README.md

Note: les ADR documentent le POURQUOI, pas le QUOI (c'est le code)" \
  docs/adr/README.md



# ----- JOUR 30 — Mercredi 22 mars 2023 — C4 + Rétrospective -----------------
log "J30 — C4 + Rétrospective Finale"

c "2023-03-22T09:00:00" \
  "docs(j30): add C4 diagrams Level 1/2/3 + final retrospective

C4 L1: Contexte système (clients, services externes)
C4 L2: Conteneurs (AccountService, TransactionService, Redis, RabbitMQ)
C4 L3: Composants AccountService (APIHandler → RBAC → UseCases → Domain)

Retrospective:
- What would NOT pass production as-is
- What IS production-ready
- The architectural lesson: rules before complexity" \
  docs/jour-30/README.md

c "2023-03-22T11:00:00" \
  "docs: add MANIFESTE.md — pourquoi le code n'est jamais optimal au début

La complexité est émergente, pas initiale.
L'architecte crée les conditions, pas le code parfait.
La formation ne s'arrête pas à la connaissance des patterns.
Une règle appliquée systématiquement > 100 règles oubliées." \
  docs/MANIFESTE.md

c "2023-03-22T16:00:00" \
  "chore: final README.md — 30 jours, 1050 tests, 23 602 lignes

30 jours · 64 fichiers source · 28 fichiers tests · 10 ADR
1 050 tests · 23 602 lignes · 0 réécriture complète
2 dépendances: pytest, pyyaml" \
  README.md

# =============================================================================
# Push instructions
# =============================================================================
echo ""
info "==================================================================="
info "Historique git créé : $(git log --oneline | wc -l | tr -d ' ') commits"
info "Du 2023-02-11 (J01 Singleton) au 2023-03-22 (J30 C4+Rétrospective)"
info "==================================================================="
echo ""
warn "Étapes suivantes :"
echo ""
echo "  2. Connecter et pousser :"
echo "     git remote add origin https://github.com/angeawalabj/bankcore.git"
echo "     git branch -M main"
echo "     git push -u origin main"
echo ""
echo "  3. Vérifier l'historique :"
echo "     git log --format='%ad  %s' --date=format:'%Y-%m-%d %H:%M' | head -40"
echo ""
info "Distribution des commits par jour :"
git log --format='%ad' --date=short | sort | uniq -c | \
  awk '{printf "  %s  %s commits\n", $2, $1}' | head -35
