# ADR-001 — Python stdlib uniquement (pas de frameworks tiers)

**Statut :** Accepté  
**Date :** 2026-02-01  
**Décideur :** Architecte principal

---

## Contexte

BankCore est un projet de démonstration architecturale. Le choix des
bibliothèques externes impacte directement ce que le projet démontre :
- Avec SQLAlchemy : on démontre SQLAlchemy, pas le Repository Pattern
- Avec FastAPI : on démontre FastAPI, pas l'Architecture Hexagonale
- Avec Pydantic : on démontre Pydantic, pas les Value Objects du Domaine

---

## Décision

**Utiliser exclusivement la bibliothèque standard Python (stdlib).**

Seules exceptions autorisées :
- `pytest` : framework de test (outil de vérification, pas d'architecture)
- `pyyaml` : parsing du docker-compose.yml dans les tests

---

## Conséquences

### Positives
- Le code démontre la compréhension profonde des patterns, pas la connaissance de frameworks
- Zero dépendance à gérer sur 30 jours (pas de breaking changes, pas de conflits)
- Chaque composant est construit from scratch → compréhension totale
- Les patterns sont universels : les mêmes concepts s'appliquent en Java, Go, TypeScript

### Négatives
- Plus de code à écrire (ex: `SchemaInspector` plutôt que SQLAlchemy inspect)
- Performance non optimisée (ex: `InProcessMessageBus` plutôt que Kafka)
- Certaines fonctionnalités (async, streaming) nécessiteraient asyncio à fond

### Alternatives rejetées

| Alternative | Raison du rejet |
|-------------|-----------------|
| SQLAlchemy | Masque le Repository Pattern et la conception du schéma |
| FastAPI + Pydantic | Masque l'Architecture Hexagonale et les Value Objects |
| Celery | Masque le Message Queue Pattern |
| pytest-asyncio | Complexité non nécessaire pour les démonstrations ciblées |

---

## Validation

**J01-J29 :** 1000+ tests, 0 dépendance externe autre que pytest/pyyaml.
Le projet démontre que des patterns de niveau enterprise sont implémentables
sans framework — et qu'un architecte doit comprendre les patterns
indépendamment des outils qui les implémentent.
