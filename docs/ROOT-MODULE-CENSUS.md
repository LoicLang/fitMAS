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

- Root files counted: 19
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
- Primary risk: moving files faster than deleting obsolete boundaries
- Thursday criterion: root is explainable, delete candidates are explicit, and
  new root files fail architecture tests unless classified here

## Classification

| File | Owner cible | Action | Reason | Next slice |
| --- | --- | --- | --- | --- |
| `__init__.py` | root-entrypoint | entrypoint | package marker only | permanent root |
| `adaptation.py` | domain/planning | merge | old adaptation facade overlaps planning runtime | planning simplification |
| `adaptation_decision.py` | domain/planning | merge | decision value object should live with planning decisions | planning simplification |
| `api.py` | root-entrypoint | entrypoint | FastAPI app assembly entrypoint | keep until app package owns all routes |
| `coach_messages.py` | domain/coaching | merge | message fixtures overlap coach voice and reply composer | coaching package split |
| `coach_state_bundle.py` | domain/coaching | merge | old bundle should collapse into CoachContext | coach context shrink |
| `conversation_context.py` | decision | merge | conversation context should be one DecisionRuntime context | decision package split |
| `conversation_pipeline.py` | decision | keep_root_temporarily | hotspot orchestrator is shrinking; PlanPatch replies already moved to `decision/plan_patch_reply.py` | turn state / idempotence / recording shrink |
| `conversation_prompt_modules.py` | llm | merge | prompt fragments should collapse into three prompt families | prompt shrink |
| `conversation_prompting.py` | llm | merge | prompt assembly should move into llm prompts | prompt shrink |
| `llm_prompt_builder.py` | llm | merge | legacy prompt builder should collapse into llm prompts | prompt shrink |
| `main.py` | root-entrypoint | entrypoint | ASGI import entrypoint | permanent root |
| `models.py` | core | keep_root_temporarily | central SQLAlchemy models need a dedicated schema split | model schema split |
| `plan_validator.py` | domain/planning | merge | validation should live with planning policy and mutation service | planning simplification |
| `planning_contract.py` | domain/planning | merge | planning contract should merge with domain planning models | planning simplification |
| `prompt_layers.py` | llm | merge | prompt layering should collapse into canonical prompt families | prompt shrink |
| `repository.py` | core | keep_root_temporarily | monolithic repository needs domain repository split | repository split |
| `schema.py` | core | keep_root_temporarily | central Pydantic schema needs bounded API/domain split | schema split |
| `signals.py` | domain/coaching | merge | signal derivation overlaps context and memory substrates | coaching substrate shrink |

## Immediate Cut Order

1. Move athlete/coaching services to `domain/*` before touching monoliths.
2. Split monoliths only after deletion:
   `conversation_pipeline.py`, `repository.py`, `schema.py`, `models.py`.

## Non Goals

- No broad import churn without deletion.
- No moving legacy bridges to new folders just to make the tree look cleaner.
- No new root module without adding a row here and a deletion or ownership
  plan.
