# Jour 08 — Liskov Substitution Principle (LSP)

## Le principe

> "Si S est un sous-type de T, alors les objets de type T peuvent être
> remplacés par des objets de type S sans altérer les propriétés
> désirables du programme."
> — Barbara Liskov (1987)

En pratique : partout où le code accepte un `Account`, il doit fonctionner
**sans surprise** avec `CurrentAccount`, `SavingsAccount`, `ProAccount`,
ou tout type futur enregistré via `AccountTypeRegistry` (Jour 07).

**Le signal d'une violation LSP :**
```python
# isinstance() dans la logique métier = violation LSP
if isinstance(account, SavingsAccount):
    # traitement spécial
elif isinstance(account, ProAccount):
    # autre traitement spécial
```

---

## Les violations potentielles dans BankCore

### Violation 1 : préconditions renforcées dans SavingsAccount

`Account.withdraw()` contrat implicite : "si le solde est suffisant,
le retrait réussit".

`SavingsAccount.withdraw()` ajoute : "ET le solde restant doit être ≥ 50€".

C'est une précondition plus stricte que le parent — violation LSP.

**Résolution :** documenter explicitement le contrat dans `Account.withdraw()`
pour que la précondition soit connue de tous. Un sous-type peut **affaiblir**
les préconditions (accepter plus), jamais les **renforcer** (accepter moins).

### Violation 2 : postconditions affaiblies dans ProAccount

`Account.withdraw()` contrat implicite : "après retrait, balance >= 0".

`ProAccount.withdraw()` : balance peut devenir négative (découvert).

C'est une postcondition plus faible — potentielle violation si du code
suppose `account.balance >= 0` après tout retrait réussi.

**Résolution :** le contrat de `Account` doit explicitement permettre
un solde négatif pour les types qui l'autorisent. On introduit
`min_possible_balance` comme propriété abstraite.

### Violation 3 : apply_interest() n'existe que sur SavingsAccount

```python
account = AccountFactory.create("savings", "Bob", 1000.0)
account.apply_interest()   # OK

account = AccountFactory.create("current", "Alice", 1000.0)
account.apply_interest()   # AttributeError — LSP violée
```

Un service qui appelle `apply_interest()` sur n'importe quel `Account`
plantera sur les types qui ne l'ont pas.

**Résolution :** `apply_interest()` ne doit pas être appelé via
l'interface `Account` — il appartient à une interface `InterestBearing`
séparée. Anticipation du Jour 09 (ISP).

---

## La décision

**Formaliser les contrats de `Account` avec des invariants explicites.**

Introduire :
1. `min_possible_balance` — propriété que chaque sous-type déclare
2. `can_withdraw(amount)` — vérifie la faisabilité sans effet de bord
3. `AccountContractVerifier` — vérifie les invariants LSP pour tout `Account`

Ces outils permettent de tester LSP mécaniquement :
```python
verifier = AccountContractVerifier()
verifier.verify(account)   # passe pour tout Account valide
```

---

## Règles LSP pour Account (contrat formel)

| Règle | Description |
|-------|-------------|
| **Invariant 1** | `account_id` est non-vide et immuable après construction |
| **Invariant 2** | `balance` reflète exactement la somme algébrique des transactions |
| **Invariant 3** | `deposit(amount)` avec amount > 0 augmente toujours le solde |
| **Invariant 4** | `withdraw()` retourne `False` sans modifier le solde si la règle échoue |
| **Invariant 5** | `balance >= min_possible_balance` toujours vrai |
| **Invariant 6** | `get_info()` retourne toujours les clés requises |

---

## Ce que ce jour prouve

Un test LSP passe si **tout sous-type existant et futur** satisfait
les invariants définis sur le type parent. `AccountContractVerifier`
sera réutilisé dans les tests de tout nouveau type de compte enregistré
via `AccountTypeRegistry` (Jour 07).

---

## Connexion avec les jours suivants

- **Jour 09 (ISP)** : `apply_interest()` sera déplacée vers
  `InterestBearing` — résout la Violation 3 proprement
- **Jour 10 (DIP)** : les services recevront `Account` par injection,
  jamais `SavingsAccount` ou `CurrentAccount` directement

---

## Complexité aujourd'hui

- 1 nouveau fichier : `account_contract.py`
- Modifications légères : `account.py` (ajout de `min_possible_balance`,
  `can_withdraw()`)
- 207 tests existants : **tous verts sans modification**
- Nouveaux tests : `test_lsp.py`
