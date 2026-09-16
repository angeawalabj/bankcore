# Jour 27 — RBAC (Role-Based Access Control)

## Le problème concret

Jusqu'ici, n'importe quel appelant peut virer 50 000€ ou consulter
n'importe quel compte : les Use Cases (J11) n'ont aucune notion
d'identité. Un `TransferUseCase.execute(command)` fait ce qu'on lui
demande, point.

**La question qu'un auditeur (ou un incident de prod) va poser :**
> "Qui a autorisé ce virement de 80 000€ ? Un guichetier peut-il faire ça ?"

Sans contrôle d'accès, la réponse est toujours "tout le monde peut tout
faire" — inacceptable pour un système bancaire.

---

## Le modèle : Permission, Role, Principal

```
Permission   → capacité atomique ("transfer", "deposit", "create_account")
Role         → ensemble nommé de permissions (Teller, Manager, Admin, System)
Principal    → une identité authentifiée, porteuse d'un Role et de limites
```

Hiérarchie livrée (`ROLE_PERMISSIONS`) :

```
Teller  → view_account, deposit, withdraw
Manager → Teller + transfer, close_account, view_reports, view_audit_log
Admin   → Manager + create_account, manage_users, configure_system
System  → toutes les permissions (appels internes inter-services)
```

Chaque `Principal` porte aussi des **limites par opération** :
```python
teller("U1", "Alice", transfer_limit=5_000.0)
# Principal(role=TELLER, limits={"transfer": 5000.0, "withdraw": 5000.0})
```
Un Teller a la permission `transfer`... mais seulement jusqu'à sa limite.
La permission dit *quoi*, la limite dit *combien* — ce sont deux vérifications
distinctes dans `AuthorizationService.authorize()`.

---

## AuthorizationService — le point de décision unique

```python
authz.authorize(principal, Permission.TRANSFER, resource=account_id, amount=80_000)
```

Deux vérifications, dans cet ordre :
1. **Permission** : `principal.has_permission(TRANSFER)` — sinon `AuthorizationError`
2. **Limite** : `amount > principal.get_limit("transfer")` — sinon `LimitExceededError`

Chaque décision (`GRANTED`, `DENIED`, `LIMIT_EXCEEDED`) est enregistrée et,
si un `audit_log` (J26) est injecté, écrite dans la chaîne HMAC — une
tentative de virement refusée laisse une trace infalsifiable, pas juste
une ligne de log qu'on peut effacer.

---

## @requires_permission — brancher l'autorisation sur les Use Cases

```python
class TransferUseCase:
    @requires_permission(Permission.TRANSFER, amount_arg="amount")
    def execute(self, command, principal: Principal):
        ...
```

Le décorateur retrouve le `Principal` et le montant dans les arguments,
appelle `self._authz.authorize(...)`, et ne laisse `execute()` s'exécuter
que si l'autorisation passe. `SecuredBankApplicationService` fait la même
chose de façon explicite (sans décorateur) pour chaque opération exposée —
deux styles pour le même résultat, au choix de l'appelant.

---

## Connexion avec les jours précédents

- **J10 (DIP)** : `AuthorizationService` est injecté, pas construit en dur —
  testable avec des `Principal` fabriqués à la main
- **J11 (Use Cases)** : le contrôle d'accès enveloppe l'exécution, il ne
  la remplace pas
- **J26 (Audit Log)** : chaque décision GRANTED/DENIED/LIMIT_EXCEEDED est
  une entrée signée, pas un simple `print()`

---

## Complexité aujourd'hui

- 1 nouveau fichier : `application/rbac/rbac.py`
- 32 tests (`test_rbac.py`) : hiérarchie de rôles, limites, décorateur,
  `SecuredBankApplicationService`
