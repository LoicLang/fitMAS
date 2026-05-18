---
summary: delivered plan for Decision Runtime Phase 8U planning provider default-on
read_when:
  - checking why FITMAS_CANONICAL_PLANNING_PROVIDER is default-on
  - debugging canonical planning provider traces
  - preparing Phase 8V fallback reduction
---

# Decision Runtime Phase 8U Planning Provider Default-On

## Status

Delivered locally on 2026-05-17.

8U-A / 8U-B / 8U-C were implemented together:

- 8U-A: `FITMAS_CANONICAL_PLANNING_PROVIDER` is default-on with opt-out `0`.
- 8U-B: supported planning turns must leave canonical handled traces.
- 8U-C: default-on real smoke wrapper exists without exporting the provider flag.

Latency is not a product gate for this slice. Reliability and artifact honesty
win.

## Changes

- `legacy/conversation_canonical_planning_bridge.py`
  - provider default is now `True`;
  - trace states are explicit: `prepared`, `handled`, `blocked`,
    `fallback_legacy`;
  - fallback reasons are recorded.
- `legacy/conversation_understanding_bridge.py`
  - planning Understanding runs by default for planning turns.
- `conversation_pipeline.py`
  - prepares canonical planning traces before legacy/candidate fallbacks.
- `llm/understanding_service.py`
  - normalizes typed provider refs:
    `session_3`, `date_YYYY-MM-DD`, `day:YYYY-MM-DD`, raw ISO dates;
  - fills missing `requested_change.source_ref` from typed
    `extracted_signals.payload.target_session_id`.
- `domain/planning/reference_resolver.py`
  - accepts the same typed machine aliases without parsing free user text.
- `legacy/conversation_pending_bridge.py`
  - treats conditional confirmations like
    `oui je confirme si tu penses que c'est propre` as acceptance, while
    keeping backend validation before write.
- `scripts/smoke_a_plus_api.py`
  - loads `conversation_turns.context_json`;
  - fails supported default-on planning turns that do not use canonical traces.
- `scripts/smoke-decision-runtime-canonical-planning-default`
  - runs default-on unit gates and real API/LLM planning smoke without
    exporting `FITMAS_CANONICAL_PLANNING_PROVIDER=1`.

## Verification

```bash
./scripts/test-backend -q tests/test_conversation_canonical_planning_bridge.py tests/test_conversation_understanding_bridge.py tests/test_llm_understanding_service.py tests/test_domain_planning_reference_resolver.py tests/test_conversation_pending_bridge.py::ConversationPendingBridgeTest::test_pending_recheck_prompt_treats_coach_judgment_condition_as_acceptance tests/test_smoke_a_plus_api.py tests/test_phase8t_canonical_planning_provider_architecture.py
# 70 passed

./scripts/smoke-decision-runtime-canonical-planning-provider
# RESULT: OK

./scripts/smoke-decision-runtime-canonical-planning-default
# RESULT: OK (9 check(s))
```

## Next

Move to 8V if the goal is to reduce legacy planning fallback.

8V should not remove fallback blindly. It should first classify each remaining
`fallback_legacy` reason and only shrink lanes where typed refs and backend
policy are already trustworthy.
