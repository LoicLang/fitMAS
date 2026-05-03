# FitMAS

Coach IA multisport proactif qui ajuste ton entraînement selon ta vraie vie.

## Statut — 2 mai 2026

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
- Heartbeat proactif avec cooldowns + catch-up matin borné (briefing matin, rappel pré-séance, revue dimanche, nouveau plan lundi)
- Mémoire V2 base : `profile / working / patterns`
- Runtime tools multi-tool borné : read-only / candidate / validation-only, aucun write DB libre
- Runtime conversationnel désormais branché sur les prompt layers live
- `CoachDecision` + `PlanPatch` branchés sur la conversation : validation serveur, confirmation pending, commit via `PlanMutationService`
- Doctrine conversation renforcee : zero determinisme sur texte utilisateur libre ; le LLM est le seul detecteur d'intention
- Phase 1 voix conversation shippée 30 avril : règles "Voix coach" + few-shots BONS/MAUVAIS sur `fitmas_message`, détecteur receipt-style log-only
- Phase 2 `pending_resolution` typed + `memory_actions` + `execution_actions` shippée 1 mai : confirmations résolues structurellement, plus de re-décision sauvage
- Anciens chemins `UserIndication`, replan legacy et tool routing deterministe supprimes du repo
- DeepSeek principal avec fallback Claude possible sur sorties structurées fragiles
- `suggest_replan_candidates` est le helper canonique de candidates replan ; `propose_replan` reste alias compat
- Workflow `replan_after_constraint` formalisé dans le prompt : tools atomiques → candidate optionnelle → `PlanPatch | no_change | requires_confirmation`
- Revue hebdomadaire + régénération automatique du plan le lundi matin
- Bot Telegram avec commandes (/start, /plan, /today, /newweek, /sync, /log)

La vérité "état réel + suite" vit dans `docs/BUILD-ORDER.md`.

Chantiers en cours (suite incident hallucination factuelle briefing 2 mai) :
- ✅ **Chantier 0** — TTL `_recent_proactive_context` (heartbeat) — shippé 2 mai 2026 — fix hallucination + 6 tests
- ✅ **Chantier 1** — Voix coach unifiée `coach_voice.py` partagée tous pipelines (conversation + briefing + reminder + review + signal) — shippé 3 mai 2026 — 5 commits atomiques (étapes A-E), 36 tests nouveaux
- **Chantier 2** — Truth source unifié runtime (4-5j) — clôture définitive Phase 3 cohérence + tuer dual-write — `docs/COACH-COHERENCE-REFACTOR.md`
- **Chantier 3** — Tool-use loop unifié conversation + heartbeat (6-7j) — vraie boucle agentique multi-rounds, prose terminale — `docs/LLM-FIRST-CONVERSATION.md`
- **Chantier 4** — Observabilité briefing (1j) — endpoint debug dump bundle + prompt + response
- **Phase A+** — Weekly Coherence Review (3-4j, après Chantier 3) — couche raisonnement week-level, transforme coach réactif local en coach stratégique — `docs/BUILD-ORDER.md` section dédiée

Cap produit actuel :
- Telegram = coach conversationnel
- App = cockpit performance
- priorité immédiate : dogfood Telegram + briefings réels pour valider voix unifiée, puis Chantiers 2+3 pour clôturer Phase A LLM-first et préparer Phase A+
- Phase B long terme : progression/prescription structurée, pas ouverte tant que Phase A + Chantiers 2+3 + Phase A+ ne sont pas clos

## Stack

| Composant | Choix |
|-----------|-------|
| Backend | Python 3.13 + FastAPI + SQLAlchemy 2.0 + SQLite |
| Front | React 18 + Vite + React Router + Tailwind CSS v4 + motion + Embla + Recharts |
| Messagerie | Telegram bot (python-telegram-bot 21) |
| IA | DeepSeek V4 — `deepseek-v4-flash` quotidien, `deepseek-v4-pro` pour plans/coach |
| Cron | APScheduler (briefing 7h30, synchro Strava 2h, revue dimanche 20h) |
| Déploiement | Fly.io (CDG), Docker, volume SQLite persistant |

## Ordre de lecture

1. `AGENTS.md` — regles de travail
2. `PROJECT.md` — ce fichier
3. `docs/README.md` — carte des docs
4. `docs/BUILD-ORDER.md` — source de verite sur l'etat reel et la suite
5. `docs/LLM-FIRST-CONVERSATION.md` — doctrine zero determinisme sur texte user + plan de migration
6. `docs/ARCHITECTURE.md` — stack, principes de harness, modele de donnees, flux
7. `docs/PRODUCT.md` — vision, scope, parcours utilisateur
8. `docs/COACH-COHERENCE-REFACTOR.md` — gouvernance state/mutations
9. `docs/PLANNING.md` — contrat + moteur planning
10. `docs/CONVERSATION.md` — grounding + indications utilisateur
11. `docs/SOUL.md` — voix, heartbeat, messagerie

## Structure du repo

```
AGENTS.md            — regles agentiques
PROJECT.md           — point d'entree
docs/                — docs actifs + README (anciens docs en docs/archive/ si besoin)
backend/src/fitmas/  — API + bot + domaines partages
backend/src/fitmas/tools/ — tools runtime read-only + contrats ; pas de routing deterministe depuis le texte user
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
Variables : `DEEPSEEK_API_KEY`, `TELEGRAM_BOT_TOKEN`, `STRAVA_CLIENT_ID`, `STRAVA_CLIENT_SECRET`

Stabilisation LLM :
- le chemin DeepSeek OpenAI-compatible structured output est le defaut quand `DEEPSEEK_API_KEY` existe
- `FITMAS_USE_DEEPSEEK_OPENAI_STRUCTURED=0` sert de kill switch temporaire
- `ANTHROPIC_API_KEY` sert de fallback schema Claude quand DeepSeek retourne un JSON invalide metier
`ANTHROPIC_API_KEY` reste un fallback temporaire pendant la migration provider.

## Principes

- LLM-first pour l'intention floue ; déterminisme pour vérité, validation, permissions, commit et audit
- Zero determinisme sur texte utilisateur libre : pas de regex, keyword, classifieur, parsing oui/non, extraction sante/dispo/execution/preference ou routing de tools hors LLM
- Le LLM produit des actions structurees ; le backend valide, resout, ecrit et audite
- Pas de reply conversationnelle finale depuis un helper déterministe, sauf outage minimal ou résumé d'event réel
- Tools atomiques et bornés avant gros tool magique
- `PlanPatch` est le langage d'action ; le write reste orchestré par `PlanMutationService`
- Mono-agent propre avant toute tentation multi-agent
- Telegram pour valider la proactivité, WhatsApp quand prouvé
- Telegram = relation coach, app = tableau de bord performance
- Build perso d'abord : single-user, multisport, usage quotidien réel
- Hotspots splittés par domaine : `api_*`, `telegram_*`, modules partagés transverses
- Les écrans app lisent des payloads dédiés backend, pas des objets bruts réassemblés côté front
