---
summary: structure cible minimale du repository et repartition des responsabilites
read_when:
  - creer de nouveaux dossiers
  - hesiter sur l'emplacement d'un fichier
  - organiser les premiers fichiers du projet
---

# Repository Structure

## Principe

Le repository doit separer clairement:

- les regles et la memoire durable
- le code produit
- les scripts d'aide

## Structure minimale actuelle

- `AGENTS.md`: mode de travail agentique
- `PROJECT.md`: point d'entree projet
- `docs/`: documentation durable
- `scripts/`: scripts utilitaires de repository
- `backend/`: package Python backend
- `frontend/`: prototype front leger servi par l'API

## Regles d'emplacement

Si un fichier explique le projet ou une decision, il va dans `docs/`.

Si un fichier sert a automatiser une action de repository, il va dans `scripts/`.

Si un fichier fait partie du produit lui-meme, il doit vivre dans `backend/` ou `frontend/` selon sa responsabilite.

## Evolution attendue

Quand l'app iOS native apparaitra, documenter sa structure ici et clarifier la place du prototype web pour eviter les doublons.
