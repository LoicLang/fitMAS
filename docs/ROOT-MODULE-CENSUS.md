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

- Root files counted: 84
- Permanent root entrypoints allowed: 3
- First wrapper cuts completed: `heartbeat*.py`, `llm_gateway.py`,
  `telegram_scheduler.py`, `tool_*.py`, `api_messages.py`,
  `plan_patch_tools.py`, `state.py`, `final_reply.py`
- Planning candidate root cut completed: `plan_patch_backend_candidates.py`,
  `plan_patch_candidates.py`, `plan_patch_candidate_evaluator.py`,
  `plan_patch_candidate_reviewer.py`, `plan_patch_adaptation_policy.py`
- API root cut completed: `api_activities.py`, `api_app.py`,
  `api_debug.py`, `api_onboarding.py`, `api_ops.py`, `api_payloads.py`,
  `api_plan.py`, `api_read.py`, `api_static.py`, `api_stats.py`,
  `api_support.py`, `app_views.py`, `onboarding_contract.py`
- Telegram root cut completed: `telegram_api.py`, `telegram_bot.py`,
  `telegram_channel.py`, `telegram_commands.py`, `telegram_debounce.py`,
  `telegram_onboarding.py`, `telegram_shared.py`
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
| `conversation_pipeline.py` | decision | keep_root_temporarily | hotspot orchestrator is shrinking; PlanPatch replies already moved to `decision/plan_patch_reply.py` | turn state / idempotence / recording shrink |
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
| `performance_overview.py` | domain/athlete | move | performance overview is athlete analytics | athlete package split |
| `performance_stats.py` | domain/athlete | move | performance stats are athlete analytics | athlete package split |
| `periodization.py` | domain/planning | move | periodization belongs to planning | planning package split |
| `plan_patch.py` | domain/planning | move | PlanPatch is planning domain language | planning package split |
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
| `temporal_resolver.py` | core | move | temporal resolution is shared core | core package split |
| `threshold_estimation.py` | domain/athlete | move | threshold estimation is athlete physiology | athlete package split |
| `time_context.py` | core | move | time helpers are shared core | core package split |
| `training_load.py` | domain/athlete | move | training load is athlete state | athlete package split |
| `week_coherence.py` | domain/planning | move | week coherence is planning quality | planning package split |
| `week_context.py` | domain/coaching | move | week context is coaching context | coaching package split |
| `week_metadata.py` | domain/planning | merge | week label helper belongs with periodization | planning simplification |
| `workout_content.py` | domain/planning | move | workout content belongs to planning/session domain | planning package split |

## Immediate Cut Order

1. Move execution and memory services to `domain/*` before touching monoliths.
2. Split monoliths only after deletion:
   `conversation_pipeline.py`, `repository.py`, `week_coherence.py`.

## Non Goals

- No broad import churn without deletion.
- No moving legacy bridges to new folders just to make the tree look cleaner.
- No new root module without adding a row here and a deletion or ownership
  plan.
