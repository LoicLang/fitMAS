---
summary: guide opératoire pour lancer, tester, débugger et modifier FitMAS sans perdre de temps
read_when:
  - démarrer localement
  - tester un flux réel
  - débugger la prod
  - préparer un deploy
  - reprendre le projet après une pause
---

# FitMAS Runbook

## Objectif

Permettre à un nouvel agent de :
- lancer le système vite
- savoir quels flux tester vraiment
- débugger sans casser la prod
- trouver vite le bon module à modifier

## Topologie actuelle

- un seul service Fly.io
- une seule machine
- API FastAPI locale via `./scripts/dev` sur `:8033` par défaut
- API FastAPI prod sur `:8000`
- bot Telegram lancé dans le même conteneur
- SQLite sur volume Fly monté dans `/data`

Entrypoints :
- local API : `./scripts/dev`
- local frontend React : `./scripts/dev-web`
- local bot : `./scripts/bot`
- prod entrypoint : [`scripts/start-prod`](/Users/loiclang/Documents/Projects/FitMAS/scripts/start-prod)

## Variables d'environnement

Minimum local utile :
- `DEEPSEEK_API_KEY`
- `TELEGRAM_BOT_TOKEN`

`ANTHROPIC_API_KEY` reste accepte comme fallback temporaire si `DEEPSEEK_API_KEY` est absent.

Provider LLM / stabilisation :
- le chemin DeepSeek OpenAI-compatible pour les sorties structurees de conversation est actif par defaut quand `DEEPSEEK_API_KEY` existe
- `FITMAS_USE_DEEPSEEK_OPENAI_STRUCTURED=0` sert de kill switch temporaire si le dogfood revele une regression provider
- si ce flag est actif, garder `ANTHROPIC_API_KEY` disponible pour le fallback schema Claude

Pour Strava :
- `STRAVA_CLIENT_ID`
- `STRAVA_CLIENT_SECRET`

Pour prod / déploiement :
- `FITMAS_DB_PATH`
- `FITMAS_PUBLIC_URL`
- `TZ`
- `FLY_APP_NAME`
- `FITMAS_ENABLE_DEBUG_ENDPOINTS`
- `FITMAS_TELEGRAM_DEBOUNCE_SECONDS`

Notes :
- `.env` est chargé par l'API et le bot
- en local, DB par défaut : `fitmas.db` à la racine
- en prod, DB : `/data/fitmas.db`
- debounce Telegram par défaut : `2.5s`

## Commandes de base

Installer :

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

Lister la doc :

```bash
./scripts/docs:list
```

Lancer l'API locale :

```bash
./scripts/dev
```

Comportement :
- `./scripts/dev` refuse de démarrer si le port demandé est déjà occupé
- raison : éviter un split-brain local où `127.0.0.1:8000` sert une autre app pendant que FitMAS prend `0.0.0.0:8000`
- override simple : `PORT=8040 ./scripts/dev`

Lancer le bot local :

```bash
./scripts/bot
```

Compiler les modules Python :

```bash
.venv/bin/python -m compileall backend/src/fitmas
```

Build frontend :

```bash
cd frontend && npm run build
```

Tests frontend :

```bash
cd frontend && npm test -- --run
```

Tests backend app/read-models :

```bash
./scripts/test-backend tests/test_calendar_resolution.py tests/test_load_projection.py tests/test_app_endpoints.py
```

Smoke backend conversation/tools :

```bash
./scripts/test-backend -q tests/test_conversation_prompting.py tests/test_llm_first_conversation_contract.py tests/test_llm_json.py tests/test_llm_tools.py tests/test_conversation_context.py tests/test_execution_context.py tests/test_tool_runtime.py tests/test_memory_mutation_service.py tests/test_memory_routing.py tests/test_memory_patterns.py tests/test_core_flows.py
```

Smoke API minimal :

```bash
PORT=8033 ./.venv/bin/python -m uvicorn --app-dir backend/src fitmas.api:app --host 127.0.0.1 --port 8033
curl http://127.0.0.1:8033/health
```

Smoke conversations reelles :

```bash
./scripts/smoke-real-conversations
```

Usage :
- utilise une DB temporaire dediee au smoke
- charge `.env` si besoin
- joue une batterie de scenarios conversationnels avec vraie API LLM
- utile si on touche `api_messages.py`, `heartbeat.py`, `llm.py`, `conversation_pipeline.py`, `adaptation.py`

Smoke DeepSeek OpenAI-compatible structured output :

```bash
FITMAS_USE_DEEPSEEK_OPENAI_STRUCTURED=1 ./scripts/spike-deepseek-openai-sdk --models deepseek-v4-flash
```

Smoke conversation avec le flag structured output :

```bash
set -a; source .env; set +a
FITMAS_USE_DEEPSEEK_OPENAI_STRUCTURED=1 \
ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-$DEEPSEEK_API_KEY}" \
./scripts/smoke-real-conversations --scenario golden_case_autonomy --scenario today_unavailability
```

Smoke API Phase A+ / WeekCoherence :

```bash
set -a; source .env; set +a
FITMAS_USE_DEEPSEEK_OPENAI_STRUCTURED=1 \
ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-$DEEPSEEK_API_KEY}" \
./scripts/smoke-a-plus-api
```

Usage :
- lance un vrai serveur HTTP local `fitmas.main:app` sur un port libre a partir de `8073` ;
- utilise une DB SQLite temporaire dediee ;
- seed une semaine runtime en `ScheduledSession` avec deux seances cles running, recuperation, velo et natation ;
- joue des scenarios reels via `/api/v0/messages` avec le vrai provider LLM ;
- verifie les artefacts DB : `plan_mutation_events`, `pending_mutation_confirmations`, `conversation_turns`, `scheduled_sessions`.

Scenarios verrouilles :
- `move_hard_close` : deplacer une seance dure/key vers une fenetre dangereuse ne doit pas commit ;
- `replace_key_running_swim_easy` : remplacer une seance cle running par natation easy ne doit pas commit ;
- `add_hard_dense` : ajouter du dur dans une semaine deja dense ne doit pas commit silencieusement ;
- `occupied_target` : target occupee ne doit pas commit ;
- `memory_preference` : preference memoire ne doit pas creer de write planning ;
- `move_easy_to_free` : un move easy peut commit ou demander confirmation, mais jamais claim sans event/pending.

Commandes utiles :

```bash
./scripts/smoke-a-plus-api --scenario move_hard_close --scenario replace_key_running_swim_easy
./scripts/smoke-a-plus-api --keep-db --port 8075
```

Smoke Phase A avant dogfood reel :

```bash
set -a; source .env; set +a
FITMAS_USE_DEEPSEEK_OPENAI_STRUCTURED=1 \
ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-$DEEPSEEK_API_KEY}" \
./scripts/smoke-real-conversations --scenario golden_case_autonomy --scenario today_unavailability
```

Checks attendus :
- pas de crash API
- pas de 400 tool-use
- les continuations courtes (`Oui`, `Running`, `Mercredi`) appellent bien le LLM et peuvent produire mutation/event reel
- les tool traces peuvent montrer un fallback JSON apres tool-use ; c'est connu, mais ne doit pas devenir une action silencieuse fausse

Debug proactive coach loop :

```bash
curl -X POST "http://127.0.0.1:8033/api/v0/debug/heartbeat/morning?dump=true&send=false" | jq
curl -X POST "http://127.0.0.1:8033/ops/heartbeat/signal_check?dump=true&send=false" | jq
```

Le dump contient : gate, contexte lu, prompt systeme/user, sortie LLM brute,
decision `send/no_send`, judge `ALLOW/BLOCK`, message final ou raison de
silence. En prod, activer explicitement `FITMAS_ENABLE_DEBUG_ENDPOINTS=true`
avant d'appeler ces endpoints.

Depuis le 28 avril, le scheduler a un catch-up jusqu'a 10h locale si le creneau jitter du briefing matin a ete rate et qu'aucun proactif n'a deja ete envoye.

Smoke ton sur profil reel :

```bash
./scripts/smoke-real-profile --source-db .tmp-fitmas-prod-copy.db
```

Usage :
- copie la DB source vers une DB temporaire jetable
- upgrade le schema localement si besoin
- rejoue une batterie de messages sur le vrai profil, le vrai coach et le vrai historique
- imprime la reponse, un indicateur simple de verbosite, et les effets memoire / sessions
- utile pour calibrer le ton, les low-info replies, et les reactions sur de vraies donnees utilisateur

## Parcours réels à tester

### 1. Parcours onboarding

À tester si on touche :
- `telegram_onboarding.py`
- `api_onboarding.py`
- `planner.py`
- `llm.py`

Scénario :
1. `/start`
2. sports
3. objectif
4. semaine réelle
5. contraintes
6. création du coach
7. preview de voix
8. validation
9. vérifier plan, profil, facts

Checks :
- pas de sortie de ConversationHandler
- preview cohérente
- `telegram_chat_id` bien stocké
- plan créé
- facts onboarding présents

### 2. Parcours message → mutation

À tester si on touche :
- `api_messages.py`
- `llm.py`
- `mutations.py`
- `repository.py`

Scénario :
1. envoyer un message naturel
2. vérifier la réponse coach
3. vérifier l'effet sur le plan si mutation
4. vérifier que les facts utiles montent en DB

Checks :
- `CoachMessage(user)` puis `CoachMessage(agent)`
- pas d'hallucination temporelle
- mutation cohérente ou no-op propre

### 3. Parcours activité réelle

À tester si on touche :
- `api_activities.py`
- `activities.py`
- `strava.py`
- `signals.py`

Scénario :
1. log manuel via webapp
2. vérifier activité créée
3. vérifier matching vers le bon jour
4. vérifier passage à `done`

Checks :
- sport normalisé
- titre raisonnable
- `matched_day` et `match_reason` cohérents
- activité hors fenêtre ne matche pas le plan courant

### 3 bis. Parcours app React

À tester si on touche :
- `frontend/src/app/`
- `frontend/src/features/`
- `backend/src/fitmas/api_app.py`
- `backend/src/fitmas/app_views.py`
- `backend/src/fitmas/calendar_resolution.py`

Scénario :
1. ouvrir `/`
2. ouvrir un détail séance depuis le hero ou le rail
3. revenir au calendrier
4. ouvrir `/evolution`
5. déclencher une action séance puis vérifier la revalidation

Checks :
- 3 tabs primaires seulement : `Aperçu`, `Calendrier`, `Évolution`
- le détail séance fonctionne en accès direct `/workout/:sessionId`
- le calendrier affiche bien `planned / done / missing / offplan`
- l'évolution charge même sans historique dense
- les utilitaires n'écrasent pas la lecture principale

### 4. Parcours heartbeat

À tester si on touche :
- `heartbeat.py`
- `telegram_scheduler.py`
- `telegram_channel.py`
- `time_context.py`

Scénario :
1. générer un draft heartbeat
2. vérifier cooldown
3. vérifier qu'on persiste seulement après envoi réussi
4. vérifier le rendu Telegram

Checks :
- `proactive=true` seulement pour les vrais messages proactifs
- pas de faux positif sur cooldown
- timezone user bien respectée

## Débugger sans casser la prod

Règle :
- éviter les scripts SSH lourds en prod
- préférer les endpoints debug si explicitement activés

Endpoints debug disponibles seulement si autorisés :
- `GET /api/v0/signals`
- `POST /api/v0/debug/heartbeat/{kind}?dump=true`
- `POST /ops/heartbeat/{kind}?dump=true`
- `POST /api/v0/reset`

Comportement voulu :
- debug OFF par défaut quand `FLY_APP_NAME` est présent
- override explicite via `FITMAS_ENABLE_DEBUG_ENDPOINTS=true`

## Mapping rapide : où modifier quoi

Si la demande concerne :

- endpoints API → `api_*.py`
- boot FastAPI → `api.py`
- onboarding Telegram → `telegram_onboarding.py`
- commandes Telegram → `telegram_commands.py`
- jobs / heartbeat Telegram → `telegram_scheduler.py`
- envoi Telegram pur → `telegram_channel.py`
- client backend du bot → `telegram_api.py`
- planning déterministe → `planner.py`
- décisions LLM / prompting / facts → `llm.py`
- mutations de plan → `mutations.py`
- heuristiques activité → `activities.py`
- signaux proactifs → `signals.py`
- temps / timezone / récence → `time_context.py`
- persistance centrale → `repository.py`, `schema.py`, `db.py`
- style / ton coach → `SOUL.md` + `llm.py` + `heartbeat.py`
- app mobile/web → `frontend/src/`
- read models app → `api_app.py`, `app_views.py`, `calendar_resolution.py`, `load_projection.py`

## Réalité des hotspots

Les fichiers encore lourds :
- `repository.py` (1453 lignes, 72 fonctions)
- `llm.py` (971 lignes)
- `conversation_pipeline.py` (853 lignes)
- `adaptation.py` (696 lignes)
- `heartbeat.py`

Avant d'ajouter de la logique dedans, se poser la question :
- est-ce un nouveau sous-domaine ?
- est-ce réutilisable ailleurs ?
- est-ce un signe qu'il faut sortir un module ?

## Vérification minimale avant fin de tâche

Toujours faire :
1. `.venv/bin/python -m compileall backend/src/fitmas`
2. `cd frontend && npm run build` si on touche l'app
3. au moins un smoke réel du flux touché
4. mise à jour doc si comportement modifié

Si le changement touche :
- `llm.py`
- `api_messages.py`
- `heartbeat.py`
- `adaptation.py`
- `conversation_pipeline.py`
- `planning_window_resolution.py`

Et si `DEEPSEEK_API_KEY` ou `ANTHROPIC_API_KEY` est dispo via `.env` ou l'environnement :
- charger `.env`
- lancer au moins **un smoke réel LLM-backed** sur le flux touché
- noter explicitement si le run tape bien l'API ou retombe en fallback

Commande pratique :

```bash
set -a
source ./.env >/dev/null 2>&1
set +a
```

Dire explicitement :
- ce qui a été testé concrètement
- ce qui reste non vérifié

## Pièges déjà rencontrés

- ~~heartbeat marqué comme "envoyé" alors que Telegram avait échoué~~ → **fixé** : persist + module guard déplacés après send Telegram réussi
- ~~cooldown calculé sur tous les messages agent au lieu de `proactive=true`~~ → **fixé** : `_check_cooldown` filtre `proactive.is_(True)`
- ~~`maintain_load` et labels anglais exposés dans l'UI~~ → **fixé** : `planning_mode_label_fr()`, `_freshness()` FR, labels focus FR, jours FR
- ~~séance du jour montre demain les jours de repos~~ → **fixé** : `build_app_overview` détecte `today_is_rest`
- ~~accents manquants dans planner/templates~~ → **fixé** : accents dans `planner.py`, `session_templates.py`
- ~~prompt LLM fuit dans session_note~~ → **fixé** : `_sanitize_coach_text()` dans `llm.py`
- ~~dénivelé affiché pour natation/renfo~~ → **fixé** : `build_session_detail` filtre `elevation_m` par sport
- `telegram_chat_id` absent en DB
- heartbeat local impossible sans chat id
- variables lues trop tôt au moment des imports
- shell web/PWA servi en vieille version côté appareil alors que la prod avait bien bougé
- un build frontend manquant peut masquer la SPA derrière la page "Frontend build missing"
- docs qui dérivent du code réel
- un autre service local pouvait déjà écouter sur `:8000`, ce qui faisait croire qu'on testait FitMAS alors qu'on lisait une autre app

## Quand déployer

Déployer seulement si :
- le flux touché a été smoké en local
- la doc a été réalignée si besoin
- le changement ne laisse pas un endpoint debug ouvert par accident

Si le changement touche heartbeat, onboarding, ou persistance :
- test réel recommandé après deploy

Si le changement touche `frontend/src/`, `frontend/index.html` ou `manifest.json` :
- vérifier la prod avec une URL shell versionnée
- vérifier au moins un rendu desktop et un rendu mobile
