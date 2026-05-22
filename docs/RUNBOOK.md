---
summary: guide operatoire court pour lancer, tester, debugger et verifier FitMAS
read_when:
  - demarrer localement
  - tester un flux reel
  - debugger un comportement coach
  - preparer un deploy
  - reprendre le projet apres une pause
---

# Runbook

## Lire Avant De Coder

```bash
./scripts/docs:list
```

Archives et anciens plans :

```bash
./scripts/docs:list --all
```

Ordre utile :

1. `PROJECT.md`
2. `docs/BUILD-ORDER.md`
3. `docs/DECISION-RUNTIME-REFACTOR.md`
4. doc domaine concernee

## Environnement

Minimum local :

- `DEEPSEEK_API_KEY`
- `TELEGRAM_BOT_TOKEN`

Fallback temporaire :

- `ANTHROPIC_API_KEY`

Strava :

- `STRAVA_CLIENT_ID`
- `STRAVA_CLIENT_SECRET`

Debug :

- `FITMAS_ENABLE_DEBUG_ENDPOINTS=1`

DB :

- local : `fitmas.db`
- prod Fly : `/data/fitmas.db`

## Lancer

Installer :

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

API locale :

```bash
./scripts/dev
```

Port alternatif :

```bash
PORT=8040 ./scripts/dev
```

Bot local :

```bash
./scripts/bot
```

Frontend :

```bash
./scripts/dev-web
```

Healthcheck API :

```bash
curl http://127.0.0.1:8033/health
```

## Tester

Backend complet :

```bash
./scripts/test-backend
```

Target pytest :

```bash
./scripts/test-backend -q tests/test_docs_list.py
```

Compile Python :

```bash
.venv/bin/python -m compileall backend/src/fitmas
```

Frontend :

```bash
cd frontend && npm test -- --run
cd frontend && npm run build
```

## Smoke Coach

Smoke API core :

```bash
./scripts/smoke-a-plus-api --skip-generated-week \
  --scenario lookup_current_plan \
  --scenario create_easy_free_day \
  --fallback-census-json /tmp/fitmas-core-census.json \
  --timeout 420
```

Résumé fallback :

```bash
./scripts/decision-runtime-fallback-census-summary \
  /tmp/fitmas-core-census.json \
  --json-out /tmp/fitmas-core-summary.json
```

Legacy planning/pending census :

```bash
./scripts/decision-runtime-planning-pending-census \
  --json-out /tmp/fitmas-10e-planning-pending-census.json
```

Smoke conversations reelles :

```bash
./scripts/smoke-real-conversations
```

Usage :

- utilise une DB temporaire ;
- charge `.env` si besoin ;
- fait des appels LLM reels ;
- a lancer quand on touche conversation, planning, pending, reply ou provider.

## Debug Ops

Activer :

```bash
FITMAS_ENABLE_DEBUG_ENDPOINTS=1 ./scripts/dev
```

Conversation :

```bash
curl -X POST "http://127.0.0.1:8033/ops/conversation/debug" \
  -H "Content-Type: application/json" \
  -d '{"text":"redonne le plan actuel"}'
```

Heartbeat :

```bash
curl -X POST "http://127.0.0.1:8033/ops/heartbeat/morning?dump=true&send=false"
```

Ne pas exposer les endpoints ops en prod sans flag explicite.

## Quand Ca Casse

Localiser par couche :

- contexte faux -> `decision/context_builder.py` ou read models ;
- comprehension fausse -> `llm/understanding_service.py` / prompts ;
- planning faux -> `domain/planning/*` ;
- pending faux -> bridges pending actuels, cible `decision/` ;
- write faux -> mutation/command service ;
- reply fausse -> reply composer/backend/verifier ;
- livraison fausse -> `app/telegram/` ou route API.

Eviter :

- ajouter un fallback local ;
- gonfler un prompt ;
- parser le texte utilisateur ;
- recreer un wrapper root supprime.

## Deploy

Verifier avant deploy :

```bash
./scripts/test-backend
```

Puis utiliser le workflow Fly existant.
Ne pas deployer un changement runtime conversation sans smoke reel si le temps
le permet.
