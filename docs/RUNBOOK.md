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
3. `docs/V0-DOGFOOD-SCOPE.md`
4. `docs/RUNTIME-V0.md`
5. `docs/RUNTIME-MIGRATION-PLAN.md`
6. doc domaine concernee

## Environnement

Minimum local :

- `DEEPSEEK_API_KEY`
- `TELEGRAM_BOT_TOKEN`

Smoke provider matrix :

- `MISTRAL_API_KEY`
- `GEMINI_API_KEY`
- `XAI_API_KEY` ou `GROK_API_KEY`
- `FITMAS_LLM_PROFILE=deepseek|mistral|gemini|grok`
- override optionnel : `FITMAS_LLM_MODEL`
- override raisonnement optionnel : `FITMAS_LLM_REASONING_EFFORT`
- override raisonnement provider : `FITMAS_MISTRAL_REASONING_EFFORT`, `FITMAS_GEMINI_REASONING_EFFORT`, `FITMAS_GROK_REASONING_EFFORT`

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

Runtime V0 :

```bash
pytest tests/runtime_v0
python3 scripts/v0_eval/run_matrix.py --provider fake --repetitions 1
python3 scripts/v0_eval/run_matrix.py --repetitions 5
```

Exporter un run V0 :

```bash
python3 scripts/v0_eval/run_matrix.py \
  --repetitions 5 \
  --export-dir exports/runtime-v0/stability-providers-5x
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

Matrice provider coach :

```bash
./scripts/smoke-coach-provider-matrix
```

Par defaut, lance les 9 scenarios humains contre :

- DeepSeek : `deepseek-v4-pro`
- Mistral Small 4 : `mistral-small-2603`, `reasoning_effort=high`
- Gemini Flash 3.5 : `gemini-3.5-flash`, `reasoning_effort=medium`
- Grok : `grok-4.3`, `reasoning_effort=low`

Collecter les reponses/actions sans bloquer sur les attentes metier :

```bash
./scripts/smoke-coach-provider-matrix --review-only
```

Lancer les suites existantes aussi :

```bash
./scripts/smoke-coach-provider-matrix --review-only --suite all
```

Suites disponibles :

- `human` : 9 phrases humaines ciblees pour comparaison qualitative ;
- `core` : suite A+ historique par defaut ;
- `daily` : batterie conversation quotidienne ;
- `extended` : batterie etendue legacy/fallback/pending.

Comparer moins cher / plus vite :

```bash
./scripts/smoke-coach-provider-matrix \
  --review-only \
  --scenario ok_without_pending \
  --scenario fatigue_keep_light \
  --dry-run
```

Forcer un slug modele :

```bash
./scripts/smoke-coach-provider-matrix --model gemini=gemini-3.5-flash
```

Sorties :

- `.tmp-smoke-provider-matrix-*/summary.md`
- `.tmp-smoke-provider-matrix-*/summary.json`
- `.tmp-smoke-provider-matrix-*/<provider>/<suite>/smoke.db`
- `.tmp-smoke-provider-matrix-*/<provider>/<suite>/stdout.txt`
- `.tmp-smoke-provider-matrix-*/<provider>/<suite>/stderr.txt`
- `.tmp-smoke-provider-matrix-*/<provider>/<suite>/run.json`

Usage :

- utilise une DB temporaire separee par provider/suite ;
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
