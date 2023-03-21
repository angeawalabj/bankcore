# ADR-002 — Rétrocompatibilité à chaque Jour

**Statut :** Accepté  
**Date :** 2026-02-01  
**Décideur :** Architecte principal

---

## Contexte

Chaque jour de BankCore introduit un nouveau concept architectural.
Le risque : chaque jour casse le travail des jours précédents,
transformant le projet en une série de réécritures plutôt qu'une évolution.

---

## Décision

**Les tests des jours précédents ne sont jamais modifiés pour accommoder
les changements d'un jour ultérieur, sauf pour corriger des bugs.**

Règle concrète :
- J01 : 15 tests. J29 : 15 tests du J01 passent encore sans modification.
- Si un changement du J10 casse les tests du J03 → le changement est refactorisé
  pour être rétrocompatible (ex: paramètres optionnels avec valeurs par défaut).

---

## Conséquences

### Positives
- Démontre qu'une bonne architecture peut évoluer sans réécriture
- Force l'utilisation de patterns d'extension (OCP, DIP) plutôt que de modification
- Le CI est simple : `pytest tests/` doit toujours passer

### Négatives
- Contrainte supplémentaire sur chaque refactoring
- Parfois, du code de compatibilité moins propre est nécessaire
  (ex: `registry if registry is not None else AccountRegistry()`)

### Exemples concrets

**J10 DIP — TransactionService :**
```python
# Avant J10 (J03)
def __init__(self) -> None:
    self._config = ConfigManager.get_instance()

# Après J10 — rétrocompatible
def __init__(self, config=None, alert_system=None) -> None:
    self._config = config or ConfigManager.get_instance()
```
Les 308 tests existants continuent de fonctionner avec `TransactionService()`.

**Bug J15 — Registry injection :**
```python
# Bug découvert : bool(empty_repo) == False
self._registry = registry or AccountRegistry()  # ← BUG

# Fix rétrocompatible
self._registry = registry if registry is not None else AccountRegistry()
```

---

## Validation

**J29 :** `pytest tests/` → 1000+ tests, 0 régression depuis J01.
