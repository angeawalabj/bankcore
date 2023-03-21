# Architecture Decision Records — BankCore

10 décisions architecturales clés documentées au format standard.

| ADR | Titre | Jour | Statut |
|-----|-------|------|--------|
| [ADR-001](ADR-001-stdlib-only.md) | Python stdlib uniquement | J01 | ✅ Accepté |
| [ADR-002](ADR-002-backward-compatibility.md) | Rétrocompatibilité à chaque jour | J01 | ✅ Accepté |
| [ADR-003](ADR-003-to-010.md#adr-003) | Protocol vs ABC pour le DIP | J10 | ✅ Accepté |
| [ADR-004](ADR-003-to-010.md#adr-004) | Port dans Application, Adapter dans Infrastructure | J12 | ✅ Accepté |
| [ADR-005](ADR-003-to-010.md#adr-005) | UUID TEXT vs INTEGER pour les PKs SQLite | J13 | ✅ Accepté |
| [ADR-006](ADR-003-to-010.md#adr-006) | Orchestration vs Choreography pour la Saga | J23 | ✅ Accepté |
| [ADR-007](ADR-003-to-010.md#adr-007) | id(consumer) vs consumer.name pour MessageBus | J18 | ✅ Accepté |
| [ADR-008](ADR-003-to-010.md#adr-008) | CircuitBreakerClient catch-all vs re-raise | J24 | ✅ Accepté |
| [ADR-009](ADR-003-to-010.md#adr-009) | interest_rate non persisté comme événement | J21 | ⚠️ Dette technique |
| [ADR-010](ADR-003-to-010.md#adr-010) | Séparation ConfigManager / SecretsProvider | J28 | ✅ Accepté |

---

## Format des ADR

Chaque ADR suit le format :

```
# ADR-NNN — Titre

Statut : Proposé | Accepté | Rejeté | Remplacé par ADR-NNN
Date : YYYY-MM-DD
Décideur : Rôle

## Contexte
Quelle situation a nécessité cette décision ?

## Décision
Qu'a-t-on décidé de faire ?

## Conséquences
### Positives
### Négatives
### Alternatives rejetées

## Validation
Comment vérifie-t-on que la décision est respectée ?
```

---

## Pourquoi documenter les ADR

Un ADR est un artefact de la pensée d'architecte, pas du code.

**Sans ADR :**
- Un nouveau développeur trouve du code "bizarre" et le "corrige"
- La "correction" casse une contrainte architecturale non documentée
- L'équipe passe 3 jours à comprendre pourquoi ça ne fonctionne plus

**Avec ADR :**
- ADR-007 explique pourquoi `id(consumer)` est utilisé plutôt que `consumer.name`
- Le développeur lit l'ADR avant de "corriger"
- La décision tient dans le temps

Les ADR ne documentent pas le "quoi" (c'est le code).
Ils documentent le "pourquoi" (c'est la pensée d'architecte).
