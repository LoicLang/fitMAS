---
summary: root module ownership census and simplification map for backend/src/fitmas
read_when:
  - adding or moving a backend module
  - deleting legacy root files
  - checking whether the repo is getting smaller or only better sorted
---

# Root Module Census

Phase 9Y rule:

```text
No root module is neutral.
Each backend/src/fitmas/*.py file has an owner, a target action and a next cut.
```

This is a simplification map, not a moving checklist. `delete` means the file
is condemned as a product surface and must disappear once imports are cut.
`merge` means useful code remains, but the module boundary should disappear.
`move` means the module is a real bounded-context file. `keep_root_temporarily`
is allowed only for hotspots that need a separate shrink slice.

## Summary

- Root files counted: 113
- Permanent root entrypoints allowed: 3
- First wrapper cuts completed: `heartbeat*.py`, `llm_gateway.py`,
  `telegram_scheduler.py`, `tool_*.py`, `api_messages.py`,
  `plan_patch_tools.py`, `state.py`, `final_reply.py`
- Primary risk: moving files faster than deleting obsolete boundaries
- Thursday criterion: root is explainable, delete candidates are explicit, and
  new root files fail architecture tests unless classified here

## Classification

| File | Owner cible | Action | Reason | Next slice |
| --- | --- | --- | --- | --- |
| `__init__.py` | root-entrypoint | entrypoint | package marker only | permanent root |
| `activities.py` | domain/execution | move | activity ingestion and matching belongs to execution | execution package split |
| `activity_claims.py` | domain/execution | move | user activity claims are execution truth | execution package split |
| `activity_helpers.py` | domain/execution | merge | helper boundary too small for root | merge into execution helpers |
| `adaptation.py` | domain/planning | merge | old adaptation facade overlaps planning runtime | planning simplification |
| `adaptation_decision.py` | domain/planning | merge | decision value object should live with planning decisions | planning simplification |
| `adaptation_log.py` | domain/coaching | move | user-visible adaptation history is coaching evidence | coaching package split |
| `api.py` | root-entrypoint | entrypoint | FastAPI app assembly entrypoint | keep until app package owns all routes |
| `api_activities.py` | app/api | move | API route module | api package split |
| `api_app.py` | app/api | move | app cockpit route module | api package split |
| `api_debug.py` | app/api | move | debug route module | api package split |
| `api_onboarding.py` | app/api | move | onboarding route module | api package split |
| `api_ops.py` | app/api | move | ops route module | api package split |
| `api_payloads.py` | app/api | merge | payload helpers should live beside routes | api package split |
| `api_plan.py` | app/api | move | plan route module | api package split |
| `api_read.py` | app/api | move | app read route module | api package split |
| `api_static.py` | app/api | move | static route module | api package split |
| `api_stats.py` | app/api | move | stats route module | api package split |
| `api_support.py` | app/api | merge | shared API helpers should not stay root | api package split |
| `app_views.py` | app/api | move | read models for cockpit views | api package split |
| `athlete_profile.py` | domain/athlete | move | athlete profile domain model | athlete package split |
| `athlete_zones.py` | domain/athlete | move | zones are athlete physiology | athlete package split |
| `availability_constraints.py` | domain/memory | move | durable availability facts belong with memory | memory package split |
| `calendar_resolution.py` | core | move | date resolution is shared infrastructure | core package split |
| `calibration_llm.py` | llm | move | LLM calibration helper | llm package cleanup |
| `calibration_needs.py` | domain/coaching | move | coach calibration state | coaching package split |
| `calibration_status.py` | domain/coaching | move | coach calibration status | coaching package split |
| `claim_guard.py` | decision | merge | visible claim protection should collapse into OutputVerifier | output verifier shrink |
| `coach_messages.py` | domain/coaching | merge | message fixtures overlap coach voice and reply composer | coaching package split |
| `coach_reading_digest.py` | domain/coaching | move | digest is coaching context | coaching package split |
| `coach_state_bundle.py` | domain/coaching | merge | old bundle should collapse into CoachContext | coach context shrink |
| `coach_voice.py` | domain/coaching | move | voice rules are coaching domain policy | coaching package split |
| `context_pack.py` | decision | merge | prompt context pack overlaps Decision ContextBuilder | context builder shrink |
| `conversation_context.py` | decision | merge | conversation context should be one DecisionRuntime context | decision package split |
| `conversation_contract.py` | decision | merge | conversation contracts should be canonical outcome contracts | decision package split |
| `conversation_pipeline.py` | decision | keep_root_temporarily | hotspot orchestrator must shrink before moving | conversation adapter shrink |
| `conversation_prompt_modules.py` | llm | merge | prompt fragments should collapse into three prompt families | prompt shrink |
| `conversation_prompting.py` | llm | merge | prompt assembly should move into llm prompts | prompt shrink |
| `conversation_turn_planner.py` | decision | move | typed turn planning belongs to decision | decision package split |
| `db.py` | core | move | DB session and engine are core infrastructure | core package split |
| `execution_clarification.py` | domain/execution | move | execution ambiguity belongs to execution domain | execution package split |
| `execution_context.py` | domain/execution | move | execution context belongs to execution domain | execution package split |
| `execution_evidence.py` | domain/execution | move | execution evidence belongs to execution domain | execution package split |
| `execution_mutation_service.py` | domain/execution | move | execution writes need a domain service | execution package split |
| `fact_memory.py` | domain/memory | move | fact normalization belongs to memory | memory package split |
| `fitness_snapshot.py` | domain/athlete | move | fitness snapshot is athlete state | athlete package split |
| `generated_week_coherence.py` | domain/coaching | move | generated week review is coaching context | coaching package split |
| `grounding_contract.py` | decision | merge | grounding should be part of reply request and verifier | output verifier shrink |
| `intensity_distribution.py` | domain/planning | move | intensity distribution is planning quality | planning package split |
| `interference.py` | domain/planning | move | sport interference is planning policy | planning package split |
| `llm_prompt_builder.py` | llm | merge | legacy prompt builder should collapse into llm prompts | prompt shrink |
| `load_projection.py` | domain/athlete | move | load projection is athlete state | athlete package split |
| `main.py` | root-entrypoint | entrypoint | ASGI import entrypoint | permanent root |
| `memory_maintenance.py` | domain/memory | move | memory cleanup belongs to memory domain | memory package split |
| `memory_mutation_service.py` | domain/memory | move | memory writes need a domain service | memory package split |
| `memory_patterns.py` | domain/memory | move | learned patterns belong to memory domain | memory package split |
| `memory_profile.py` | domain/memory | merge | thin repository wrapper should vanish | memory package split |
| `memory_routing.py` | domain/memory | move | memory routing belongs to memory domain | memory package split |
| `models.py` | core | keep_root_temporarily | central SQLAlchemy models need a dedicated schema split | model schema split |
| `mutation_hooks.py` | domain/planning | move | mutation side effects belong with planning commands | planning package split |
| `mutation_permissions.py` | domain/planning | move | mutation permissions are planning policy | planning package split |
| `mutations.py` | domain/planning | merge | old mutation helpers overlap PlanningCommandService | planning simplification |
| `onboarding_contract.py` | app/api | move | onboarding API contract belongs with app/onboarding | api package split |
| `performance_overview.py` | domain/athlete | move | performance overview is athlete analytics | athlete package split |
| `performance_stats.py` | domain/athlete | move | performance stats are athlete analytics | athlete package split |
| `periodization.py` | domain/planning | move | periodization belongs to planning | planning package split |
| `plan_patch.py` | domain/planning | move | PlanPatch is planning domain language | planning package split |
| `plan_patch_adaptation_policy.py` | domain/planning | move | adaptation policy belongs to planning | planning package split |
| `plan_patch_backend_candidates.py` | domain/planning | merge | backend candidate helper should merge into candidate_builder | planning simplification |
| `plan_patch_candidate_evaluator.py` | domain/planning | merge | evaluator duplicates domain planning evaluator boundary | planning simplification |
| `plan_patch_candidate_reviewer.py` | domain/planning | merge | reviewer should live behind planning reviewer prompt | planning simplification |
| `plan_patch_candidates.py` | domain/planning | merge | candidate contracts should collapse into domain planning models | planning simplification |
| `plan_validator.py` | domain/planning | merge | validation should live with planning policy and mutation service | planning simplification |
| `planner.py` | domain/planning | move | planner belongs to planning domain | planning package split |
| `planning_config.py` | domain/planning | move | planning configuration belongs to planning | planning package split |
| `planning_contract.py` | domain/planning | merge | planning contract should merge with domain planning models | planning simplification |
| `planning_decision.py` | domain/planning | move | planning decision model belongs to planning | planning package split |
| `planning_state.py` | domain/planning | move | planning state belongs to planning | planning package split |
| `planning_window_resolution.py` | domain/planning | merge | window resolver should merge into ReferenceResolver | planning simplification |
| `profile_summary.py` | domain/memory | move | compact profile summary belongs to memory | memory package split |
| `prompt_contracts.py` | llm | move | prompt contracts belong under llm | llm package cleanup |
| `prompt_layers.py` | llm | merge | prompt layering should collapse into canonical prompt families | prompt shrink |
| `prompt_observability.py` | llm | move | prompt telemetry belongs under llm | llm package cleanup |
| `readiness.py` | domain/athlete | move | readiness is athlete state | athlete package split |
| `recent_reality.py` | domain/execution | move | recent reality is execution substrate | execution package split |
| `repo_conversation.py` | domain/coaching | move | conversation persistence should leave monolithic repository | repository split |
| `repository.py` | core | keep_root_temporarily | monolithic repository needs domain repository split | repository split |
| `schema.py` | core | keep_root_temporarily | central Pydantic schema needs bounded API/domain split | schema split |
| `seed.py` | core | move | seed data is infrastructure and fixtures | core package split |
| `session_metadata.py` | domain/planning | merge | load band helper belongs with session/timeline models | planning simplification |
| `session_similarity.py` | domain/planning | move | session matching similarity is planning/execution boundary | planning package split |
| `session_templates.py` | domain/planning | move | session templates belong to planning | planning package split |
| `signals.py` | domain/coaching | merge | signal derivation overlaps context and memory substrates | coaching substrate shrink |
| `strava.py` | integrations | move | external Strava client belongs to integrations | integration package split |
| `strength_engine.py` | domain/athlete | move | strength engine is athlete capability | athlete package split |
| `strength_exercise_bank.py` | domain/athlete | move | strength exercise bank is athlete capability data | athlete package split |
| `strength_signals.py` | domain/athlete | move | strength signals are athlete state | athlete package split |
| `telegram_api.py` | app/telegram | move | Telegram API client belongs to telegram app | telegram package split |
| `telegram_bot.py` | app/telegram | move | Telegram bot entry belongs to telegram app | telegram package split |
| `telegram_channel.py` | app/telegram | move | Telegram delivery channel belongs to telegram app | telegram package split |
| `telegram_commands.py` | app/telegram | move | Telegram commands belong to telegram app | telegram package split |
| `telegram_debounce.py` | app/telegram | move | Telegram debounce belongs to telegram app | telegram package split |
| `telegram_onboarding.py` | app/telegram | move | Telegram onboarding belongs to telegram app | telegram package split |
| `telegram_shared.py` | app/telegram | move | Telegram shared helpers belong to telegram app | telegram package split |
| `temporal_resolver.py` | core | move | temporal resolution is shared core | core package split |
| `threshold_estimation.py` | domain/athlete | move | threshold estimation is athlete physiology | athlete package split |
| `time_context.py` | core | move | time helpers are shared core | core package split |
| `training_load.py` | domain/athlete | move | training load is athlete state | athlete package split |
| `week_coherence.py` | domain/planning | move | week coherence is planning quality | planning package split |
| `week_context.py` | domain/coaching | move | week context is coaching context | coaching package split |
| `week_metadata.py` | domain/planning | merge | week label helper belongs with periodization | planning simplification |
| `workout_content.py` | domain/planning | move | workout content belongs to planning/session domain | planning package split |

## Immediate Cut Order

1. Merge old planning candidate modules into `domain/planning` instead of
   preserving wrapper boundaries.
2. Move API routes to `app/api` and delete root wrappers.
3. Split monoliths only after deletion:
   `conversation_pipeline.py`, `repository.py`, `week_coherence.py`.

## Non Goals

- No broad import churn without deletion.
- No moving legacy bridges to new folders just to make the tree look cleaner.
- No new root module without adding a row here and a deletion or ownership
  plan.
