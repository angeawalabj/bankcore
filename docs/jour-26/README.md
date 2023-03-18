# Jour 26 — Audit Log Immuable

## Le problème légal concret

Un système bancaire est soumis à des obligations légales d'auditabilité :
- PCI-DSS : traçabilité complète de chaque transaction
- RGPD : qui a accédé à quoi, quand
- Bâle III : preuve d'intégrité des données financières

**La question qu'un auditeur externe va poser :**
> "Comment pouvez-vous prouver que l'entrée #4721 n'a pas été modifiée
> après coup pour dissimuler une fraude ?"

Avec une BDD classique : impossible. `UPDATE audit_log SET amount = 100 WHERE id = 4721` ne laisse aucune trace.

**Avec un Audit Log chaîné :** modifier l'entrée #4721 casse la chaîne à partir de #4722. La falsification est **détectable**.

---

## Le mécanisme : chaînage cryptographique

```
Entrée 1 :  hash = SHA256(data_1)                      → "a3f9..."
Entrée 2 :  hash = SHA256(data_2 + prev_hash="a3f9...")  → "b7c2..."
Entrée 3 :  hash = SHA256(data_3 + prev_hash="b7c2...")  → "e1d4..."
```

Si quelqu'un modifie `data_2` :
- Le hash de l'entrée 2 change
- L'entrée 3 contient l'ancien hash de 2
- La vérification de 3 échoue → falsification détectée

C'est le même principe que la blockchain, sans la partie distribuée.

---

## Signature HMAC

En plus du chaînage, chaque entrée est signée avec une clé secrète :

```
signature = HMAC-SHA256(secret_key, entry_content)
```

Même si l'attaquant connaît l'algorithme de chaînage, il ne peut pas
recalculer des signatures valides sans la clé secrète.

---

## Architecture BankCore J26

```
AuditLogger (J03 Observer) ──── écrit dans ────> ImmutableAuditLog
                                                       │
                                                  chaîne + signe
                                                       │
                                                  AuditEntry
                                                  ├── entry_id
                                                  ├── timestamp
                                                  ├── event_type
                                                  ├── payload
                                                  ├── prev_hash   ← chaînage
                                                  ├── entry_hash  ← intégrité
                                                  └── signature   ← authenticité
```

---

## Connexion avec les jours précédents

- **J03 (AuditLogger)** : devient le writer de l'ImmutableAuditLog
- **J21 (EventStore)** : même concept — append-only, mais l'audit log
  ajoute la signature cryptographique
- **J28 (Secrets)** : la clé HMAC sera gérée par SecretsProvider
