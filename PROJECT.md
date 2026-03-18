# FitMAS

Equipe IA proactive qui ajuste ton entrainement et ta nutrition selon ta vraie vie.

## Status

V0 en construction. Cadrage termine. Code en cours.

## Stack

- Backend: Python + FastAPI + SQLite
- Front: webapp mobile-first
- Messagerie: Telegram bot (WhatsApp plus tard)
- IA: appels LLM directs + Pydantic structured outputs

## Ordre de lecture

1. `AGENTS.md` — regles de travail
2. `PROJECT.md` — ce fichier
3. `docs/PRODUCT.md` — vision, scope, parcours utilisateur
4. `docs/ARCHITECTURE.md` — stack, modele de donnees, flux
5. `docs/SOUL.md` — voix, heartbeat, messagerie
6. `docs/BUILD-ORDER.md` — quoi coder et dans quel ordre

## Structure du repo

```
AGENTS.md          — regles agentiques
PROJECT.md         — point d'entree
docs/              — 4 docs essentiels + README
backend/           — API FastAPI
frontend/          — webapp mobile-first
scripts/           — utilitaires repo
```

## Principes

- Determinisme avant LLM
- Un seul "agent" bien prompte en V0
- Heuristiques d'entrainement en dur, LLM pour personnaliser/formuler
- Telegram pour valider la proactivite, WhatsApp quand prouve
- SQLite en dev, PostgreSQL en prod
