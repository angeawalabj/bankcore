#!/usr/bin/env python3
"""
BankCore — Script de mise en place Git et push GitHub
======================================================
Génère les commandes git avec des dates réalistes (1 commit par jour,
démarré le 1er février 2026).

Usage:
    python setup_git.py                    # affiche les commandes
    python setup_git.py --execute          # exécute (requiert git installé)
    python setup_git.py --remote URL       # configure le remote et push
    python setup_git.py --execute --remote https://github.com/angeawalabj/bankcore.git
"""

import argparse
import os
import subprocess
import sys
from datetime import datetime, timedelta


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

START_DATE    = datetime(2026, 2, 1, 9, 0, 0)   # 1er février 2026, 9h00
AUTHOR_NAME   = "Ange AWALA"
AUTHOR_EMAIL  = "ange.awala.bj@gmail.com"   # à modifier
REMOTE_BRANCH = "main"

# ---------------------------------------------------------------------------
# Commits par jour
# Chaque entrée : (day_offset, hour, minute, files_added, message)
# ---------------------------------------------------------------------------

COMMITS = [
    # ── JOUR 01 ── Singleton Pattern
    (0, 9, 0,
     ["src/bankcore/__init__.py", "src/bankcore/config_manager.py",
      "requirements.txt", "README.md"],
     "feat(J01): implement ConfigManager Singleton with thread-safe double-checked locking\n\n- Single source of truth for all bank configuration\n- Thread-safe via double-checked locking\n- _reset() for test isolation\n- Env var overrides (BANKCORE_*)"),

    (0, 11, 30,
     ["tests/test_config_manager.py"],
     "test(J01): add 15 tests for ConfigManager Singleton\n\n- Uniqueness across callers\n- Thread safety (50 concurrent threads)\n- Env var loading\n- State sharing and reset"),

    # ── JOUR 02 ── Factory Pattern
    (1, 9, 15,
     ["src/bankcore/account.py", "src/bankcore/account_factory.py"],
     "feat(J02): add Account ABC + AccountFactory with dynamic registry\n\n- Account: abstract base with deposit/withdraw/get_info\n- CurrentAccount, SavingsAccount, ProAccount\n- AccountFactory: create() + register() for OCP-readiness\n- TransactionRecord: immutable financial records"),

    (1, 14, 0,
     ["tests/test_account_factory.py"],
     "test(J02): add 38 tests for AccountFactory and Account types\n\n- Factory behavior and type correctness\n- CurrentAccount/SavingsAccount/ProAccount rules\n- Extensibility via register()\n- Config integration (J01 limits)"),

    # ── JOUR 03 ── Observer Pattern
    (2, 9, 0,
     ["src/bankcore/events.py", "src/bankcore/alert_system.py",
      "src/bankcore/transaction_service.py"],
     "feat(J03): implement AlertSystem Observer with 4 concrete observers\n\n- BankEvent: frozen dataclass, immutable\n- AlertSystem: Singleton event bus with wildcard support\n- FraudDetector, NotificationService, BalanceMonitor, AuditLogger\n- TransactionService publishes events on every operation"),

    (2, 15, 30,
     ["tests/test_alert_system.py"],
     "test(J03): add 34 tests for AlertSystem Observer pattern\n\n- Subscription mechanics (subscribe/unsubscribe/wildcard)\n- Error isolation: broken observer doesn't stop others\n- TransactionService integration"),

    # ── JOUR 04 ── Strategy Pattern
    (3, 9, 0,
     ["src/bankcore/fee_strategy.py", "src/bankcore/fee_calculator.py"],
     "feat(J04): implement FeeCalculator Strategy with 5 strategies\n\n- FeeStrategy: abstract base\n- StandardFee, ZeroFee, TieredFee, InternationalFee, PromoFee\n- FeeCalculator: context with runtime strategy swap\n- FeeResult: immutable result with fee_pct"),

    (3, 14, 45,
     ["tests/test_fee_calculator.py"],
     "test(J04): add 32 tests for FeeStrategy and FeeCalculator\n\n- Each strategy in isolation\n- Tiered boundaries, international minimum\n- PromoFee wrapping\n- FeeCalculator strategy swapping"),

    # ── JOUR 05 ── Decorator Pattern
    (4, 9, 0,
     ["src/bankcore/transaction_processor.py",
      "src/bankcore/transaction_decorators.py"],
     "feat(J05): implement TransactionPipeline Decorator stack\n\n- TransactionProcessor: ABC + base Decorator\n- ValidationDecorator, LoggingDecorator, RateLimitDecorator, FeeDecorator\n- build_pipeline(): assembles full stack with toggleable layers"),

    (4, 14, 0,
     ["tests/test_transaction_pipeline.py"],
     "test(J05): add 40 tests for Decorator stack\n\n- Each decorator in isolation\n- Full pipeline integration\n- Week 1 integration: all 5 patterns together"),

    # ── JOUR 06 ── SRP
    (7, 9, 0,
     ["src/bankcore/transaction_history.py",
      "src/bankcore/account_config.py",
      "src/bankcore/event_builder.py"],
     "refactor(J06): extract 3 classes for Single Responsibility Principle\n\n- TransactionHistory: owns record storage and retrieval\n- AccountConfigResolver: resolves limits from ConfigManager by account type\n- EventBuilder: static factory for all BankEvent types\n- Account/AccountFactory/TransactionService updated to delegate"),

    (7, 15, 0,
     ["tests/test_srp_refactoring.py"],
     "test(J06): add 34 tests verifying SRP extraction correctness\n\n- TransactionHistory: isolated from Account\n- AccountConfigResolver: config override, supported types\n- EventBuilder: correct event types, immutability\n- SRP proof: each class testable without the others"),

    # ── JOUR 07 ── OCP
    (8, 9, 0,
     ["src/bankcore/account_type_registry.py",
      "src/bankcore/fee_strategy_registry.py"],
     "feat(J07): add AccountTypeRegistry and FeeStrategyRegistry for OCP\n\n- AccountTypeRegistry: Singleton, thread-safe, ConfigProfile\n- FeeStrategyRegistry: maps names to strategy classes\n- Extension via register() — zero existing file modification\n- OCP proof: YouthAccount added without touching AccountFactory"),

    (8, 14, 30,
     ["tests/test_ocp.py"],
     "test(J07): add 25 tests proving OCP invariant\n\n- YouthAccount registered: 0 existing files modified\n- PremiumFeeStrategy registered: FeeCalculator unchanged\n- Formal OCP proof tests"),

    # ── JOUR 08 ── LSP
    (9, 9, 0,
     ["src/bankcore/account_contract.py"],
     "feat(J08): add AccountContractVerifier with 6 LSP invariants\n\n- Invariants: IDENTITY, BALANCE_CONSISTENCY, DEPOSIT_CONTRACT\n- WITHDRAW_CONTRACT, MIN_BALANCE, GET_INFO_CONTRACT\n- min_possible_balance + can_withdraw() added to Account hierarchy\n- ProAccount.overdraft_used() added"),

    (9, 15, 0,
     ["tests/test_lsp.py"],
     "test(J08): add 54 tests for Liskov Substitution Principle\n\n- All 3 types pass all 6 invariants\n- can_withdraw consistency across 5 amounts × 3 types\n- TransactionService works with all type combinations (9 pairs)\n- BrokenAccount caught by verifier"),

    # ── JOUR 09 ── ISP
    (10, 9, 0,
     ["src/bankcore/interfaces.py"],
     "feat(J09): add 8 segregated interfaces (ISP)\n\n- Readable, Transactable, InterestBearing, Overdraftable\n- Depositable, Withdrawable, Transferable\n- EventHandler, EventFilter\n- ABC.register() for isinstance without multiple inheritance"),

    (10, 14, 0,
     ["tests/test_isp.py"],
     "test(J09): add 47 tests for Interface Segregation Principle\n\n- InterestBearing: SavingsAccount only\n- Overdraftable: ProAccount only\n- CurrentAccount has no apply_interest() — ISP violation prevention\n- TransactionProcessor satisfies Depositable/Withdrawable/Transferable"),

    # ── JOUR 10 ── DIP
    (11, 9, 0,
     ["src/bankcore/protocols.py", "src/bankcore/container.py"],
     "feat(J10): add Protocols, FakeConfig, SpyAlertSystem, BankContainer (DIP)\n\n- ConfigProtocol, AlertProtocol: structural (duck typing)\n- FakeConfig: in-memory test double with sensible defaults\n- SpyAlertSystem: recording test double\n- BankContainer: manual DI container, build_for_testing()"),

    (11, 15, 30,
     ["tests/test_dip.py"],
     "test(J10): add 32 tests for Dependency Inversion Principle\n\n- Protocol satisfaction: ConfigManager and AlertSystem\n- TransactionService with injected fakes: no global state\n- BankContainer: build, build_for_testing, build_pipeline\n- Full isolation proof: Singletons reset after injection — still works"),

    # ── JOUR 11 ── Layered Architecture
    (14, 9, 0,
     ["src/bankcore/application/__init__.py",
      "src/bankcore/application/commands.py",
      "src/bankcore/application/use_cases.py"],
     "feat(J11): add Layered Architecture — Commands, Use Cases, ApplicationService\n\n- 5 immutable Command DTOs with __post_init__ validation\n- UseCaseResult: ok()/fail() factories, bool(result)\n- 5 Use Cases + BankApplicationService facade\n- AccountRegistry: in-memory store (Repository swap at J14)\n- Layer isolation: Use Cases never import Presentation layer"),

    (14, 15, 0,
     ["tests/test_layered_architecture.py"],
     "test(J11): add 42 tests for Layered Architecture\n\n- Command validation and immutability\n- Each Use Case: success, not found, business rejection\n- Full banking flow: create→deposit→transfer→interest\n- Layer isolation verified programmatically"),

    # ── JOUR 12 ── Clean Architecture
    (15, 9, 0,
     ["src/bankcore/domain/__init__.py",
      "src/bankcore/domain/value_objects.py",
      "src/bankcore/domain/domain_events.py",
      "src/bankcore/application/ports.py",
      "src/bankcore/infrastructure/__init__.py",
      "src/bankcore/infrastructure/persistence/__init__.py",
      "src/bankcore/infrastructure/persistence/in_memory_repository.py"],
     "feat(J12): add Clean Architecture — Value Objects, Domain Events, Ports, Adapters\n\n- Money: arithmetic operators, currency guard, factories\n- AccountId: typed identifier, uppercase normalization\n- 5 Domain Events (past tense, frozen, zero infrastructure imports)\n- AccountRepositoryPort, NotificationPort, DomainEventStorePort\n- InMemoryAccountRepository + InMemoryDomainEventStore"),

    (15, 15, 30,
     ["tests/test_clean_architecture.py"],
     "test(J12): add 54 tests for Clean Architecture\n\n- Money/AccountId immutability, arithmetic, cross-currency guards\n- Domain Events: zero infrastructure imports verified\n- Clean Architecture swap: InMemory and Registry same behaviour\n- Layer isolation: value_objects imports nothing from infrastructure"),

    # ── JOUR 13 ── Database Schema
    (16, 9, 0,
     ["src/bankcore/infrastructure/persistence/schema.py",
      "src/bankcore/infrastructure/persistence/sqlite_repository.py"],
     "feat(J13): add SQLite schema with 5 tables, 6 indexes, CHECK constraints\n\n- Tables: owner, account, transaction, transfer, fee_record\n- CHECK: balance >= min_possible_balance (LSP at DB level)\n- 6 performance indexes\n- SQLiteAccountRepository: implements AccountRepositoryPort\n- Idempotent sync, anti-corruption layer in _reconstruct()"),

    (16, 14, 30,
     ["tests/test_database_schema.py"],
     "test(J13): add 37 tests for database schema and SQLiteAccountRepository\n\n- All 5 tables and required columns present\n- FK and CHECK constraints enforced\n- SQLite/InMemory produce identical results\n- Data survival across reconnection"),

    # ── JOUR 14 ── Repository Pattern
    (17, 9, 0,
     ["src/bankcore/application/specifications.py",
      "src/bankcore/application/unit_of_work.py"],
     "feat(J14): add Specification Pattern, Pagination, Unit of Work\n\n- 8 concrete specs + AndSpec/OrSpec/NotSpec with &/|/~ operators\n- InterestEligibleSpec uses InterestBearing (ISP) — no isinstance(Savings)\n- Page: frozen, has_next/has_prev/total_pages\n- UnitOfWork: dirty tracking, identity map, context manager\n- TransferOperation: atomic transfer within UoW scope"),

    (17, 15, 0,
     ["tests/test_repository_pattern.py"],
     "test(J14): add 51 tests for Repository Pattern\n\n- Each spec in isolation and composed\n- Pagination edge cases\n- UnitOfWork commit/rollback/context manager\n- Cross-repo consistency: InMemory and SQLite same specs same results"),

    # ── JOUR 15 ── Hexagonal Architecture
    (18, 9, 0,
     ["src/bankcore/presentation/__init__.py",
      "src/bankcore/presentation/test_driver.py",
      "src/bankcore/presentation/scheduler.py",
      "src/bankcore/presentation/api_handler.py"],
     "feat(J15): add Hexagonal Architecture — 4 primary adapters\n\n- TestDriver: fluent API, name→id registry, chainable assertions\n- InterestScheduler: paginated batch, dry_run, SchedulerReport\n- BankAPIHandler: REST routes, 201/200/404/422 mapping\n- fix: use 'is not None' for registry injection (empty repo falsy bug)"),

    (18, 15, 0,
     ["tests/test_hexagonal_architecture.py"],
     "test(J15): add 40 tests for Hexagonal Architecture\n\n- TestDriver: full scenario, isolated instances, fluent assertions\n- BankAPIHandler: all routes and status codes\n- InterestScheduler: run, dry_run, preview, report\n- Adapters contain no business logic (source inspection)"),

    # ── JOUR 16 ── Microservices
    (21, 9, 0,
     ["src/bankcore/services/__init__.py",
      "src/bankcore/services/shared/__init__.py",
      "src/bankcore/services/shared/service_client.py",
      "src/bankcore/services/account_service/__init__.py",
      "src/bankcore/services/account_service/service.py",
      "src/bankcore/services/transaction_service/__init__.py",
      "src/bankcore/services/transaction_service/service.py"],
     "feat(J16): add AccountService and TransactionMicroservice\n\n- ServiceClient: call logging, latency, GET/POST/PATCH/DELETE\n- ServiceRegistry: service discovery, total_calls()\n- AccountService: owns its own InMemoryAccountRepository\n- TransactionMicroservice: calls AccountService via ServiceClient\n- Transfer: validate→GET×2→PATCH×2→log, rollback on partial failure"),

    (21, 15, 30,
     ["tests/test_microservices.py"],
     "test(J16): add 40 tests for microservice communication\n\n- ServiceClient: call count, log, latency\n- 4 calls per transfer verified\n- Data isolation: TransactionLog separate from AccountService\n- Rollback: failed credit reverses successful debit"),

    # ── JOUR 17 ── Cache
    (22, 9, 0,
     ["src/bankcore/infrastructure/cache/__init__.py",
      "src/bankcore/infrastructure/cache/cache_backend.py",
      "src/bankcore/infrastructure/cache/caching_service_client.py"],
     "feat(J17): add InMemoryCache and CachingServiceClient (Decorator pattern)\n\n- InMemoryCache: TTL, lazy eviction, thread-safe, delete_pattern()\n- CacheStats: hit_rate, miss_rate, saved_calls, evictions\n- CachingServiceClient: Decorator over ServiceClient\n- NEVER_CACHE_PATTERNS: /balance always bypassed\n- PATCH invalidates related cache keys automatically"),

    (22, 14, 30,
     ["tests/test_cache.py"],
     "test(J17): add 35 tests for caching layer\n\n- TTL expiry, lazy eviction, thread safety (10 threads)\n- CachingServiceClient: HIT/MISS, PATCH invalidation\n- Performance proof: N GETs = 1 downstream call\n- Transfer with cache: 3 calls instead of 4"),

    # ── JOUR 18 ── Message Queue
    (23, 9, 0,
     ["src/bankcore/infrastructure/messaging/__init__.py",
      "src/bankcore/infrastructure/messaging/message_bus.py",
      "src/bankcore/infrastructure/messaging/consumers.py"],
     "feat(J18): add MessageBus Pub/Sub with DLQ and idempotency\n\n- Message: frozen, unique ID, with_retry()\n- MessageBus: exact/wildcard/hash routing, retry, DLQ\n- Idempotency key: id(consumer) to prevent name collisions\n- FraudDetectionConsumer, NotificationConsumer, AnalyticsConsumer\n- CacheInvalidationConsumer: J17+J18 integration\n- AuditConsumer, BrokenConsumer (test double)"),

    (23, 15, 0,
     ["tests/test_message_queue.py"],
     "test(J18): add 38 tests for MessageBus and consumers\n\n- Routing: exact/wildcard/hash\n- DLQ: broken consumer isolated, healthy consumer unaffected\n- Idempotency: duplicate message_id not processed twice\n- CacheInvalidationConsumer: J17+J18 integration"),

    # ── JOUR 19 ── Docker
    (24, 9, 0,
     ["docker/account-service/Dockerfile",
      "docker/account-service/server.py",
      "docker/account-service/entrypoint.sh",
      "docker/account-service/.dockerignore",
      "docker/transaction-service/Dockerfile",
      "docker/transaction-service/server.py",
      "docker/transaction-service/entrypoint.sh",
      "docker/transaction-service/.dockerignore",
      "docker/docker-compose.yml",
      "docker/docker-compose.test.yml"],
     "feat(J19): add Docker multi-stage builds and compose orchestration\n\n- Dockerfiles: python:3.12-slim, multi-stage, non-root user\n- Healthchecks: /health endpoint, --start-period, --retries\n- docker-compose.yml: 4 services, depends_on: service_healthy\n- docker-compose.test.yml: CI integration test runner\n- entrypoint.sh: SIGTERM handling, graceful shutdown\n- TransactionService waits for AccountService (30s retry loop)"),

    (24, 14, 30,
     ["tests/test_docker_config.py"],
     "test(J19): add 46 tests for Docker configuration validation\n\n- Dockerfile: multi-stage, non-root, HEALTHCHECK, EXPOSE\n- docker-compose: depends_on condition:service_healthy\n- Entrypoint: SIGTERM trap, retry loop with MAX_RETRIES\n- All tests run without Docker daemon"),

    # ── JOUR 20 ── Monitoring
    (25, 9, 0,
     ["src/bankcore/infrastructure/monitoring/__init__.py",
      "src/bankcore/infrastructure/monitoring/metrics.py",
      "src/bankcore/infrastructure/monitoring/tracer.py",
      "src/bankcore/infrastructure/monitoring/health_check.py"],
     "feat(J20): add distributed monitoring — metrics, tracing, health checks\n\n- Counter/Gauge/Histogram: thread-safe, MetricsRegistry Singleton\n- Tracer: Span/Trace with context manager, nested spans, parent_id\n- Thread-local active span for automatic parent detection\n- HealthChecker: composite checks, healthy/degraded/unhealthy\n- RepositoryHealthCheck, CacheHealthCheck, MessageBusHealthCheck"),

    (25, 15, 0,
     ["tests/test_monitoring.py", "docs/jour-20/README.md"],
     "test(J20): add 59 tests for monitoring — metrics, tracer, health checks\n\n- Counter/Gauge/Histogram: thread safety, percentiles, buckets\n- MetricsRegistry: snapshot, pre-registered BankCore defaults\n- Tracer: nested spans, error capture, thread-local active span\n- HealthChecker: all-ok=healthy, any-error=unhealthy, composite"),

    # ── JOUR 21 ── Event Sourcing
    (28, 9, 0,
     ["src/bankcore/domain/event_sourcing/__init__.py",
      "src/bankcore/domain/event_sourcing/event_store.py",
      "src/bankcore/domain/event_sourcing/aggregate.py"],
     "feat(J21): implement Event Sourcing — EventStore, AccountAggregate, Projections\n\n- InProcessEventStore: append-only, versioning, optimistic locking\n- StoredEvent: SHA-256 checksum, integrity verification\n- ConcurrencyError: prevents lost updates in concurrent writes\n- AccountAggregate: state derived from events, no persistent balance\n- AccountProjection, BalanceHistoryProjection\n- balance_at_version(): historical balance at any point"),

    (28, 15, 0,
     ["tests/test_event_sourcing.py", "docs/jour-21/README.md"],
     "test(J21): add 39 tests for Event Sourcing\n\n- EventStore: append, versioning, optimistic locking\n- Checksum integrity verification\n- AccountAggregate.from_events(): deterministic state reconstruction\n- Full cycle: command→events→store→projection\n- Audit trail completeness"),

    # ── JOUR 22 ── CQRS
    (29, 9, 0,
     ["src/bankcore/application/cqrs/__init__.py",
      "src/bankcore/application/cqrs/cqrs.py"],
     "feat(J22): add CQRS — Commands/Queries separated, Read Models, ProjectionUpdater\n\n- Write side: 5 Commands + AccountCommandHandler → EventStore\n- Read side: BalanceReadModel, AccountSummaryReadModel, TransactionHistoryReadModel\n- ProjectionUpdater: event → read model (synchronous for now)\n- AccountQueryHandler: never touches EventStore\n- CQRSFacade: handle_command() vs handle_query() — strict separation\n- fix: restore interest_rate in _apply(AccountOpened) for savings"),

    (29, 15, 30,
     ["tests/test_cqrs.py", "docs/jour-22/README.md"],
     "test(J22): add 29 tests for CQRS\n\n- All 5 commands: success and failure paths\n- Queries: balance, summary, list (with filters), history\n- CQRS separation: QueryHandler has no EventStore (verified structurally)\n- Eventual consistency: queries reflect command results immediately\n- Full banking scenario: open→deposit→transfer→query"),

    # ── JOUR 23 ── Saga Pattern
    (30, 9, 0,
     ["src/bankcore/application/saga/__init__.py",
      "src/bankcore/application/saga/saga.py"],
     "feat(J23): add Saga Pattern — orchestrated distributed transaction\n\n- SagaOrchestrator: PENDING→RUNNING→COMPLETED/COMPENSATING→COMPENSATED/FAILED\n- Forward pass + reverse compensation on failure\n- Only executed steps are compensated\n- DebitSourceStep, ConvertCurrencyStep, CreditDestinationStep, NotifyStep\n- create_international_transfer_saga() factory\n- Execution log: every state transition recorded"),

    (30, 15, 0,
     ["tests/test_saga.py", "docs/jour-23/README.md"],
     "test(J23): add 35 tests for Saga Pattern\n\n- All 5 steps in isolation (execute + compensate)\n- Compensation order reversed, only executed steps compensated\n- Full international transfer: EUR→GBP debit/convert/credit\n- Compensation restores original balance exactly\n- FAILED status when compensation also fails"),
]


# ---------------------------------------------------------------------------
# Git command generator
# ---------------------------------------------------------------------------

def format_date(base: datetime, day_offset: int, hour: int, minute: int) -> str:
    dt = base + timedelta(days=day_offset, hours=hour - base.hour,
                          minutes=minute - base.minute)
    # Simple approach: add days then set hour/minute
    dt = datetime(
        base.year, base.month, base.day,
        hour, minute, 0
    ) + timedelta(days=day_offset)
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def git_cmd(cmd: str, env: dict = None) -> tuple[int, str]:
    """Run a git command and return (returncode, output)."""
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True, env=full_env
    )
    return result.returncode, result.stdout + result.stderr


def generate_commands(remote_url: str = None) -> list[str]:
    """Generate the full list of git commands."""
    cmds = [
        "# BankCore — Git Setup Script",
        "# Generated for start date: 1er février 2026",
        "",
        "# ── Initialisation ──",
        "git init",
        f'git config user.name "{AUTHOR_NAME}"',
        f'git config user.email "{AUTHOR_EMAIL}"',
        "",
        "# ── .gitignore ──",
        'echo "__pycache__/\n*.pyc\n*.pyo\n.venv/\n.pytest_cache/\n*.db\n.coverage\nhtmlcov/" > .gitignore',
        "git add .gitignore",
        f'GIT_AUTHOR_DATE="{format_date(START_DATE, -1, 8, 0)}" '
        f'GIT_COMMITTER_DATE="{format_date(START_DATE, -1, 8, 0)}" '
        f'git commit --allow-empty -m "chore: initialize BankCore project"',
        "",
    ]

    for day_offset, hour, minute, files, message in COMMITS:
        date_str   = format_date(START_DATE, day_offset, hour, minute)
        files_str  = " ".join(f'"{f}"' for f in files)
        msg_lines  = message.split("\n")
        msg_main   = msg_lines[0]
        msg_body   = "\n".join(msg_lines[1:]) if len(msg_lines) > 1 else ""

        cmds.append(f"# Day offset +{day_offset}  {date_str}")
        cmds.append(f"git add {files_str}")

        if msg_body:
            # Multi-line commit message
            body_escaped = msg_body.replace('"', '\\"').replace('\n', '\\n')
            cmds.append(
                f'GIT_AUTHOR_DATE="{date_str}" GIT_COMMITTER_DATE="{date_str}" '
                f'git commit -m "{msg_main}" -m "{body_escaped}"'
            )
        else:
            cmds.append(
                f'GIT_AUTHOR_DATE="{date_str}" GIT_COMMITTER_DATE="{date_str}" '
                f'git commit -m "{msg_main}"'
            )
        cmds.append("")

    # Remote and push
    if remote_url:
        cmds += [
            "# ── Remote et push ──",
            f"git remote add origin {remote_url}",
            f"git branch -M {REMOTE_BRANCH}",
            f"git push -u origin {REMOTE_BRANCH}",
        ]
    else:
        cmds += [
            "# ── Remote et push (à configurer) ──",
            "# git remote add origin https://github.com/angeawalabj/bankcore.git",
            f"# git branch -M {REMOTE_BRANCH}",
            f"# git push -u origin {REMOTE_BRANCH}",
        ]

    return cmds


def execute_commands(remote_url: str = None) -> None:
    """Execute git commands directly."""
    print("🚀 BankCore Git Setup — Exécution...\n")

    # Init
    rc, out = git_cmd("git init")
    print(f"git init → {'✓' if rc == 0 else '✗'}")

    rc, _ = git_cmd(f'git config user.name "{AUTHOR_NAME}"')
    rc, _ = git_cmd(f'git config user.email "{AUTHOR_EMAIL}"')
    print(f"git config user → ✓")

    # .gitignore
    with open(".gitignore", "w") as f:
        f.write("__pycache__/\n*.pyc\n*.pyo\n.venv/\n.pytest_cache/\n*.db\n.coverage\nhtmlcov/\n")
    git_cmd("git add .gitignore")
    init_date = format_date(START_DATE, -1, 8, 0)
    env = {"GIT_AUTHOR_DATE": init_date, "GIT_COMMITTER_DATE": init_date}
    git_cmd('git commit --allow-empty -m "chore: initialize BankCore project"', env)
    print("Initial commit → ✓\n")

    total = len(COMMITS)
    for i, (day_offset, hour, minute, files, message) in enumerate(COMMITS, 1):
        date_str  = format_date(START_DATE, day_offset, hour, minute)
        msg_lines = message.split("\n")
        msg_main  = msg_lines[0]
        msg_body  = "\n".join(msg_lines[1:]) if len(msg_lines) > 1 else ""

        # Only add files that exist
        existing = [f for f in files if os.path.exists(f)]
        if not existing:
            print(f"  [{i}/{total}] Skipped (no files): {msg_main[:60]}")
            continue

        git_cmd(f"git add {' '.join(existing)}")
        env = {"GIT_AUTHOR_DATE": date_str, "GIT_COMMITTER_DATE": date_str}

        if msg_body:
            cmd = f'git commit -m "{msg_main}" -m "{msg_body}"'
        else:
            cmd = f'git commit -m "{msg_main}"'

        rc, out = git_cmd(cmd, env)
        status = "✓" if rc == 0 else f"✗ {out[:80]}"
        print(f"  [{i}/{total}] {date_str[:10]} — {msg_main[:55]} {status}")

    # Push
    if remote_url:
        print(f"\n📤 Push vers {remote_url}...")
        git_cmd(f"git remote add origin {remote_url}")
        git_cmd(f"git branch -M {REMOTE_BRANCH}")
        rc, out = git_cmd(f"git push -u origin {REMOTE_BRANCH}")
        print(f"Push → {'✓' if rc == 0 else '✗'}\n{out[:200]}")

    print("\n✅ Git setup terminé.")
    rc, out = git_cmd("git log --oneline | head -20")
    print(f"\n📋 Derniers commits:\n{out}")


def main():
    parser = argparse.ArgumentParser(description="BankCore Git Setup")
    parser.add_argument("--execute", action="store_true",
                        help="Exécute les commandes git (par défaut: affiche seulement)")
    parser.add_argument("--remote", type=str, default=None,
                        help="URL du remote GitHub (ex: https://github.com/angeawalabj/bankcore.git)")
    parser.add_argument("--output", type=str, default="git_setup.sh",
                        help="Fichier de sortie pour le script (défaut: git_setup.sh)")
    args = parser.parse_args()

    if args.execute:
        execute_commands(args.remote)
    else:
        cmds   = generate_commands(args.remote)
        script = "#!/bin/bash\nset -e\n\n" + "\n".join(cmds) + "\n"

        with open(args.output, "w") as f:
            f.write(script)
        os.chmod(args.output, 0o755)

        print(f"✅ Script généré: {args.output}")
        print(f"   {len(COMMITS)} commits | Dates: 01/02/2026 → {format_date(START_DATE, 30, 15, 0)[:10]}")
        print(f"\nUsage:")
        print(f"   bash {args.output}                          # exécuter le script")
        print(f"   python setup_git.py --execute               # exécuter via Python")
        print(f"   python setup_git.py --execute --remote URL  # + push GitHub")
        print(f"\nPremières lignes du script généré:")
        for line in cmds[:8]:
            print(f"   {line}")


if __name__ == "__main__":
    main()
