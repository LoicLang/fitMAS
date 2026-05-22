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

- Root files counted: 5
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
- Execution root cut completed: `activities.py`, `activity_claims.py`,
  `activity_helpers.py`, `execution_clarification.py`,
  `execution_context.py`, `execution_evidence.py`,
  `execution_mutation_service.py`, `recent_reality.py`
- Memory root cut completed: `availability_constraints.py`,
  `fact_memory.py`, `memory_maintenance.py`,
  `memory_mutation_service.py`, `memory_patterns.py`,
  `memory_profile.py`, `memory_routing.py`, `profile_summary.py`
- Athlete root cut completed: `athlete_profile.py`, `athlete_zones.py`,
  `fitness_snapshot.py`, `load_projection.py`, `performance_overview.py`,
  `performance_stats.py`, `readiness.py`, `strength_engine.py`,
  `strength_exercise_bank.py`, `strength_signals.py`,
  `threshold_estimation.py`, `training_load.py`
- Coaching root cut completed: `adaptation_log.py`, `calibration_needs.py`,
  `calibration_status.py`, `coach_reading_digest.py`, `coach_voice.py`,
  `generated_week_coherence.py`, `repo_conversation.py`, `week_context.py`
- Core/integration root cut completed: `calendar_resolution.py`, `db.py`,
  `seed.py`, `temporal_resolver.py`, `time_context.py`, `strava.py`
- LLM support root cut completed: `calibration_llm.py`,
  `prompt_contracts.py`, `prompt_observability.py`
- Planning primitive root cut completed: `intensity_distribution.py`,
  `interference.py`, `periodization.py`, `planner.py`,
  `planning_config.py`, `planning_decision.py`, `planning_state.py`,
  `session_similarity.py`, `session_templates.py`, `workout_content.py`
- Planning core root cut completed: `plan_patch.py`, `week_coherence.py`
- Decision root cut completed: `conversation_turn_planner.py`
- Planning metadata root modules merged and deleted: `session_metadata.py`,
  `week_metadata.py`
- Planning window resolution root cut completed:
  `planning_window_resolution.py`
- Decision grounding root cut completed: `grounding_contract.py`
- Decision output verification root cut completed: `claim_guard.py`
- Decision conversation contract root cut completed:
  `conversation_contract.py`
- Decision context pack root cut completed: `context_pack.py`
- Decision conversation context root cut completed: `conversation_context.py`
- LLM prompt policy root cut completed: `conversation_prompting.py`
- LLM prompt layers root cut completed: `prompt_layers.py`
- LLM conversation system prompt root cut completed:
  `conversation_prompt_modules.py`
- LLM conversation prompt builder root cut completed: `llm_prompt_builder.py`
- Planning adaptation decision root cut completed: `adaptation_decision.py`
- Planning contract root cut completed: `planning_contract.py`
- Planning validator root cut completed: `plan_validator.py`
- Telegram delivery root cut completed: `coach_messages.py`
- Coaching state bundle root cut completed: `coach_state_bundle.py`
- Coaching signals root cut completed: `signals.py`
- Planning adaptation root cut completed: `adaptation.py`
- Decision conversation pipeline root cut completed: `conversation_pipeline.py`
- Planning repository extraction completed:
  `domain/planning/repository.py` owns `ScheduledSession` runtime reads/writes
  `PlanMutationEvent` audit writes and `PlanningDecisionRecord`.
- Memory repository extraction completed:
  `domain/memory/repository.py` owns profile facts, working memory and pattern
  storage.
- Execution repository extraction completed:
  `domain/execution/repository.py` owns `Activity` reads, conversion and
  writes.
- Athlete repository extraction completed:
  `domain/athlete/repository.py` owns user/profile facades, user sports /
  constraints / preferences and fitness/readiness snapshot storage.
- Integration repository extraction completed:
  `integrations/repository.py` owns Strava connection, token and sync metadata.
- Planning template repository extraction completed:
  `domain/planning/template_repository.py` owns `WeeklyPlan` / `DayPlan`
  onboarding, template and archive compatibility.
- Coaching repository extraction completed:
  `domain/coaching/repository.py` owns adaptation event conversion and storage.
- Root repository deleted:
  root `repository.py` no longer exists; source, tests and scripts import the
  real owner repositories directly.
- Primary risk: moving files faster than deleting obsolete boundaries
- Thursday criterion: root is explainable, delete candidates are explicit, and
  new root files fail architecture tests unless classified here

## Classification

| File | Owner cible | Action | Reason | Next slice |
| --- | --- | --- | --- | --- |
| `__init__.py` | root-entrypoint | entrypoint | package marker only | permanent root |
| `api.py` | root-entrypoint | entrypoint | FastAPI app assembly entrypoint | keep until app package owns all routes |
| `main.py` | root-entrypoint | entrypoint | ASGI import entrypoint | permanent root |
| `models.py` | core | keep_root_temporarily | central SQLAlchemy models need a dedicated schema split | model schema split |
| `schema.py` | core | keep_root_temporarily | central Pydantic schema needs bounded API/domain split | schema split |

## Immediate Cut Order

1. Keep only root entrypoints plus bounded monoliths in root.
2. Next cuts target the bounded monoliths only:
   `schema.py`, `models.py`.

## Non Goals

- No broad import churn without deletion.
- No moving legacy bridges to new folders just to make the tree look cleaner.
- No new root module without adding a row here and a deletion or ownership
  plan.
