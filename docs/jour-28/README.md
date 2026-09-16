# Jour 28 — Secrets Management

## Le problème concret

`ConfigManager` (J01) lit une config non sensible : ports, timeouts,
feature flags. Mais l'Audit Log (J26) a besoin d'une clé HMAC, la base
de données a un mot de passe, RabbitMQ a des identifiants — mélanger ça
dans le même fichier de config est comment finissent les clés API dans
les logs, les process lists, et les images Docker versionnées sur Git.

**La question qu'un pentest va poser :**
> "Cette clé HMAC de l'audit log — où est-elle stockée, et peut-elle
> fuiter dans un `git log` ou un `docker inspect` ?"

`SecretsProvider` répond en isolant l'accès aux secrets derrière une
interface typée, jamais loggée.

---

## SecretsProvider — une interface, trois implémentations

```python
class SecretsProvider(ABC):
    def get(self, key: str) -> str: ...       # lève SecretNotFoundError si absent
    def exists(self, key: str) -> bool: ...
    def get_or_default(self, key, default) -> str: ...
```

- **`InMemorySecretsProvider`** — dict en mémoire, pour les tests
  (zéro dépendance à l'environnement, et journalise chaque accès —
  sans jamais journaliser la *valeur* — pour vérifier qu'un secret
  a bien été lu et pas juste chargé "au cas où")
- **`EnvSecretsProvider`** — lit les variables d'environnement
  (`bankcore.audit.hmac_key` → `BANKCORE_AUDIT_HMAC_KEY`) ; c'est le
  mécanisme de livraison réel en production (J19 : Docker/K8s injectent
  ces variables via secret volumes, jamais en dur dans l'image)
- **`RotatingSecretsProvider`** — versionne les secrets pour permettre
  une rotation sans interruption de service

---

## Rotation sans interruption

```
1. add_version(key, nouvelle_valeur)     → v1 et v2 actives en même temps
2. Les clients migrent progressivement vers v2
3. deactivate_version(key, 1)            → v1 retirée
```

Pourquoi ça compte pour l'Audit Log (J26) : une entrée signée avec la
clé v1 doit rester vérifiable même après la rotation vers v2. Sans
versionnage, faire tourner une clé casserait la vérifiabilité de tout
l'historique signé avant la rotation. `get_version(key, 1)` reste
disponible précisément pour ça.

---

## SecretKeys — un registre central

```python
SecretKeys.AUDIT_HMAC_KEY   # "bankcore.audit.hmac_key"
SecretKeys.DATABASE_PASSWORD
SecretKeys.JWT_SIGNING_KEY
```

Une constante plutôt qu'une chaîne libre à chaque appel : une faute de
frappe dans `"bankcore.audit.hmac_key"` échoue silencieusement (le
secret n'est jamais trouvé) ; une faute de frappe dans `SecretKeys.AUDIT_HMAC_KEY`
est une `AttributeError` à l'exécution, détectée immédiatement.

---

## Connexion avec les jours précédents

- **J01 (ConfigManager)** : gère le non-sensible ; `SecretsProvider`
  prend le relais pour tout le reste — deux responsabilités, pas une
- **J10 (DIP)** : `SecretsProvider` est injectable — un test n'a jamais
  besoin d'une vraie variable d'environnement
- **J19 (Docker)** : `EnvSecretsProvider` est le pont naturel vers les
  secrets injectés par l'orchestrateur (secret volumes, sealed secrets)
- **J26 (Audit Log)** : `SecretsAwareMixin.create_audit_log()` construit
  l'`ImmutableAuditLog` avec la clé HMAC fournie par le provider, avec
  un repli explicite (`bankcore-default-dev-key-not-for-production`)
  pour ne jamais bloquer les tests sur un secret absent

---

## Complexité aujourd'hui

- 1 nouveau fichier : `infrastructure/secrets/secrets_provider.py`
- 39 tests (`test_secrets.py`) : les trois providers, rotation,
  `SecretKeys`, intégration avec l'Audit Log
