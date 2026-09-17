# Pourquoi le Code n'est Jamais Optimal au Début
## Et pourquoi tout projet sérieux exige un suivi de toute sa durée de vie

*Un texte sur la gestion de projet, l'architecture logicielle, et ce que BankCore démontre vraiment.*

---

## Ce qu'on observe sur le terrain

Chaque développeur a vécu cette situation :

> *"On va refactorer ce module, il est devenu ingérable."*

Et six mois plus tard :

> *"On va réécrire complètement ce module, il est devenu ingérable."*

Ce n'est pas un problème de compétence. Ce n'est pas un problème de flemme.
C'est un problème de **compréhension de la nature des projets logiciels**.

---

## La vérité inconfortable

**Le code parfait dès le premier jour n'existe pas.**

Non pas parce que les développeurs sont mauvais. Mais parce que :

- Au Jour 1, le problème a une certaine forme
- Au Jour 90, ce même problème a une forme différente
- Au Jour 365, il a une forme que personne n'avait anticipée

BankCore en est la preuve directe.

Au Jour 1, `ConfigManager` était 80 lignes. Simple, lisible, suffisant.
Si on avait essayé d'y intégrer dès le départ les microservices, le CQRS,
les sagas et l'audit log cryptographique, le projet n'aurait jamais démarré.

**La complexité est une propriété émergente. Elle arrive avec le temps,
pas avec le premier commit.**

---

## Ce que cela implique concrètement

Si la complexité est émergente, alors l'optimisation ne peut pas être
un événement ponctuel. Elle doit être un **processus continu**.

Cela veut dire que dans tout projet sérieux :

- Il y aura du **refactoring** — pas parce qu'on a mal fait, mais parce que le problème a évolué
- Il y aura des **ADR** (Architecture Decision Records) — pour que les futures évolutions respectent les contraintes passées
- Il y aura des **livrables intermédiaires** — pas pour "montrer de l'avancement", mais pour valider que la direction est bonne avant que le coût du changement devienne prohibitif
- Il y aura des **tests automatisés** — pas pour avoir une couverture à 100%, mais pour que le refactoring soit possible sans régression silencieuse

Et tout cela nécessite quelqu'un pour l'orchestrer.

---

## Le rôle de l'architecte : ce qu'il est vraiment

On confond souvent l'architecte avec "le développeur senior qui fait les choix techniques".

Ce n'est pas ça.

**L'architecte est la personne qui crée les conditions pour que le projet
reste maintenable quand la complexité arrive — et elle arrive toujours.**

Concrètement, l'architecte :

**Définit les règles avant d'en avoir besoin.**
Au Jour 6 de BankCore, le SRP (Single Responsibility Principle) a été introduit.
Pas parce qu'il y avait un problème urgent. Mais parce que sans cette règle,
le code du Jour 15 aurait été ingérable.

**Anticipe les points de rupture.**
Au Jour 7, un registre (`AccountTypeRegistry`) a remplacé un `if/elif` hardcodé.
À ce moment, il n'y avait que 3 types de comptes. Ce n'était pas nécessaire
pour les 3 types. C'était nécessaire pour le 4ème type qui arriverait forcément.

**Documente les décisions, pas juste le code.**
Le code dit *quoi*. Les ADR disent *pourquoi*.
Sans ADR-007 (idempotency via `id(consumer)` plutôt que `consumer.name`),
ce choix "bizarre" serait "corrigé" par le prochain développeur,
recréant silencieusement le bug d'origine.

**Maintient la cohérence dans le temps.**
BankCore a 30 jours de développement. Les tests du Jour 1 passent encore
au Jour 30 sans modification. Ce n'est pas de la chance —
c'est le résultat de règles de rétrocompatibilité appliquées systématiquement.

**Gère la dette technique de façon explicite — jusqu'à sa résolution.**
ADR-009 documentait que `interest_rate` n'était pas persisté comme événement
de domaine. C'était une dette technique nommée, documentée, et planifiée
pour résolution — pas "du code sale ignoré" mais un compromis assumé avec
un plan. Elle a depuis été résolue (`InterestRateSet`), et l'ADR documente
maintenant les deux : le constat honnête du départ, et la correction réelle.

---

## La formation : pourquoi elle ne s'arrête pas à l'apprentissage des patterns

BankCore enseigne 20+ patterns et principes architecturaux.
Mais ce n'est pas ce que le projet démontre de plus important.

Ce qu'il démontre vraiment, c'est **la progression**.

Un développeur qui connaît le Decorator Pattern peut l'appliquer sur commande.
Un architecte comprend *pourquoi* le Decorator Pattern a été introduit au Jour 5
**et pas au Jour 1** — et ce que ça aurait coûté de l'introduire trop tôt
(sur-ingénierie) ou trop tard (refactoring massif).

**La formation ne se termine pas quand on connaît les patterns.
Elle se termine quand on sait *quand* et *pourquoi* les appliquer.**

Et cette connaissance ne s'acquiert que par l'exposition à des projets
qui ont grandi, échoué, été refactorisés — et documentés honnêtement.

C'est ce que BankCore essaie d'être : un projet honnête sur sa propre évolution.

---

## Ce qu'exige un projet du début jusqu'à la fin

Un projet logiciel de niveau professionnel n'est pas un sprint.
C'est un marathon avec des checkpoints.

**Au démarrage :**
- Définir les règles les plus importantes (pas toutes — juste les plus importantes)
- Établir les contraintes non-négociables (sécurité, auditabilité, performance)
- Choisir l'architecture initiale en sachant qu'elle évoluera
- Mettre en place les outils de vérification (tests, CI) avant la première feature

**En cours de route :**
- Des livrables réguliers — pas "quand c'est prêt", mais à intervalles définis
- Des revues d'architecture — "est-ce qu'on respecte encore nos règles initiales ?"
- Du refactoring planifié — pas d'urgence, pas de dette cachée
- De la documentation des décisions — pas du code commenté, des ADR

**Sur la durée :**
- Des fonctionnalités nouvelles ajoutées sans réécriture du cœur
- Des technologies remplacées sans changer la logique métier
- Des équipes qui changent sans perte de connaissance architecturale
- Un système qui reste compréhensible après 3 ans, pas seulement après 3 mois

Rien de tout cela n'est possible sans quelqu'un dont le rôle est
de maintenir cette cohérence dans le temps.

**C'est pourquoi l'architecte n'est pas un luxe sur un projet ambitieux.
C'est une nécessité.**

---

## La conclusion que BankCore rend visible

```
30 jours · 64 fichiers source · 28 fichiers de tests
1 050 tests · 23 602 lignes · 0 réécriture complète
```

Ce résultat n'est pas dû à la brillance du code du Jour 1.
Il est dû à une règle simple appliquée tous les jours :

> *"Les tests des jours précédents ne cassent jamais."*

Cette règle a forcé chaque changement à être rétrocompatible.
Cette contrainte a forcé l'utilisation de patterns d'extension plutôt que de modification.
Ces patterns ont rendu le code maintenable au Jour 30 comme au Jour 1.

**Une règle. Appliquée systématiquement. Sur 30 jours.**

C'est tout ce qu'il faut pour transformer du code qui "marche" en architecture qui "dure".

Et c'est ce que la formation — vraie formation, pas les tutoriels — doit transmettre :
pas juste les patterns, mais la discipline de les appliquer dans le temps.

---

*BankCore — 30 jours de discipline architecturale*  
*Commencé le 1er février 2026 · Terminé le 6 mars 2026*
