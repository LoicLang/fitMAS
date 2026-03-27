# FitMAS

Coach IA multisport proactif qui ajuste ton entraînement selon ta vraie vie.

## Statut — 27 mars 2026

**Déployé et fonctionnel sur https://the deployed app/**

Ce qui tourne en prod :
- Onboarding Telegram conversationnel complet (/start → profil + coach + plan)
- Planner hebdomadaire multisport déterministe (running, cycling, swimming, climbing, strength)
- Boucle message → LLM → mutation → réponse coach
- Webapp mobile-first React/Vite avec 5 onglets (Aperçu, Calendrier, Évolution, Activités, Profil)
- Activités manuelles + Strava OAuth + import + synchro automatique
- Heartbeat proactif avec cooldowns (briefing matin, rappel pré-séance, revue dimanche, nouveau plan lundi)
- Mémoire utile via UserFact (extraction LLM + upsert)
- Revue hebdomadaire + régénération automatique du plan le lundi matin
- Bot Telegram avec commandes (/start, /plan, /today, /newweek, /sync, /log)

Ce qui manque encore → voir `docs/BUILD-ORDER.md`

Cap produit actuel :
- Telegram = coach conversationnel
- App = cockpit performance
- prochaine fondation : Telegram moins bavard, charge d'entraînement, calendrier persistant daté

## Stack

| Composant | Choix |
|-----------|-------|
| Backend | Python 3.13 + FastAPI + SQLAlchemy 2.0 + SQLite |
| Front | React 18 + Vite + React Router + motion + Embla + Recharts |
| Messagerie | Telegram bot (python-telegram-bot 21) |
| IA | Anthropic Claude — Haiku quotidien, Sonnet pour plans |
| Cron | APScheduler (briefing 7h30, synchro Strava 2h, revue dimanche 20h) |
| Déploiement | Fly.io (CDG), Docker, volume SQLite persistant |

## Ordre de lecture

1. `AGENTS.md` — règles de travail
2. `PROJECT.md` — ce fichier
3. `docs/PRODUCT.md` — vision, scope, parcours utilisateur
4. `docs/ARCHITECTURE.md` — stack, modèle de données, flux
5. `docs/APP-UX.md` — contrat UX de l'app
6. `docs/PLANNING-ENGINE-V2.md` — roadmap moteur adaptee au code actuel
7. `docs/SOUL.md` — voix, heartbeat, messagerie
8. `docs/BUILD-ORDER.md` — ce qui est fait, ce qui reste, dans quel ordre

## Structure du repo

```
AGENTS.md            — règles agentiques
PROJECT.md           — point d'entrée
docs/                — 4 docs essentiels + README
backend/src/fitmas/  — API + bot + domaines partagés (34 modules, ~5200 lignes)
frontend/            — webapp React/Vite
scripts/             — dev, dev-web, start-prod, docs:list
Dockerfile           — image Docker multi-stage
fly.toml             — config Fly.io
```

## Dev local

```bash
rm -rf .venv && python3 -m venv .venv && .venv/bin/python -m pip install -e .
./scripts/dev
./scripts/dev-web
```

Local API via `./scripts/dev` démarre sur `127.0.0.1:8033` par défaut pour éviter les faux conflits avec un autre service en `:8000`.
Override possible : `PORT=8040 ./scripts/dev`
Frontend Vite via `./scripts/dev-web` sur `127.0.0.1:5173`, avec proxy API vers `:8033`.

DB : `fitmas.db` à la racine. Supprimer pour re-seeder.
Variables : `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `STRAVA_CLIENT_ID`, `STRAVA_CLIENT_SECRET`

## Principes

- Déterminisme avant LLM
- Un seul appel LLM bien prompté tant que le domaine n'exige pas mieux
- Heuristiques d'entraînement en dur, LLM pour personnaliser et formuler
- Telegram pour valider la proactivité, WhatsApp quand prouvé
- Telegram = relation coach, app = tableau de bord performance
- Build perso d'abord : single-user, multisport, usage quotidien réel
- Hotspots splittés par domaine : `api_*`, `telegram_*`, modules partagés transverses
