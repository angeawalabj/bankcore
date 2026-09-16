# Outils de mise en place de l'historique Git

Ces trois fichiers documentent comment l'historique Git de ce dépôt a été
construit — à lire tel quel, sans détour :

- **`COMMITS.md`** — le détail prévu de chaque commit (fichiers touchés,
  contenu, tests ajoutés) pour les 30 jours du challenge.
- **`setup_git.py`** — génère `git_setup.sh` à partir de ce plan, avec
  une date par commit espacée sur 30 jours à partir du 1er février 2026.
- **`git_setup.sh`** — le script résultant, celui qui a effectivement
  créé les commits de ce dépôt.

Le code n'a pas nécessairement été écrit au rythme d'un commit par jour
calendaire — ces scripts répartissent l'historique sur 30 jours pour
correspondre à la structure du challenge, pas pour documenter un journal
de bord au jour le jour. Ils sont conservés ici, non cachés, plutôt que
supprimés : ils font partie de la méthode réelle de construction de ce
dépôt, pas seulement les 30 jours qu'ils simulent.

Ces scripts ont déjà été exécutés une fois pour construire l'historique
actuel — les relancer recréerait un nouvel historique, ils ne sont donc
conservés qu'à titre de documentation.
