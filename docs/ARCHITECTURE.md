---
summary: architecture technique courante, stack et frontieres repo
read_when:
  - comprendre la structure technique actuelle
  - ajouter une integration
  - modifier un entrypoint API, Telegram ou scheduler
  - verifier qu'un deplacement de fichier respecte l'organisation cible
---

# Architecture

## Cap

FitMAS est un coach multisport qui ajuste le plan selon la vraie vie.

Doctrine runtime :

```text
LLM-first pour comprendre le langage humain.
Determinism-first pour verite, validation, policy, writes et audit.
```

Le refactor en cours ne cherche pas un backend plus complet.
Il cherche un runtime plus petit.

## Stack

| Zone | Choix |
| --- | --- |
| Backend | Python 3.13, FastAPI, SQLAlchemy, Pydantic |
| DB | SQLite sur volume Fly en dogfood, Postgres plus tard si multi-user |
| Frontend | React, Vite, Tailwind, React Router |
| Bot | Telegram via `python-telegram-bot` |
| Scheduler | APScheduler in-process |
| LLM | DeepSeek prioritaire, Anthropic fallback temporaire |
| Deploy | Fly.io, Docker, volume persistant |

## Organisation Courante

```text
backend/src/fitmas/
  app/
    api/          routes et read models HTTP
    telegram/     bot, commands, onboarding, delivery et scheduler Telegram
  core/           db, time, temporal/calendar resolution, seed
  decision/       InputEvent, context, outcome, command bus, reply, verifier
  domain/
    planning/     repository, candidates, evaluator, policy, mutation service
    execution/    activities, claims, evidence, context, recent reality, writes
    memory/       durable facts, profile summary, routing, patterns, maintenance, writes
    athlete/      profile, zones, readiness, load, strength, performance
    coaching/     voice, calibration, digest, week context, adaptation evidence
  llm/            gateway, prompts, understanding, reply backends, compat legacy
  integrations/   Strava et clients externes
  skills/
    heartbeat/    heartbeat runtime, reply composer, tool loop
  tools/          contracts, registry, runtime, metrics
  legacy/         bridges temporaires de migration
```

Root encore accepte :

- `api.py`, `main.py`, `__init__.py` pour l'assemblage app.
- `models.py`, `schema.py` restent les deux monolithes bruts.
- `repository.py` reste en facade temporaire, avec deja extraits :
  `domain/planning/repository.py` pour sessions/audit/decision planning et
  `domain/memory/repository.py` pour facts, working memory et patterns,
  `domain/execution/repository.py` pour activites reelles,
  `domain/athlete/repository.py` pour snapshots fitness/readiness,
  `integrations/repository.py` pour connection/tokens Strava,
  `domain/planning/template_repository.py` pour compat `WeeklyPlan/DayPlan`
  onboarding/template/archive.

Ce qui n'est plus l'architecture active :

- root `api_messages.py`
- root `api_*.py`
- root `telegram_*.py`
- root execution modules (`activities.py`, `execution_*.py`, `recent_reality.py`)
- root memory modules (`availability_constraints.py`, `fact_memory.py`,
  `memory_*.py`, `profile_summary.py`)
- root athlete modules (`athlete_*.py`, `fitness_snapshot.py`,
  `load_projection.py`, `performance_*.py`, `readiness.py`,
  `strength_*.py`, `threshold_estimation.py`, `training_load.py`)
- root coaching modules (`adaptation_log.py`, `calibration_*.py`,
  `coach_reading_digest.py`, `coach_voice.py`,
  `generated_week_coherence.py`, `repo_conversation.py`, `week_context.py`)
- root core modules (`calendar_resolution.py`, `db.py`, `seed.py`,
  `temporal_resolver.py`, `time_context.py`)
- root integration modules (`strava.py`)
- root LLM support modules (`calibration_llm.py`, `prompt_contracts.py`,
  `prompt_observability.py`)
- root planning primitives (`intensity_distribution.py`, `interference.py`,
  `periodization.py`, `planner.py`, `planning_config.py`,
  `planning_decision.py`, `planning_state.py`, `session_similarity.py`,
  `session_templates.py`, `workout_content.py`)
- root planning core modules (`plan_patch.py`, `week_coherence.py`)
- root conversation turn planner (`conversation_turn_planner.py`)
- root planning metadata helpers (`session_metadata.py`, `week_metadata.py`)
- root planning window resolution (`planning_window_resolution.py`)
- root grounding contract (`grounding_contract.py`)
- root claim guard (`claim_guard.py`)
- root conversation contract (`conversation_contract.py`)
- root context pack (`context_pack.py`)
- root conversation context (`conversation_context.py`)
- root conversation prompting (`conversation_prompting.py`)
- root conversation prompt modules (`conversation_prompt_modules.py`)
- root prompt layers (`prompt_layers.py`)
- root conversation prompt builder (`llm_prompt_builder.py`)
- root adaptation decision (`adaptation_decision.py`)
- root planning contract (`planning_contract.py`)
- root plan validator (`plan_validator.py`)
- root coach messages (`coach_messages.py`)
- root coach state bundle (`coach_state_bundle.py`)
- root signals (`signals.py`)
- root adaptation (`adaptation.py`)
- root conversation pipeline (`conversation_pipeline.py`)
- root `final_reply.py`
- root `heartbeat.py`
- root `telegram_scheduler.py`
- root `llm_gateway.py`
- root `tool_*`

## Verites Runtime

| Verite | Source |
| --- | --- |
| Planning visible | `ScheduledSession` |
| Execution reelle | `Activity` + evidence execution |
| Audit planning | `PlanMutationEvent` |
| Audit conversation | `ConversationTurnRecord` |
| Memoire durable | profile memory / `UserFact` transition |
| Memoire courte | working memory |
| Templates historiques | `WeeklyPlan` / `DayPlan` |

Regle dure :

```text
Si le user peut le voir ou si le coach peut agir dessus,
la verite planning vient de ScheduledSession.
```

## Boucle Runtime

```text
Interface event
-> InputEvent
-> CoachContext
-> Understanding LLM
-> decision/domain services
-> command service / mutation service
-> DecisionOutcome
-> reply composer/backend
-> OutputVerifier
-> delivery
```

Interfaces :

- API app : lire, exposer, declencher une action bornee.
- Telegram : livrer/retry/debounce, pas decider.
- Scheduler : produire un event heartbeat, pas un deuxieme coach.
- Ops : debug des artefacts, pas contournement runtime.

## Frontieres

| Couche | Role |
| --- | --- |
| `decision/` | orchestration pure, outcomes, replies, verifier, command bus |
| `domain/planning/` | resolution refs structurees, candidates, simulation, policy |
| `llm/` | provider, prompts, understanding, formulation finale |
| `tools/` | lecture ou validation bornee pour LLM |
| `skills/heartbeat/` | workflow proactif borne |
| `legacy/` | compat temporaire, sortie obligatoire |

Interdits :

- regex/keywords sur texte utilisateur libre en runtime conversation.
- write DB hors writer/command/mutation service.
- reply visible depuis un helper opportuniste.
- nouveau fallback local pour masquer une frontiere floue.
- nouveau module legacy.

## Risque Actuel

Le root runtime conversationnel est supprime. Les premiers owners repository
sont extraits. Les prochains risques sont les monolithes transverses restants :

- `repository.py`, tant qu'il porte encore user/profile facades ;
- `schema.py` ;
- `models.py`.

Critere de succes jeudi :

```text
Moins de chemins runtime.
Moins de legacy appele.
Moins de branches dans les owners `decision/turn_*`.
Plus de bugs localisables par couche.
```

## Verification

```bash
./scripts/docs:list
./scripts/test-backend
```

Smoke core :

```bash
./scripts/smoke-a-plus-api --skip-generated-week \
  --scenario lookup_current_plan \
  --scenario create_easy_free_day \
  --fallback-census-json /tmp/fitmas-core-census.json \
  --timeout 420
```
