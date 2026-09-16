# Jour 29 — Architecture Decision Records

## Le problème concret

Le code dit *quoi*. Il ne dit jamais *pourquoi*.

```python
# Pourquoi id(consumer) et pas consumer.name ici ?
idempotency_key = f"{current.message_id}:{id(consumer)}"
```

**Ce qui arrive sans ADR :**
Un nouveau développeur trouve ça "bizarre", le remplace par
`consumer.name` (plus lisible), et casse silencieusement la
désduplication dès que deux instances du même type de consommateur
sont abonnées au même topic. Personne ne comprend pourquoi la prod
traite certains messages deux fois — la décision originale n'était
écrite nulle part.

Un ADR (Architecture Decision Record) documente la décision, son
contexte, et ce qu'on a rejeté et pourquoi — pour que la prochaine
personne (souvent soi-même, six mois plus tard) n'ait pas à
redécouvrir le problème par un incident.

---

## Les 10 ADR de BankCore

| ADR | Titre | Jour | Statut |
|-----|-------|------|--------|
| [ADR-001](../adr/ADR-001-stdlib-only.md) | Python stdlib uniquement | J01 | ✅ Accepté |
| [ADR-002](../adr/ADR-002-backward-compatibility.md) | Rétrocompatibilité à chaque jour | J01 | ✅ Accepté |
| [ADR-003](../adr/ADR-003-to-010.md#adr-003) | Protocol vs ABC pour le DIP | J10 | ✅ Accepté |
| [ADR-004](../adr/ADR-003-to-010.md#adr-004) | Port dans Application, Adapter dans Infrastructure | J12 | ✅ Accepté |
| [ADR-005](../adr/ADR-003-to-010.md#adr-005) | UUID TEXT vs INTEGER pour les PKs SQLite | J13 | ✅ Accepté |
| [ADR-006](../adr/ADR-003-to-010.md#adr-006) | Orchestration vs Choreography pour la Saga | J23 | ✅ Accepté |
| [ADR-007](../adr/ADR-003-to-010.md#adr-007) | id(consumer) vs consumer.name pour MessageBus | J18 | ✅ Accepté |
| [ADR-008](../adr/ADR-003-to-010.md#adr-008) | CircuitBreakerClient catch-all vs re-raise | J24 | ✅ Accepté |
| [ADR-009](../adr/ADR-003-to-010.md#adr-009) | interest_rate non persisté comme événement | J21 | ⚠️ Dette technique |
| [ADR-010](../adr/ADR-003-to-010.md#adr-010) | Séparation ConfigManager / SecretsProvider | J28 | ✅ Accepté |

Index complet, format standard (Contexte / Décision / Conséquences /
Alternatives rejetées / Validation) : [`docs/adr/`](../adr/).

---

## Deux ADR qui montrent ce que le format apporte

**ADR-002 (rétrocompatibilité)** fixe une règle simple et vérifiable :
les tests d'un jour ne sont jamais modifiés pour accommoder un jour
suivant, sauf correction de bug. Conséquence directe et mesurable :
`pytest tests/` passe sans régression depuis J01 jusqu'à J29.

**ADR-009 est différent des neuf autres : c'est une dette technique
assumée, pas une décision "propre".** `AccountAggregate.apply_interest()`
a besoin de `_interest_rate`, mais l'événement `AccountOpened` ne le
transporte pas — la reconstruction depuis l'historique d'événements le
réinfère du `account_type` plutôt que de le stocker explicitement.
Ça fonctionne tant que le taux ne change jamais après ouverture du
compte, ce qui est faux en pratique. L'ADR documente le correctif à
apporter (un événement `InterestRateSet` explicite) au lieu de prétendre
que le problème n'existe pas.

---

## Connexion avec les jours précédents

- **Chaque ADR référence le jour où la décision a été prise** — les ADR
  ne sont pas rédigés a posteriori, ils accompagnent le code depuis J01
- **J30 (C4 + Rétrospective)** : les diagrammes C4 documentent la
  structure ; les ADR documentent pourquoi cette structure a été choisie
  plutôt qu'une autre — les deux sont nécessaires, aucun ne remplace l'autre

---

## Complexité aujourd'hui

- 4 fichiers : `ADR-001` à `ADR-010`, répartis en 3 fichiers Markdown
  plus un index (`docs/adr/README.md`)
- Aucun test : un ADR documente une décision, pas un comportement —
  sa "validation" est la ligne `## Validation` de chaque ADR, vérifiée
  manuellement, pas par pytest
