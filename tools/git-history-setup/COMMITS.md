# BankCore — Journal des Commits Git

> Convention : `type(scope): message`
> Types : `feat`, `refactor`, `test`, `docs`, `fix`, `chore`

---

## Jour 01 — Singleton Pattern : ConfigManager

```
feat(config): add ConfigManager singleton with thread-safe double-checked locking

- src/bankcore/config_manager.py
  + ConfigManager class with get_instance(), get(), set(), load_from_env()
  + Thread-safe with threading.Lock (double-checked locking)
  + _reset() method for test isolation
  + Default banking configuration (fees, limits, alerts)

feat(config): load configuration from environment variables

- Supports BANKCORE_DATABASE_URL, BANKCORE_ENVIRONMENT,
  BANKCORE_MAX_TRANSFER, BANKCORE_LOW_BALANCE_THRESHOLD
- Type coercion matches default type per key

test(config): add 15 tests for ConfigManager singleton

- src/bankcore/__init__.py
- tests/test_config_manager.py
  + TestSingletonBehavior (3 tests)
  + TestDefaultConfiguration (6 tests)
  + TestRuntimeOverrides (3 tests)
  + TestEnvironmentVariableLoading (4 tests)
  + TestThreadSafety (1 test — 50 concurrent threads)

docs(config): add README for Jour 01

- docs/jour-01/README.md
  + Problem statement, diagram, decision rationale, trade-offs
```

---

## Jour 02 — Factory Pattern : AccountFactory

```
feat(account): add Account abstract base class with TransactionRecord

- src/bankcore/account.py
  + Account(ABC) with deposit(), withdraw(), get_info(), get_transactions()
  + TransactionRecord dataclass (immutable)
  + CurrentAccount: daily limit, no overdraft
  + SavingsAccount: minimum balance 50 EUR, apply_interest()
  + ProAccount: overdraft limit -5000 EUR, daily limit 50k EUR

feat(factory): add AccountFactory with dynamic registry

- src/bankcore/account_factory.py
  + AccountFactory.create(type, owner, deposit) → Account
  + AccountFactory.register(type, creator) for extension (OCP preview)
  + _register_defaults() reads limits from ConfigManager (J01)
  + Available types: current, savings, pro

test(factory): add 38 tests for AccountFactory and Account types

- tests/test_account_factory.py
  + TestAccountFactoryCreation (11 tests)
  + TestCurrentAccount (7 tests)
  + TestSavingsAccount (5 tests)
  + TestProAccount (4 tests)
  + TestFactoryExtensibility (2 tests)
  + TestConfigIntegration (1 test — J01 + J02 combined)
  + TestAccountReporting (4 tests)

docs(factory): add README for Jour 02

- docs/jour-02/README.md
```

---

## Jour 03 — Observer Pattern : AlertSystem

```
feat(events): add BankEvent dataclass and EventType constants

- src/bankcore/events.py
  + BankEvent(frozen=True) with event_type, account_id, amount, metadata
  + EventType class with TRANSFER, DEPOSIT, WITHDRAWAL, ACCOUNT_CREATED,
    LOW_BALANCE, LARGE_TRANSACTION, FRAUD_SUSPECTED, FEE_APPLIED

feat(alerts): add AlertSystem observer with concrete observers

- src/bankcore/alert_system.py
  + AlertSystem (Singleton) with subscribe(), publish(), unsubscribe()
  + AlertObserver(ABC) with on_event(), supported_events()
  + FraudDetector: large amount + rapid succession detection
  + NotificationService: SMS/email output
  + BalanceMonitor: publishes LOW_BALANCE events
  + AuditLogger: wildcard "*" subscription, immutable log

feat(transactions): add TransactionService with Observer integration

- src/bankcore/transaction_service.py
  + TransactionService.deposit(), withdraw(), transfer()
  + Publishes BankEvent after every successful operation
  + TransactionService knows NOTHING about fraud, notifications, etc.

test(alerts): add 39 tests for AlertSystem and Observer pattern

- tests/test_alert_system.py
  + TestAlertSystemSubscription (5 tests)
  + TestAlertSystemDispatch (7 tests)
  + TestErrorIsolation (2 tests)
  + TestAuditLogger (3 tests)
  + TestBalanceMonitor (4 tests)
  + TestTransactionServiceObserverIntegration (4 tests)

docs(alerts): add README for Jour 03

- docs/jour-03/README.md
```

---

## Jour 04 — Strategy Pattern : FeeCalculator

```
feat(fees): add FeeStrategy abstract + 4 concrete strategies

- src/bankcore/fee_strategy.py
  + FeeStrategy(ABC) with calculate(), description()
  + StandardFeeStrategy: 0.1% current, 0.05% pro, 0% savings
  + ZeroFeeStrategy: always 0
  + TieredFeeStrategy: 0.2% < 500, 0.1% < 5k, 0.05% < 50k, 0.02% above
  + InternationalFeeStrategy: 2% min 5 EUR, pro 1% min 2 EUR
  + PromoFeeStrategy: wraps any strategy with % discount
  + FeeResult frozen dataclass with fee_pct property

feat(fees): add FeeCalculator as Strategy context

- src/bankcore/fee_calculator.py
  + FeeCalculator.apply_fee(account, amount) → FeeResult
  + FeeCalculator.estimate(amount, account_type) — no side effects
  + FeeCalculator.compare_strategies() — multiple strategies compared
  + Publishes FEE_APPLIED event to AlertSystem (J03)

test(fees): add 38 tests for FeeStrategy and FeeCalculator

- tests/test_fee_calculator.py
  + TestStandardFeeStrategy (7 tests)
  + TestZeroFeeStrategy (2 tests)
  + TestTieredFeeStrategy (7 tests)
  + TestInternationalFeeStrategy (4 tests)
  + TestPromoFeeStrategy (6 tests)
  + TestFeeResult (4 tests)
  + TestFeeCalculator (8 tests)

docs(fees): add README for Jour 04

- docs/jour-04/README.md
```

---

## Jour 05 — Decorator Pattern : TransactionPipeline

```
feat(pipeline): add TransactionProcessor interface and base Decorator

- src/bankcore/transaction_processor.py
  + TransactionProcessor(ABC) with deposit(), withdraw(), transfer()
  + TransactionDecorator(TransactionProcessor) — delegates by default

feat(pipeline): add 4 transaction decorators + build_pipeline()

- src/bankcore/transaction_decorators.py
  + ValidationDecorator: input sanity checks, rejects invalid before execution
  + LoggingDecorator: timing, success rate, structured log
  + RateLimitDecorator: sliding window per account
  + FeeDecorator: calculates and debits fees before delegating
  + build_pipeline(service, validate, log, rate_limit, apply_fees) factory

refactor(transactions): TransactionService implements TransactionProcessor

- src/bankcore/transaction_service.py
  + Inherits TransactionProcessor (interface extracted for Decorator pattern)

test(pipeline): add 40 tests for decorators and pipeline

- tests/test_transaction_pipeline.py
  + TestTransactionDecorator (3 tests)
  + TestValidationDecorator (9 tests)
  + TestLoggingDecorator (6 tests)
  + TestRateLimitDecorator (5 tests)
  + TestFeeDecorator (4 tests)
  + TestBuildPipeline (5 tests)
  + TestWeek1Integration (2 tests)

docs(pipeline): add README for Jour 05

- docs/jour-05/README.md
```

---

## Jour 06 — Single Responsibility Principle

```
refactor(srp): extract TransactionHistory from Account

- src/bankcore/transaction_history.py [NEW]
  + TransactionHistory with record(), get_all(), last(), total_credits()
  + total_debits(), filter_by_description(), count()
  + TransactionRecord frozen dataclass moved here

refactor(srp): extract AccountConfigResolver from AccountFactory

- src/bankcore/account_config.py [NEW]
  + AccountConfigResolver reads ConfigManager and maps to per-type defaults
  + resolve_daily_limit(), resolve_overdraft(), resolve_min_balance()
  + resolve_monthly_fee(), resolve_interest_rate(), resolve_all()

refactor(srp): extract EventBuilder from TransactionService

- src/bankcore/event_builder.py [NEW]
  + EventBuilder.transfer_event(), deposit_event(), withdrawal_event()
  + EventBuilder.account_created_event()

refactor(account): Account delegates to TransactionHistory

- src/bankcore/account.py
  ~ _transactions list → self._history: TransactionHistory
  ~ _record() delegates to self._history.record()
  ~ get_transactions() delegates to self._history.get_all()
  + history property exposes TransactionHistory directly

refactor(factory): AccountFactory uses AccountConfigResolver

- src/bankcore/account_factory.py
  ~ _register_defaults() reads from AccountConfigResolver instead of ConfigManager directly

refactor(transactions): TransactionService uses EventBuilder

- src/bankcore/transaction_service.py
  ~ All inline BankEvent construction replaced by EventBuilder static methods
  + self._builder = EventBuilder()

test(srp): add 34 tests for SRP refactoring

- tests/test_srp_refactoring.py
  + TestTransactionHistory (14 tests)
  + TestAccountUsesTransactionHistory (7 tests)
  + TestAccountConfigResolver (9 tests)
  + TestAccountFactoryUsesResolver (3 tests)
  + TestEventBuilder (7 tests — includes immutability)
  + TestSRPProof (3 tests — each class testable in isolation)

docs(srp): add README for Jour 06

- docs/jour-06/README.md
```

---

## Jour 07 — Open/Closed Principle

```
feat(ocp): add AccountTypeRegistry with ConfigProfile

- src/bankcore/account_type_registry.py [NEW]
  + ConfigProfile frozen dataclass (daily_limit, overdraft, min_balance, etc.)
  + AccountTypeRegistry.register(name, creator, profile)
  + AccountTypeRegistry.create(name, owner, deposit)
  + AccountTypeRegistry.get_profile(name)
  + AccountTypeRegistry._register_defaults() — current, savings, pro
  + Creators read AccountConfigResolver at instantiation time

feat(ocp): add FeeStrategyRegistry

- src/bankcore/fee_strategy_registry.py [NEW]
  + FeeStrategyRegistry.register(name, strategy_class)
  + FeeStrategyRegistry.get(name) → FeeStrategy instance
  + FeeStrategyRegistry.create_calculator(name) → FeeCalculator
  + FeeStrategyRegistry.all_instances() → used by compare_strategies()
  + Validates that registered class is a FeeStrategy subclass

refactor(factory): AccountFactory delegates to AccountTypeRegistry

- src/bankcore/account_factory.py
  ~ create() delegates to AccountTypeRegistry.create()
  ~ register() syncs to AccountTypeRegistry
  ~ available_types() delegates to AccountTypeRegistry.available()
  ~ _reset_registry() resets AccountTypeRegistry

refactor(config): AccountConfigResolver reads from AccountTypeRegistry

- src/bankcore/account_config.py
  ~ _DEFAULTS dict removed
  ~ _profile() fetches ConfigProfile from AccountTypeRegistry
  ~ _type_default() reads from ConfigProfile via getattr
  ~ supported_types() delegates to AccountTypeRegistry.available()

refactor(fees): FeeCalculator.compare_strategies uses FeeStrategyRegistry

- src/bankcore/fee_calculator.py
  ~ hardcoded strategy list → FeeStrategyRegistry.all_instances()

test(ocp): add 25 tests for OCP

- tests/test_ocp.py
  + TestAccountTypeRegistryOCP (7 tests)
  + TestFeeStrategyRegistryOCP (8 tests)
  + TestAccountTypeRegistryInternals (8 tests)
  + TestOCPInvariant (2 tests — formal proof: zero existing files modified)

docs(ocp): add README for Jour 07

- docs/jour-07/README.md
```

---

## Jour 08 — Liskov Substitution Principle

```
feat(lsp): add AccountContractVerifier with 6 invariant checks

- src/bankcore/account_contract.py [NEW]
  + ContractViolation dataclass with rule and detail
  + AccountContractVerifier.check(account, test_amount) → list[ContractViolation]
  + AccountContractVerifier.assert_compliant(account) raises on violation
  + _check_identity(), _check_balance_consistency(), _check_deposit_contract()
  + _check_withdraw_contract(), _check_min_balance_invariant()
  + _check_get_info_contract()

feat(account): add min_possible_balance abstract property + can_withdraw()

- src/bankcore/account.py
  + min_possible_balance @abstractmethod on Account
  + CurrentAccount.min_possible_balance = 0.0
  + SavingsAccount.min_possible_balance = self.min_balance
  + ProAccount.min_possible_balance = self.overdraft_limit
  + Account.can_withdraw(amount) default implementation
  + SavingsAccount.can_withdraw() override (checks min_balance)
  + ProAccount.can_withdraw() override (checks daily_limit + overdraft)
  + ProAccount.overdraft_used() method

test(lsp): add 54 tests for LSP

- tests/test_lsp.py
  + TestContractVerifierBuiltInTypes (4 tests)
  + TestIdentityInvariant (3 tests)
  + TestDepositContract (8 tests — parametrized × 3 types)
  + TestWithdrawContract (3 tests)
  + TestMinPossibleBalance (6 tests)
  + TestGetInfoContract (6 tests — parametrized)
  + TestCanWithdraw (4 tests)
  + TestSubstitutability (4 tests — TransactionService with all types)
  + TestViolationDetection (3 tests)
  + TestFutureTypeLSP (2 tests — YouthAccount satisfies LSP)

docs(lsp): add README for Jour 08

- docs/jour-08/README.md
```

---

## Jour 09 — Interface Segregation Principle

```
feat(isp): add segregated interfaces in interfaces.py

- src/bankcore/interfaces.py [NEW]
  + Readable(ABC): get_info(), get_transactions()
  + Transactable(ABC): deposit(), withdraw(), can_withdraw()
  + InterestBearing(ABC): apply_interest(), interest_rate
  + Overdraftable(ABC): overdraft_limit, overdraft_used()
  + Depositable(ABC), Withdrawable(ABC), Transferable(ABC)
  + EventHandler(ABC): on_event()
  + EventFilter(ABC): supported_events()

refactor(account): Account implements Readable + Transactable

- src/bankcore/account.py
  + Account(Readable, Transactable, ABC)
  + InterestBearing.register(SavingsAccount) — ABC virtual subclass
  + Overdraftable.register(ProAccount) — ABC virtual subclass
  - overdraft_used() removed from Account base, kept only in ProAccount

refactor(pipeline): TransactionProcessor implements Depositable+Withdrawable+Transferable

- src/bankcore/transaction_processor.py
  + TransactionProcessor(Depositable, Withdrawable, Transferable, ABC)

refactor(alerts): AlertObserver registered with EventHandler + EventFilter

- src/bankcore/alert_system.py
  + EventHandler.register(AlertObserver)
  + EventFilter.register(AlertObserver)

test(isp): add 47 tests for ISP

- tests/test_isp.py
  + TestReadableInterface (4 tests)
  + TestTransactableInterface (4 tests)
  + TestInterestBearingInterface (7 tests)
  + TestOverdraftableInterface (6 tests)
  + TestTransactionProcessorInterfaces (5 tests)
  + TestEventInterfaces (4 tests)
  + TestISPViolationPrevention (4 tests — negative tests)

docs(isp): add README for Jour 09

- docs/jour-09/README.md
```

---

## Jour 10 — Dependency Inversion Principle

```
feat(dip): add ConfigProtocol, AlertProtocol + test doubles

- src/bankcore/protocols.py [NEW]
  + ConfigProtocol(Protocol, runtime_checkable)
  + AlertProtocol(Protocol, runtime_checkable)
  + EventBuilderProtocol(Protocol)
  + FakeConfig: in-memory ConfigProtocol implementation with test defaults
  + SpyAlertSystem: records events, satisfies AlertProtocol

feat(dip): add BankContainer dependency injection container

- src/bankcore/container.py [NEW — extends BankCoreContainer]
  + BankContainer.build(config, alert_system) factory
  + BankContainer.build_for_testing() → FakeConfig + SpyAlertSystem
  + BankContainer.build_pipeline(validate, log, rate_limit, apply_fees)
  + BankContainer.transaction_service property (lazy, injected)

refactor(transactions): TransactionService accepts injected dependencies

- src/bankcore/transaction_service.py
  ~ __init__(self, config=None, alert_system=None, event_builder=None)
  ~ Falls back to Singletons when None (backward compatible)

refactor(config): AccountConfigResolver accepts injected config

- src/bankcore/account_config.py
  ~ __init__(self, config=None) — DIP injection, falls back to Singleton

test(dip): add 32 tests for DIP

- tests/test_dip.py
  + TestProtocolSatisfaction (11 tests)
  + TestTransactionServiceDIP (7 tests)
  + TestAccountConfigResolverDIP (3 tests)
  + TestBankContainer (8 tests)
  + TestFullIsolation (3 tests — zero Singleton access)

docs(dip): add README for Jour 10

- docs/jour-10/README.md
```

---

## Jour 11 — Architecture en Couches

```
feat(application): add Commands as input DTOs

- src/bankcore/application/__init__.py [NEW]
- src/bankcore/application/commands.py [NEW]
  + TransferCommand, DepositCommand, WithdrawCommand (frozen dataclasses)
  + CreateAccountCommand, ApplyInterestCommand
  + UseCaseResult with ok() and fail() class methods

feat(application): add Use Cases and BankApplicationService

- src/bankcore/application/use_cases.py [NEW]
  + AccountRegistry (in-memory store, DI-ready)
  + TransferUseCase, DepositUseCase, WithdrawUseCase
  + CreateAccountUseCase (publishes account.created event)
  + ApplyInterestUseCase (uses InterestBearing — ISP J09)
  + BankApplicationService facade over all use cases

test(layers): add 42 tests for layered architecture

- tests/test_layered_architecture.py
  + TestCommands (10 tests)
  + TestUseCaseResult (5 tests)
  + TestCreateAccountUseCase (5 tests)
  + TestDepositUseCase (3 tests)
  + TestWithdrawUseCase (4 tests)
  + TestTransferUseCase (5 tests)
  + TestApplyInterestUseCase (4 tests)
  + TestBankApplicationServiceIntegration (4 tests — incl. layer isolation)

docs(layers): add README for Jour 11

- docs/jour-11/README.md
```

---

## Jour 12 — Clean Architecture

```
feat(domain): add Money and AccountId value objects

- src/bankcore/domain/__init__.py [NEW]
- src/bankcore/domain/value_objects.py [NEW]
  + Money(frozen): +, -, *, comparison, currency validation
  + Money.zero(), Money.eur() factories
  + AccountId(frozen): normalized uppercase, equality with str

feat(domain): add Domain Events (pure, no infrastructure imports)

- src/bankcore/domain/domain_events.py [NEW]
  + DomainEvent(frozen) base with aggregate_id, event_id, occurred_at
  + AccountOpened, MoneyDeposited, MoneyWithdrawn
  + MoneyTransferred, InterestApplied, FeeCharged

feat(application): add Application Ports

- src/bankcore/application/ports.py [NEW]
  + AccountRepositoryPort(ABC): save, find_by_id, find_all, find_by_owner
  + NotificationPort(ABC): notify(event)
  + DomainEventStorePort(ABC): append, get_events_for

feat(infrastructure): add InMemoryAccountRepository and EventStore

- src/bankcore/infrastructure/__init__.py [NEW]
- src/bankcore/infrastructure/persistence/__init__.py [NEW]
- src/bankcore/infrastructure/persistence/in_memory_repository.py [NEW]
  + InMemoryAccountRepository implements AccountRepositoryPort
  + InMemoryDomainEventStore implements DomainEventStorePort

refactor(application): AccountRegistry implements AccountRepositoryPort

- src/bankcore/application/use_cases.py
  ~ AccountRegistry now extends AccountRepositoryPort
  ~ Use Case __init__ types updated to AccountRepositoryPort
  ~ BankApplicationService accepts AccountRepositoryPort

fix(application): use `registry is not None` instead of truthiness check

- src/bankcore/application/use_cases.py
  ~ `registry or AccountRegistry()` → `registry if registry is not None else AccountRegistry()`
  ! Bug: empty InMemoryAccountRepository was falsy, causing new AccountRegistry to be created

test(clean): add 54 tests for Clean Architecture

- tests/test_clean_architecture.py
  + TestMoney (18 tests)
  + TestAccountId (7 tests)
  + TestDomainEvents (8 tests)
  + TestAccountRepositoryPort (9 tests)
  + TestInMemoryDomainEventStore (4 tests)
  + TestUseCasesWithCleanArchitectureRepo (3 tests)
  + TestCleanArchitectureLayerIsolation (4 tests)

docs(clean): add README for Jour 12

- docs/jour-12/README.md
```

---

## Jour 13 — Modélisation Base de Données

```
feat(schema): add SQLite schema with 5 tables and business constraints

- src/bankcore/infrastructure/persistence/schema.py [NEW]
  + SCHEMA_SQL: DDL with owner, account, transaction, transfer, fee_record
  + CHECK constraints: account_type IN (...), balance >= min_possible_balance
  + CHECK on transaction: amount != 0, direction matches tx_type
  + 6 strategic indexes (idx_tx_account_id, idx_tx_account_time, etc.)
  + create_schema(conn), get_connection(path), schema_connection() context manager
  + SchemaInspector: tables(), columns(), indexes(), foreign_keys()

feat(persistence): add SQLiteAccountRepository

- src/bankcore/infrastructure/persistence/sqlite_repository.py [NEW]
  + SQLiteAccountRepository implements AccountRepositoryPort
  + save(): INSERT OR REPLACE with transaction sync
  + find_by_id(), find_all(), find_by_owner(), count(), exists()
  + _sync_transactions(): idempotent, inserts only new transaction records
  + _infer_tx_type(): maps description+amount to tx_type enum
  + _reconstruct(): rebuilds Account domain object from database row
  + get_transaction_history(): newest first
  + get_account_summary(): JOIN with owner + aggregates

test(schema): add 37 tests for database schema

- tests/test_database_schema.py
  + TestSchemaStructure (7 tests — all tables + columns)
  + TestSchemaIndexes (4 tests)
  + TestForeignKeyConstraints (3 tests)
  + TestCheckConstraints (6 tests — business rules at DB level)
  + TestSQLiteAccountRepository (10 tests)
  + TestReportingQueries (3 tests)
  + TestCleanArchitectureSwap (2 tests — incl. file persistence)
  + TestSchemaIdempotency (2 tests)

fix(schema): quote reserved word 'transaction' in PRAGMA table_info

- src/bankcore/infrastructure/persistence/schema.py
  ~ f"PRAGMA table_info({table})" → f'PRAGMA table_info("{table}")'
  ~ f"PRAGMA foreign_key_list({table})" → f'PRAGMA foreign_key_list("{table}")'

docs(schema): add README for Jour 13

- docs/jour-13/README.md
```

---

## Jour 14 — Repository Pattern

```
feat(specifications): add Specification Pattern for account queries

- src/bankcore/application/specifications.py [NEW]
  + AccountSpec(ABC) with &, |, ~ operators
  + AndSpec, OrSpec, NotSpec, AllSpec (composites)
  + OwnerSpec, TypeSpec, BalanceSpec (concrete)
  + InterestEligibleSpec (uses InterestBearing — ISP J09)
  + OverdraftSpec, LowBalanceSpec
  + Page frozen dataclass: items, total, page, page_size
  + Page.has_next, has_prev, total_pages properties

feat(uow): add Unit of Work pattern

- src/bankcore/application/unit_of_work.py [NEW]
  + UnitOfWork with identity map, dirty tracking
  + commit(), rollback(), context manager (__enter__/__exit__)
  + register_new(), register_dirty(), find()
  + TransferOperation: atomic transfer within UoW

refactor(persistence): InMemoryAccountRepository gains find(spec, page, page_size)

- src/bankcore/infrastructure/persistence/in_memory_repository.py
  + find(spec, page, page_size) → Page
  + find_one(spec) → Optional[Account]
  + count_spec(spec) → int

refactor(persistence): SQLiteAccountRepository gains find(spec, page, page_size)

- src/bankcore/infrastructure/persistence/sqlite_repository.py
  + find(spec, page, page_size) → Page (in-memory filter after DB load)
  + find_one(spec), count_spec(spec)

test(repo): add 51 tests for Repository Pattern

- tests/test_repository_pattern.py
  + TestSpecifications (12 tests)
  + TestSpecificationComposition (7 tests)
  + TestPage (8 tests)
  + TestInMemoryFind (12 tests)
  + TestUnitOfWork (7 tests)
  + TestTransferOperation (4 tests)
  + TestCrossRepositoryConsistency (3 tests)

docs(repo): add README for Jour 14

- docs/jour-14/README.md
```

---

## Jour 15 — Architecture Hexagonale

```
feat(presentation): add TestDriver primary adapter

- src/bankcore/presentation/__init__.py [NEW — implied]
- src/bankcore/presentation/test_driver.py [NEW]
  + TestDriver.create() — fully isolated, no global state
  + create_account(), deposit(), withdraw(), transfer(), apply_interest()
  + balance(), account_info(), all_accounts(), account_id()
  + assert_balance(), assert_last_success(), assert_last_failure()
  + assert_account_count() — fluent, chainable

feat(presentation): add InterestScheduler primary adapter

- src/bankcore/presentation/scheduler.py [NEW]
  + InterestScheduler.run(dry_run=False) → SchedulerReport
  + InterestScheduler.preview() → eligible accounts + total to credit
  + SchedulerReport: accounts_processed, skipped, errors, total_credited
  + Pagination via InterestEligibleSpec + Page (J14)

feat(presentation): add BankAPIHandler primary adapter

- src/bankcore/presentation/api_handler.py [NEW]
  + BankAPIHandler with HTTPResponse(status_code, body)
  + create_account() → 201, get_account() → 200/404
  + deposit() → 200/422, withdraw() → 200/422
  + transfer() → 200/404/422
  + _error_response(): maps error_code to HTTP status

test(hex): add 40 tests for Hexagonal Architecture

- tests/test_hexagonal_architecture.py
  + TestTestDriver (17 tests — incl. fluent chain, isolation)
  + TestBankAPIHandler (13 tests)
  + TestInterestScheduler (7 tests)
  + TestHexagonalIsolation (3 tests — no business logic in adapters)

fix(application): registry truthiness bug

- src/bankcore/application/use_cases.py
  ~ `registry or AccountRegistry()` → `registry if registry is not None else AccountRegistry()`

docs(hex): add README for Jour 15

- docs/jour-15/README.md
```

---

## Jour 16 — Microservices

```
feat(services): add ServiceClient and ServiceRegistry

- src/bankcore/services/shared/service_client.py [NEW]
  + ServiceRequest(method, path, body, headers, params)
  + ServiceResponse(status_code, body, latency_ms) with ok property
  + ServiceClient: get(), post(), patch(), delete()
  + ServiceClient: call_count, call_log, reset_stats()
  + ServiceRegistry: register(), get(), is_registered(), total_calls()

feat(services): add AccountService microservice

- src/bankcore/services/account_service/service.py [NEW]
  + AccountService with HTTP-style router handle(request)
  + Routes: GET/POST /accounts, GET /accounts/{id}
  + PATCH /accounts/{id}/balance (called by TransactionService)
  + Includes min_possible_balance in GET response (for TX validation)
  + Owns InMemoryAccountRepository (no shared database)

feat(services): add TransactionMicroservice

- src/bankcore/services/transaction_service/service.py [NEW]
  + TransactionMicroservice(account_client) — calls AccountService via client
  + Routes: POST /transfers, /deposits, /withdrawals
  + GET /transactions, /transactions/{id}
  + TransactionLog: own data store, no shared state with AccountService
  + Rollback on partial failure (debit OK, credit FAIL → reverse debit)

test(microservices): add 40 tests for Microservices

- tests/test_microservices.py
  + TestServiceClient (7 tests)
  + TestServiceRegistry (5 tests)
  + TestAccountService (10 tests)
  + TestTransactionMicroservice (7 tests)
  + TestInterServiceCommunication (9 tests — verifies call counts)
  + TestDataIsolation (2 tests)

docs(microservices): add README for Jour 16

- docs/jour-16/README.md
```

---

## Jour 17 — Cache (Redis)

```
feat(cache): add InMemoryCache with TTL, lazy eviction, CacheStats

- src/bankcore/infrastructure/cache/__init__.py [NEW — implied]
- src/bankcore/infrastructure/cache/cache_backend.py [NEW]
  + CacheEntry(dataclass) with is_expired, ttl_remaining
  + CacheStats: hits, misses, sets, deletes, evictions, hit_rate, summary()
  + InMemoryCache(threading.Lock): get(), set(), delete(), delete_pattern()
  + clear(), size(), active_size(), ttl_remaining(key)

feat(cache): add CachingServiceClient as Decorator over ServiceClient

- src/bankcore/infrastructure/cache/caching_service_client.py [NEW]
  + CachingServiceClient wraps ServiceClient — same interface (Decorator J04)
  + GET → cache lookup (HIT: return, MISS: call + store)
  + NEVER_CACHE_PATTERNS = ["/balance"] — balance always live
  + POST/PATCH/DELETE bypass cache and invalidate related keys
  + invalidate(account_id), invalidate_all()
  + _invalidate_for_path(): prefix-based invalidation on write

test(cache): add 35 tests for Cache

- tests/test_cache.py
  + TestInMemoryCache (11 tests — incl. thread_safety)
  + TestCacheStats (7 tests)
  + TestCachingServiceClient (13 tests)
  + TestBankingCacheRules (2 tests — balance live, profile cacheable)
  + TestCachePerformance (2 tests — downstream call reduction proof)
  + TestCacheIntegration (2 tests — TransactionService + cached client)

fix(cache): balance path uses NEVER_CACHE_PATTERNS not cache stats

- tests/test_cache.py
  ~ test_balance_path_never_cached: assert hits==0 and misses==0
    (cache never consulted for NEVER_CACHE paths, not just not cached)
  ~ test_multiple_transfers_accumulate_hits → test_multiple_transfers_cache_set_and_invalidate
    (PATCH invalidates immediately, no hits in tight write loops)

docs(cache): add README for Jour 17

- docs/jour-17/README.md
```

---

## Jour 18 — Message Queue

```
feat(messaging): add MessageBus with Pub/Sub, DLQ, idempotency

- src/bankcore/infrastructure/messaging/__init__.py [NEW — implied]
- src/bankcore/infrastructure/messaging/message_bus.py [NEW]
  + Message(frozen): topic, payload, message_id, retry_count, source
  + Message.with_retry() — new instance, same ID, +1 retry_count
  + Consumer(ABC): process(), max_retries, name
  + ConsumerResult: success, consumer, error
  + DeadLetterQueue: add(), for_consumer(), count(), clear()
  + MessageBus: publish(), subscribe(), unsubscribe()
  + Pattern matching: * (one segment), # (any depth) via fnmatch
  + Retry loop with DLQ on exhaustion
  + Idempotency: (message_id, consumer) deduplication
  + async_dispatch=True for threading-based non-blocking dispatch

feat(messaging): add concrete consumers

- src/bankcore/infrastructure/messaging/consumers.py [NEW]
  + Topics constants: TRANSFER_COMPLETED, TRANSFER_FAILED, DEPOSIT_COMPLETED
    WITHDRAWAL_COMPLETED, ACCOUNT_CREATED, BALANCE_UPDATED, FRAUD_SUSPECTED, LOW_BALANCE
  + FraudDetectionConsumer: large amount + high frequency detection
  + NotificationConsumer: SMS for transfers/deposits, email for fraud
  + AnalyticsConsumer: volume by type, count by type, average amount
  + CacheInvalidationConsumer: calls CachingServiceClient.invalidate()
  + AuditConsumer: wildcard "#", idempotent, append-only log
  + BrokenConsumer: test double that always raises (DLQ testing)

test(messaging): add tests for Message Queue

- tests/test_message_queue.py [PENDING — next step]
  + TestMessage, TestMessageBus, TestDeadLetterQueue
  + TestIdempotency, concrete consumer tests
  + CacheInvalidationConsumer (J17 + J18)
  + TransactionMicroserviceWithBus integration

docs(messaging): add README for Jour 18

- docs/jour-18/README.md
```


---

## JOUR 19 — Docker & Containerisation

```
git add docker/account-service/Dockerfile docker/account-service/server.py
git add docker/account-service/entrypoint.sh docker/account-service/.dockerignore
git commit -m "feat(docker): add AccountService Dockerfile + HTTP server

- Multi-stage build: builder + python:3.12-slim runtime
- Non-root user (adduser bankcore), HEALTHCHECK /health, graceful SIGTERM
- server.py: /health + /ready probes, full JSON routing
- entrypoint.sh: SIGTERM forwarding, PID tracking"

git add docker/transaction-service/Dockerfile docker/transaction-service/server.py
git add docker/transaction-service/entrypoint.sh docker/transaction-service/.dockerignore
git commit -m "feat(docker): add TransactionService Dockerfile + HTTP server

- Real urllib HTTP handler for inter-service calls (not in-process)
- entrypoint.sh: wait loop MAX_RETRIES=30 for AccountService health
- /ready probe verifies AccountService reachability"

git add docker/docker-compose.yml docker/docker-compose.test.yml
git commit -m "feat(docker): add docker-compose.yml — 4 services, healthchecks, volumes

- depends_on: condition: service_healthy (AccountService → TransactionService)
- Redis: 256MB LRU, appendonly persistence
- RabbitMQ: management UI, bankcore vhost, AMQP :5672
- Log rotation: max-size=10m, max-file=3
- docker-compose.test.yml: test-runner waits for all services healthy"

git add tests/test_docker_config.py
git commit -m "test(docker): add 46 tests for Docker config (no daemon required)

- Dockerfile: multi-stage, non-root, HEALTHCHECK, correct ports
- docker-compose.yml: services, depends_on, healthchecks, volumes, restart
- Entrypoints: SIGTERM handling, wait loop, retry limit
- Server files: /health + /ready routes, ACCOUNT_SERVICE_URL env"

git add docs/jour-19/
git commit -m "docs(j19): add ADR for Docker containerisation"
```

---

## JOUR 20 — Monitoring & Distributed Tracing

```
git add src/bankcore/infrastructure/monitoring/__init__.py
git add src/bankcore/infrastructure/monitoring/metrics.py
git commit -m "feat(monitoring): add Counter, Gauge, Histogram + MetricsRegistry

- Thread-safe metrics with threading.Lock
- Prometheus-compatible interface (no external dep)
- BankCore defaults pre-registered: transfers_total, cache_hits_total, etc.
- snapshot() returns all metrics as JSON-serializable dict"

git add src/bankcore/infrastructure/monitoring/tracer.py
git commit -m "feat(monitoring): add distributed Tracer with SpanContext

- Trace → Span tree, parent_id auto-propagation via thread-local
- SpanContext context manager: auto-finish, captures exceptions as errors
- error_traces(): filter traces with at least one error span"

git add src/bankcore/infrastructure/monitoring/health_check.py
git commit -m "feat(monitoring): add HealthChecker with composite checks

- RepositoryHealthCheck, CacheHealthCheck, MessageBusHealthCheck, MetricsHealthCheck
- Aggregation: any error → unhealthy, any degraded → degraded, else healthy
- HealthReport.to_dict() for JSON health endpoint
- Chainable: checker.add_check('db', ...).add_check('cache', ...)"

git add tests/test_monitoring.py
git commit -m "test(monitoring): add 59 tests for metrics, tracing, health checks

- Counter thread safety: 10 threads × 100 increments = 1000 exactly
- Tracer: nested spans get parent_id automatically via thread-local
- HealthChecker: one error → unhealthy, one degraded → degraded"

git add docs/jour-20/
git commit -m "docs(j20): add ADR for Monitoring & Distributed Tracing

chore: update README.md with J01-J20 full project overview"
```

---

## JOUR 21 — Event Sourcing

```
git add src/bankcore/domain/event_sourcing/__init__.py
git add src/bankcore/domain/event_sourcing/event_store.py
git commit -m "feat(eventsourcing): add InProcessEventStore — append-only with optimistic locking

- StoredEvent: sequence_number (global), aggregate_version (per-agg), SHA-256 checksum
- ConcurrencyError: expected_version guard for concurrent writers
- verify_integrity(): per-aggregate checksum verification
- append_all(): atomic batch append"

git add src/bankcore/domain/event_sourcing/aggregate.py
git commit -m "feat(eventsourcing): add AccountAggregate + Projections

- AccountAggregate: zero persistent state, rebuilt from events via from_events()
- Commands produce events, _apply() mutates state (separated intentionally)
- AccountProjection: current state from event stream
- BalanceHistoryProjection: balance_at_version() for point-in-time queries
- fix: _apply(AccountOpened) restores interest_rate=0.025 for savings accounts"

git add tests/test_event_sourcing.py
git commit -m "test(eventsourcing): add 39 tests for Event Sourcing

- Determinism: same events always produce same balance (replayed twice)
- Optimistic locking: expected_version mismatch raises ConcurrencyError
- Full cycle: command → events → store → projection → verified balance"

git add docs/jour-21/
git commit -m "docs(j21): add ADR for Event Sourcing"
```

---

## JOUR 22 — CQRS

```
git add src/bankcore/application/cqrs/__init__.py
git add src/bankcore/application/cqrs/cqrs.py
git commit -m "feat(cqrs): implement CQRS — separate write path and read path

Write side:
- 5 Commands: OpenAccount, Deposit, Withdraw, Transfer, ApplyInterest
- AccountCommandHandler: load aggregate → apply command → append events
- ProjectionUpdater: event → read model (synchronous for Day 22)

Read side:
- 4 Queries: GetBalance, GetAccountSummary, ListAccounts, GetTransactionHistory
- ReadModelStore: in-memory projection cache
- AccountQueryHandler: reads ONLY from ReadModels, never EventStore

CQRSFacade: single entry point — handle_command() or handle_query()

fix: _apply(AccountOpened) restores interest_rate by account_type
     (same fix needed in both EventSourcing J21 and CQRS J22)"

git add tests/test_cqrs.py
git commit -m "test(cqrs): add 29 tests for CQRS

- Structural proof: QueryHandler has no _event_store attribute
- Full flow: commands → EventStore → projections → queries
- Pagination: ListAccountsQuery with page/page_size"

git add docs/jour-22/
git commit -m "docs(j22): add ADR for CQRS"
```

---

## JOUR 23 — Saga Pattern

```
git add src/bankcore/application/saga/__init__.py
git add src/bankcore/application/saga/saga.py
git commit -m "feat(saga): add SagaOrchestrator + InternationalTransferSaga

SagaOrchestrator:
- State machine: PENDING→RUNNING→COMPLETED/COMPENSATING→COMPENSATED/FAILED
- Forward pass: steps in order; backward pass: compensate in reverse
- Only EXECUTED steps are compensated (not steps never reached)
- Full execution log: every state transition timestamped

InternationalTransferSaga steps:
- DebitSourceStep: compensate() restores exact pre-debit balance
- ConvertCurrencyStep: compensate() is no-op (no money moved)
- CreditDestinationStep: compensate() reverses credit
- NotifyStep: transfer_completed or transfer_cancelled"

git add tests/test_saga.py
git commit -m "test(saga): add 35 tests for Saga Pattern

- Compensation restores Alice balance on GHOST destination failure
- FX failure: debit compensated, destination never touched
- Compensation order strictly reversed (verified via ordered list)
- NotifyStep not reached when CreditDestination fails (correct)"

git add docs/jour-23/
git commit -m "docs(j23): add ADR for Saga Pattern"
```

---

## JOUR 24 — Circuit Breaker

```
git add src/bankcore/infrastructure/resilience/__init__.py
git add src/bankcore/infrastructure/resilience/circuit_breaker.py
git commit -m "feat(resilience): add Circuit Breaker with CLOSED/OPEN/HALF_OPEN states

CircuitBreaker:
- Thread-safe state machine with threading.Lock
- CLOSED→OPEN after failure_threshold consecutive failures
- OPEN→HALF_OPEN after recovery_timeout (lazy check in _get_state)
- HALF_OPEN→CLOSED after success_threshold probes succeed
- HALF_OPEN→OPEN if probe fails (reset recovery timer)
- Optional fallback callable when circuit is OPEN
- call_safe() returns default instead of raising CircuitOpenError

CircuitBreakerClient:
- Wraps ServiceClient (J16) — same interface, drop-in
- Catches ALL exceptions → ServiceResponse(503) (never propagates)
- Ensures TransactionMicroservice always gets a ServiceResponse"

git add tests/test_circuit_breaker.py
git commit -m "test(circuit): add 29 tests for Circuit Breaker

- test_transfer_fails_fast_when_circuit_open: elapsed < 50ms after trip
- No downstream call when circuit OPEN (call_count unchanged)
- Manual reset via breaker.reset() closes circuit immediately"

git add docs/jour-24/
git commit -m "docs(j24): add ADR for Circuit Breaker"
```

---

## JOUR 25 — Bulkhead + Retry

```
git add src/bankcore/infrastructure/resilience/bulkhead_retry.py
git commit -m "feat(resilience): add Bulkhead + RetryPolicy + BulkheadRetryClient

Bulkhead:
- threading.Semaphore for concurrent call limiting
- call() and context manager (__enter__/__exit__)
- Slot released in finally block (exception-safe)
- BulkheadStats: accepted, rejected, peak_concurrent

RetryPolicy:
- Exponential backoff: min(base_delay * 2^attempt, max_delay)
- Jitter: random(0, wait * jitter_factor) — prevents thundering herd
- retryable=(Exception,): per-type retry filtering
- on_retry callback for logging
- execute() never raises — returns RetryResult with all attempts logged

BulkheadRetryClient:
- Wraps ServiceClient (J16): Bulkhead → Retry → call
- 429 on BulkheadFullError, 503 on retry exhaustion
- retry_stats(): total_calls, retried count, avg_attempts"

git add tests/test_bulkhead_retry.py
git commit -m "test(resilience): add 33 tests for Bulkhead + Retry

- test_transfer_retries_on_transient_service_failure: 2 failures then success
- compute_wait: exponential growth capped by max_delay verified
- non_retryable_exception_fails_immediately: 1 attempt only"

git add docs/jour-25/
git commit -m "docs(j25): add ADR for Bulkhead + Retry Pattern"
```

---

## JOUR 26 — Audit Log Immuable

```
git add src/bankcore/infrastructure/audit/__init__.py
git add src/bankcore/infrastructure/audit/audit_log.py
git commit -m "feat(audit): add ImmutableAuditLog with HMAC-SHA256 + cryptographic chaining

AuditEntry (frozen=True):
- entry_hash: SHA-256 of canonical JSON content
- prev_hash: SHA-256 of previous entry (GENESIS for first)
- signature: HMAC-SHA256(secret_key, entry_hash)
- sequence: global ordering

ImmutableAuditLog:
- Thread-safe append via threading.Lock
- verify_entry(): HMAC verification with timing-safe compare_digest
- verify_chain(): full chain validation (prev_hash + signature)
- ChainVerificationResult: is_valid, violations list, head_hash"

git add tests/test_audit_log.py
git commit -m "test(audit): add 32 tests for Immutable Audit Log

- Tampered signature detected via wrong key verification
- Injected bad entry breaks chain at exact sequence number
- Concurrent appends: 20 threads, all unique sequences, chain intact"

git add docs/jour-26/
git commit -m "docs(j26): add ADR for Immutable Audit Log"
```

---

## JOUR 27 — RBAC

```
git add src/bankcore/application/rbac/__init__.py
git add src/bankcore/application/rbac/rbac.py
git commit -m "feat(rbac): add Role-Based Access Control

Roles & Permissions:
- Teller: VIEW_ACCOUNT, DEPOSIT, WITHDRAW
- Manager: Teller + TRANSFER, CLOSE_ACCOUNT, VIEW_REPORTS
- Admin: Manager + CREATE_ACCOUNT, MANAGE_USERS, CONFIGURE
- System: all permissions (internal service calls)

Principal (frozen=True): user_id, username, role, per-operation limits
AuthorizationService: authorize() raises AuthorizationError or LimitExceededError
@requires_permission: decorator for Use Case methods
SecuredBankApplicationService: wraps BankApplicationService with RBAC
factory functions: teller(), manager(), admin(), system_principal()
Integration with ImmutableAuditLog (J26): every decision logged"

git add tests/test_rbac.py
git commit -m "test(rbac): add 32 tests for RBAC

- Role hierarchy: Teller ⊂ Manager ⊂ Admin (issubset verified)
- Teller cannot transfer → AuthorizationError raised
- Manager transfer above limit → LimitExceededError raised
- system_principal() bypasses all restrictions
- Authz decisions logged with GRANTED/DENIED event types"

git add docs/jour-27/
git commit -m "docs(j27): add ADR for RBAC"
```

---

## JOUR 28 — Secrets Management

```
git add src/bankcore/infrastructure/secrets/__init__.py
git add src/bankcore/infrastructure/secrets/secrets_provider.py
git commit -m "feat(secrets): add SecretsProvider Protocol + 3 implementations

SecretsProvider (ABC):
- get(key) → raises SecretNotFoundError (never returns None)
- exists(key) → bool
- get_or_default(key, default) → str

InMemorySecretsProvider (tests):
- Access log records keys only — never values
- set() and delete() for test setup/teardown

EnvSecretsProvider (production):
- Key mapping: bankcore.audit.hmac_key → BANKCORE_AUDIT_HMAC_KEY
- Optional prefix: EnvSecretsProvider(prefix='APP')

RotatingSecretsProvider (key rotation):
- Versioned secrets: add_version() returns version number
- get() returns latest active version
- get_version(key, n) for verifying old signatures
- deactivate_version() after rotation completes
- list_versions() returns metadata WITHOUT values

SecretsAwareMixin: create_audit_log(provider) factory
SecretKeys: centralized constants — no magic strings"

git add tests/test_secrets.py
git commit -m "test(secrets): add 39 tests for Secrets Management

- Access log never contains secret values (only keys)
- Cross-verification: log1.verify_entry(e2) is False (different keys)
- Rotation workflow: v1 deactivated, v2 active, v1 still readable by version
- Provider swap is transparent: same code, different SecretsProvider"

git add docs/jour-28/
git commit -m "docs(j28): add ADR for Secrets Management"
```

---

## JOUR 29 — Architecture Decision Records

```
git add docs/adr/ADR-001-stdlib-only.md
git commit -m "docs(adr): ADR-001 — Python stdlib uniquement

Context: frameworks masquent les patterns qu'on veut démontrer
Decision: stdlib + pytest + pyyaml uniquement
Consequence: patterns universels, 0 breaking change, 1050+ tests"

git add docs/adr/ADR-002-backward-compatibility.md
git commit -m "docs(adr): ADR-002 — Rétrocompatibilité à chaque jour

Decision: tests J01 passent encore à J30 sans modification
Key example: TransactionService(config=None) rétrocompatible avec J03"

git add docs/adr/ADR-003-to-010.md
git commit -m "docs(adr): ADR-003 à ADR-010 — 8 décisions architecturales

ADR-003: Protocol vs ABC pour DIP (duck typing structurel)
ADR-004: Port dans Application, Adapter dans Infrastructure
ADR-005: UUID TEXT vs INTEGER pour PKs SQLite
ADR-006: Orchestration vs Choreography pour Saga
ADR-007: id(consumer) vs consumer.name — bug de collision corrigé
ADR-008: CircuitBreakerClient catch-all vs re-raise
ADR-009: interest_rate non persisté — dette technique documentée
ADR-010: Séparation ConfigManager / SecretsProvider"

git add docs/adr/README.md
git commit -m "docs(adr): add ADR index — 10 decisions, format standard

Note: les ADR documentent le POURQUOI, pas le QUOI (c'est le code)"
```

---

## JOUR 30 — C4 + Rétrospective + Manifeste

```
git add docs/jour-30/README.md
git commit -m "docs(j30): add C4 diagrams Level 1/2/3 + final retrospective

C4 Level 1: Contexte système (clients, services externes)
C4 Level 2: Conteneurs (AccountService, TransactionService, Redis, RabbitMQ)
C4 Level 3: Composants AccountService (BankAPIHandler → RBAC → UseCases → Domain)

Retrospective:
- What would NOT pass production as-is (SQLite, InMemoryCache, etc.)
- What IS production-ready (architecture, tests, resilience, security)
- The architectural lesson: rules before complexity, not after"

git add docs/MANIFESTE.md
git commit -m "docs: add MANIFESTE.md — pourquoi le code n'est jamais optimal au début

Texte sur la nature des projets logiciels:
- La complexité est emergente, pas initiale
- L'architecte crée les conditions, pas le code parfait
- La formation ne s'arrête pas à la connaissance des patterns
- Ce qu'exige un projet du début jusqu'à la fin
- Une règle appliquée systématiquement > 100 règles oubliées"

git add README.md
git commit -m "chore: update final README.md

30 jours · 64 fichiers · 28 fichiers tests · 10 ADR
1 050 tests · 23 602 lignes · 0 réécriture complète
2 dépendances externes: pytest, pyyaml"
```

---

## Résumé final par semaine

| Semaine | Jours | Fichiers ajoutés | Tests ajoutés | Total tests |
|---------|-------|-----------------|---------------|-------------|
| 1 — Patterns GoF | J01-J05 | 10 | 155 | 155 |
| 2 — SOLID | J06-J10 | 9 | 185 | 340 |
| 3 — Architecture | J11-J15 | 11 | 224 | 564 |
| 4 — Scalabilité | J16-J20 | 12 | 253 | 817 |
| 5 — Patterns avancés | J21-J28 | 18 | 233 | 1 050 |
| Documentation | J29-J30 | 5 docs | — | — |
| **TOTAL** | **30 jours** | **64 source + 28 tests** | **1 050** | **1 050** |

---

## Fichiers supprimés au cours du projet

**Aucun.** BankCore est additif par conception.
Chaque jour ajoute ou refactorise — jamais ne supprime.
C'est une contrainte architecturale délibérée : le code du J01 existe encore au J30.
