---
summary: perimetre du dossier docs et regles de documentation
read_when:
  - ajouter une nouvelle documentation
  - hesiter entre documenter ou coder
  - chercher le point d'entree documentaire du repo
---

# Docs Scope

`docs/` contient la memoire durable du projet:

- cadrage produit
- architecture
- regles de conception
- structure du repository
- decisions de travail qui doivent survivre a la conversation

On documente ici:

- la vision
- les hypotheses
- les conventions
- les contrats de structure
- les points de reprise pour un nouvel agent

On ne met pas ici:

- du code applicatif
- des artefacts generes
- des donnees runtime
- des notes jetables de conversation

## Format attendu

Chaque document Markdown de `docs/` doit contenir un front matter:

```md
---
summary: courte description
read_when:
  - quand lire ce document
---
```

Le script `scripts/docs:list` repose sur ce format.

## Regle de maintenance

Quand le comportement du projet change, la documentation concernee doit etre mise a jour dans le meme elan.
