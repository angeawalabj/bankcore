# Jour 13 — Modélisation de Base de Données

## Le problème concret

Un système bancaire sans schéma BDD réfléchi c'est :

- Des transactions enregistrées sans contrainte de solde
- Des virements sans référence à la transaction originale
- Impossible de reconstruire l'historique d'un compte
- Pas de contrainte d'intégrité référentielle entre comptes et transactions

---

## Les entités à modéliser

BankCore a cinq entités distinctes :

**Account** — un compte bancaire avec son type, propriétaire, solde courant

**Transaction** — chaque débit/crédit sur un compte (append-only, jamais modifiées)

**Transfer** — un virement reliant deux transactions (débit source + crédit destination)

**Owner** — un titulaire peut avoir plusieurs comptes

**FeeRecord** — trace de chaque prélèvement de frais, liée à une transaction

---

## Diagramme UML du schéma

```mermaid
erDiagram
    OWNER {
        TEXT owner_id PK
        TEXT full_name NOT_NULL
        TEXT email UNIQUE
        TEXT created_at NOT_NULL
    }

    ACCOUNT {
        TEXT account_id PK
        TEXT owner_id FK
        TEXT account_type NOT_NULL
        REAL balance NOT_NULL
        REAL min_possible_balance NOT_NULL
        TEXT status NOT_NULL
        TEXT created_at NOT_NULL
        TEXT updated_at NOT_NULL
    }

    TRANSACTION {
        TEXT tx_id PK
        TEXT account_id FK
        REAL amount NOT_NULL
        REAL balance_after NOT_NULL
        TEXT description NOT_NULL
        TEXT tx_type NOT_NULL
        TEXT created_at NOT_NULL
    }

    TRANSFER {
        TEXT transfer_id PK
        TEXT debit_tx_id FK
        TEXT credit_tx_id FK
        REAL amount NOT_NULL
        TEXT status NOT_NULL
        TEXT initiated_by NOT_NULL
        TEXT created_at NOT_NULL
    }

    FEE_RECORD {
        TEXT fee_id PK
        TEXT account_id FK
        TEXT linked_tx_id FK
        REAL fee_amount NOT_NULL
        TEXT strategy_name NOT_NULL
        TEXT created_at NOT_NULL
    }

    OWNER ||--o{ ACCOUNT : "owns"
    ACCOUNT ||--o{ TRANSACTION : "has"
    TRANSACTION ||--o| TRANSFER : "is debit of"
    TRANSACTION ||--o| TRANSFER : "is credit of"
    ACCOUNT ||--o{ FEE_RECORD : "charged"
    TRANSACTION ||--o| FEE_RECORD : "linked to"
```

---

## Décisions de conception

### 1. Transactions append-only
Les transactions ne sont **jamais modifiées ni supprimées**.
Si un virement est annulé, on crée une transaction de contre-passation.
L'historique est immuable — auditabilité garantie.

### 2. balance_after dans chaque transaction
Dénormalisation intentionnelle : stocker le solde après chaque transaction
permet de reconstituer l'état du compte à n'importe quel instant
sans recalculer toute la chaîne.

### 3. Transfer comme entité séparée
Un virement n'est pas une transaction — c'est une relation entre deux
transactions. Débit sur Alice + Crédit sur Bob = un Transfer.
Si le crédit échoue, le débit est enregistré, le Transfer reste en
status "PENDING" — traçabilité complète.

### 4. Clés primaires TEXT (UUID)
Pas d'auto-increment INTEGER. Raisons :
- Les UUIDs sont générés par le Domaine (pas par la BDD)
- Portabilité : UUID fonctionne en distribué
- Pas de fuite d'information (on ne peut pas deviner le nombre de comptes)

### 5. Contraintes CHECK
```sql
CHECK (balance >= min_possible_balance)
CHECK (amount != 0)
CHECK (status IN ('ACTIVE', 'FROZEN', 'CLOSED'))
```
La BDD est la dernière ligne de défense — les contraintes métier
ne doivent pas exister uniquement dans le code Python.

---

## Index stratégiques

```sql
-- Requêtes fréquentes : historique par compte
CREATE INDEX idx_tx_account_id ON transaction(account_id);
CREATE INDEX idx_tx_created_at ON transaction(created_at);

-- Requêtes fréquentes : comptes par propriétaire
CREATE INDEX idx_account_owner_id ON account(owner_id);

-- Audit : transfers par date
CREATE INDEX idx_transfer_created_at ON transfer(created_at);
```

---

## Connexion avec les jours suivants

- **Jour 14 (Repository)** : `SQLiteAccountRepository` implémente
  `AccountRepositoryPort` avec ce schéma
- **Jour 21 (Event Sourcing)** : la table `transaction` devient
  une event store — chaque transaction est un `DomainEvent`

---

## Complexité aujourd'hui

- 1 nouveau fichier : `schema.py` (DDL SQLite + migrations)
- 1 nouveau fichier : `schema_validator.py` (vérifications d'intégrité)
- Tests : `test_database_schema.py`
