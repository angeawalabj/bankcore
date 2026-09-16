# Jour 17 — Gestion de Cache (Redis)

## Le problème concret

`TransactionService` appelle `AccountService.get_account()` deux fois
par virement (une fois pour la source, une fois pour la destination).
Sous charge soutenue, ces lectures dominent le trafic.

```
Profil de charge : 1 000 virements/seconde
  → 2 000 GET /accounts/... par seconde vers AccountService
  → 99% de ces reads portent sur les mêmes 1 000 comptes actifs
  → La BDD AccountService est sollicitée pour rien
```

---

## Qu'est-ce qu'on cache et pourquoi

**Candidats au cache :**

| Donnée | TTL suggéré | Raison |
|--------|-------------|--------|
| `get_account(id)` — profil | 60s | Change rarement (nom, type) |
| `get_account(id)` — solde | NON | Mute à chaque transaction |
| `list_accounts()` | 30s | Dashboard, peu critique |
| `get_transaction(id)` | ∞ | Immuable après création |

**Décision clé :** on cache le profil (owner_name, account_type, min_possible_balance)
mais PAS le solde. Le solde est lu directement en BDD à chaque virement.
Un solde périmé causerait des découverts silencieux — inacceptable en banque.

---

## Architecture du cache

```
TransactionService
    │
    ▼
ServiceClient → GET /accounts/{id}
    │
    ▼
CachingServiceClient  ← Day 17 Decorator pattern (J04)
    │
    ├── Cache HIT → retourne la réponse cachée
    │
    └── Cache MISS → appelle AccountService, met en cache, retourne
                            │
                            ▼
                      AccountService
```

Le `CachingServiceClient` est un **Decorator** (J04) autour de `ServiceClient`.
`TransactionService` ne sait pas qu'un cache existe.

---

## Invalidation du cache

La règle la plus difficile du cache : **quand invalider ?**

```
AccountService reçoit PATCH /accounts/{id}/balance
    → invalide le cache pour account_id
    → (le solde n'est pas caché de toute façon)

AccountService reçoit POST /accounts (création)
    → invalide list_accounts cache

AccountService reçoit PATCH /accounts/{id} (mise à jour du profil)
    → invalide get_account/{id} cache
```

**Stratégie TTL :** même sans invalidation explicite, le TTL garantit
la cohérence éventuelle. Pour un profil (nom, type) : 60s est acceptable.

---

## CacheBackend — abstraction du moteur de cache

```python
class CacheBackend(Protocol):
    def get(self, key: str) -> Optional[Any]: ...
    def set(self, key: str, value: Any, ttl_seconds: int) -> None: ...
    def delete(self, key: str) -> None: ...
    def clear(self) -> None: ...
```

Implémentation livrée :
- `InMemoryCache` — seule implémentation réelle du projet (J17)

`RedisCache` n'existe pas dans ce dépôt : ADR-001 exclut les dépendances
tierces de l'application elle-même (`redis-py` en ferait partie). Le
`CacheBackend` Protocol est conçu pour qu'on puisse écrire ce backend sans
toucher au `CachingServiceClient` (DIP, J10) — c'est le point du pattern —
mais l'écrire reste un exercice, pas une livraison de ce challenge. Le
container `redis` du docker-compose (J19) tourne à côté à titre d'exemple
de topologie ; l'application ne s'y connecte pas.

---

## Métriques du cache

Un cache sans métriques est un cache aveugle.
`CacheStats` capture :
- Hit rate : % de requêtes servies depuis le cache
- Miss rate : % de requêtes ayant dû appeler le service
- Saved calls : nombre d'appels réseau évités
- Avg TTL remaining : durée de vie moyenne des entrées

---

## Connexion avec les jours précédents et suivants

- **J04 (Decorator)** : `CachingServiceClient` est un Decorator de `ServiceClient`
- **J10 (DIP)** : `CacheBackend` est un Protocol — injectable
- **J16 (Microservices)** : branché sur `TransactionService` → `AccountService`
- **J18 (Message Queue)** : les events de modification invalident le cache

---

## Complexité aujourd'hui

- 3 nouveaux fichiers : `cache/cache_backend.py`,
  `cache/caching_service_client.py`, `cache/cache_stats.py`
- `TransactionMicroservice` mis à jour pour utiliser `CachingServiceClient`
- 604 tests existants : **tous verts sans modification**
- Nouveaux tests : `test_cache.py`
