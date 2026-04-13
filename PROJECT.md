# FitMAS

Coach IA multisport proactif qui ajuste ton entraînement selon ta vraie vie.

## Statut — 13 avril 2026

**Déployé et fonctionnel sur https://the deployed app/**

Ce qui tourne en prod :
- Onboarding Telegram conversationnel complet (/start → profil + coach + plan)
- Planner hebdomadaire multisport déterministe (running, cycling, swimming, climbing, strength)
- Boucle message → LLM → mutation → réponse coach
- Webapp mobile-first React/Vite + Tailwind v4
- App React Router recentrée sur 3 tabs primaires : `Aperçu`, `Calendrier`, `Évolution`
- Détail séance en page dédiée : `/workout/:sessionId`
- Read models backend dédiés aux écrans app : `overview`, `calendar`, `evolution`, `session detail`
- Activités manuelles + Strava OAuth + import + synchro automatique
- Heartbeat proactif avec cooldowns (briefing matin, rappel pré-séance, revue dimanche, nouveau plan lundi)
- Mémoire V2 base : `profile / working / patterns`
- Runtime tools V1 read-only bornés pour certaines questions de lecture
- Runtime conversationnel désormais branché sur les prompt layers live
- Substrate de décision planning V1 renforcé pour mieux respecter l'intention de déplacement
- Revue hebdomadaire + régénération automatique du plan le lundi matin
- Bot Telegram avec commandes (/start, /plan, /today, /newweek, /sync, /log)

La vérité "état réel + suite" vit dans `docs/BUILD-ORDER.md`.

Cap produit actuel :
- Telegram = coach conversationnel
- App = cockpit performance
- priorité immédiate : meilleure lecture du réel, meilleure adaptation, mémoire plus propre, moins de duplication métier
- ordre courant : substrate de capacités partagé, weekly reality digest, split progressif des hotspots, heartbeat plus contextuel

## Stack

| Composant | Choix |
|-----------|-------|
| Backend | Python 3.13 + FastAPI + SQLAlchemy 2.0 + SQLite |
| Front | React 18 + Vite + React Router + Tailwind CSS v4 + motion + Embla + Recharts |
| Messagerie | Telegram bot (python-telegram-bot 21) |
| IA | Anthropic Claude — Haiku quotidien, Sonnet pour plans |
| Cron | APScheduler (briefing 7h30, synchro Strava 2h, revue dimanche 20h) |
| Déploiement | Fly.io (CDG), Docker, volume SQLite persistant |

## Ordre de lecture

1. `AGENTS.md` — regles de travail
2. `PROJECT.md` — ce fichier
3. `docs/README.md` — carte des docs
4. `docs/BUILD-ORDER.md` — source de verite sur l'etat reel et la suite
5. `docs/ARCHITECTURE.md` — stack, principes de harness, modele de donnees, flux
6. `docs/PRODUCT.md` — vision, scope, parcours utilisateur
7. `docs/COACH-COHERENCE-REFACTOR.md` — gouvernance state/mutations
8. `docs/PLANNING.md` — contrat + moteur planning
9. `docs/CONVERSATION.md` — grounding + indications utilisateur
10. `docs/SOUL.md` — voix, heartbeat, messagerie

## Structure du repo

```
AGENTS.md            — regles agentiques
PROJECT.md           — point d'entree
docs/                — 12 docs actifs + README (anciens docs en docs/archive/)
backend/src/fitmas/  — API + bot + domaines partages
backend/src/fitmas/tools/ — tools runtime read-only et routing associes
backend/src/fitmas/skills/heartbeat/ — cluster heartbeat (evaluation, roles, generation)
frontend/            — webapp React/Vite/Tailwind (3 tabs + detail seance)
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
- Mono-agent propre avant toute tentation multi-agent
- Heuristiques d'entraînement en dur, LLM pour personnaliser et formuler
- Telegram pour valider la proactivité, WhatsApp quand prouvé
- Telegram = relation coach, app = tableau de bord performance
- Build perso d'abord : single-user, multisport, usage quotidien réel
- Hotspots splittés par domaine : `api_*`, `telegram_*`, modules partagés transverses
- Les écrans app lisent des payloads dédiés backend, pas des objets bruts réassemblés côté front
