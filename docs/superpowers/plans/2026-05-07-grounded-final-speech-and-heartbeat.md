---
summary: long-term grounding plan for final coach replies and heartbeat factual truth
read_when:
  - correcting coach factual contradictions in conversation or heartbeat
  - modifying final_reply.py factual verifiers
  - modifying conversation temporal grounding or idempotency
  - modifying heartbeat future plan context
---

# Grounded Final Speech And Heartbeat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop FitMAS from contradicting committed planning truth in final conversation replies and proactive heartbeat messages, without adding deterministic free-text parsing or more prompt clutter.

**Architecture:** Introduce a small shared grounding layer that turns LLM intent + DB truth into typed machine artifacts: temporal references, plan windows, event facts, and reply contracts. User text is still understood only by LLMs; deterministic code only resolves typed artifacts and verifies structured outputs. Final user-facing text is composed and semantically verified against machine facts, not against keyword/token heuristics.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy, SQLite, Pydantic contracts, existing `final_reply.py`, heartbeat role/tool loop, pytest via `./scripts/test-backend`.

**Status 2026-05-07:** core slice implemented locally. Delivered:
`grounding_contract.py`, typed planner refs/truth flags, durable
`client_message_key`, semantic LLM factual verifier for grounded plan lookup,
grounded PlanPatch confirmation speech, post-event pending acceptance, close
turn grounding, and heartbeat `PlanWindowTruth`. Remaining follow-up is not a
bug patch: run P1-octies prompt/context audit, especially to reduce
`decide() returned None` without adding deterministic free-text parsers.

---

## Problem Map

Observed prod facts:

- Turn 84 blocked Friday via old `protected_recovery`; already fixed by commit `3f30173`.
- Turns 85/86 processed the same user text twice and created two competing pending confirmations.
- Turn 86 confirmation composer hallucinated `mardi (aujourd'hui)` even though DB/time truth said Wednesday 2026-05-06.
- Turn 87 accepted the correct pending and committed `move_session id=46: 2026-05-07 -> 2026-05-08`.
- Turn 88 terminal close added `Tu souffles aujourd'hui`, a new factual claim on a close turn.
- Morning heartbeat saw Thursday correctly but claimed Friday was empty while DB had Friday running 40 min.
- Turn 90 user challenge was routed `needs_clarification`, not factual recheck / plan lookup, so strict factual composer did not apply.

Primary root causes:

- `conversation_context.build_conversation_context()` does not pass user text into temporal resolution, and the existing raw-text resolver is not doctrine-compliant for conversation runtime.
- Final composers for confirmation / pending accepted / close turn do not receive enough structured DB facts to verify day/date/session claims.
- Heartbeat truth bundle has `YesterdayTruth`, `TodayTruth`, `WeekDigest`, but no authoritative future `PlanWindowTruth`.
- Conversation idempotency key is stored in `turn_context`, then `turn_context` is overwritten before persistence.
- Current `plan_lookup` guard compares deterministic fact tokens between LLM drafts; this is brittle and not the architecture we want.

## File Structure

- Create `backend/src/fitmas/grounding_contract.py`
  - Typed contracts for `TemporalIntent`, `PlanWindowFact`, `ReplyGroundingPacket`, `GroundingRequirement`, and render helpers.
- Modify `backend/src/fitmas/conversation_turn_planner.py`
  - Extend the LLM planner output with typed temporal references and truth-request flags.
- Modify `backend/src/fitmas/conversation_pipeline.py`
  - Preserve external idempotency metadata, build grounding packets, route reality checks to factual final composer, and use post-event composer after pending accept.
- Modify `backend/src/fitmas/final_reply.py`
  - Replace deterministic plan-lookup token guard with LLM semantic verifier against grounding packets.
- Modify `backend/src/fitmas/skills/heartbeat/context.py`
  - Add `PlanWindowTruth` to heartbeat bundle.
- Modify `backend/src/fitmas/skills/heartbeat/roles.py`
  - Render future plan truth as source, not prose rules.
- Modify `backend/src/fitmas/skills/heartbeat/heartbeat.py`
  - Load and trace future plan window for morning briefing.
- Modify `backend/src/fitmas/repo_conversation.py`, `backend/src/fitmas/schema.py`, migration-safe DB bootstrap if needed
  - Add durable `client_message_key` field with idempotency lookup; keep context fallback for compatibility.
- Tests:
  - `tests/test_grounding_contract.py`
  - `tests/test_conversation_temporal_grounding.py`
  - `tests/test_conversation_idempotency.py`
  - `tests/test_final_reply_grounded_verifier.py`
  - `tests/test_heartbeat_plan_window_truth.py`
  - Extend existing `tests/test_core_flows.py`, `tests/test_final_reply.py`, `tests/test_conversation_turn_planner.py`.

---

### Task 1: Typed Temporal Intent From The LLM Planner

**Files:**
- Modify: `backend/src/fitmas/conversation_turn_planner.py`
- Create: `tests/test_conversation_temporal_grounding.py`

- [ ] **Step 1: Write failing tests for typed temporal references**

```python
from fitmas.conversation_turn_planner import ConversationTurnPlan

def test_turn_plan_can_carry_typed_temporal_references():
    plan = ConversationTurnPlan(
        primary_intent="plan_mutation",
        user_goal="move tomorrow session to friday",
        mutation_signal=True,
        temporal_references=[
            {"kind": "relative_day", "value": "tomorrow", "role": "source"},
            {"kind": "weekday", "value": "friday", "role": "target"},
        ],
        confidence=0.91,
    )

    assert plan.temporal_references[0]["kind"] == "relative_day"
    assert plan.temporal_references[1]["value"] == "friday"
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
./scripts/test-backend tests/test_conversation_temporal_grounding.py -q
```

Expected: fails because `temporal_references` is not accepted by `ConversationTurnPlan`.

- [ ] **Step 3: Extend the planner schema**

Add fields:

```python
class ConversationTurnPlan(BaseModel):
    primary_intent: str
    secondary_intents: tuple[str, ...] = ()
    user_goal: str = ""
    mutation_signal: bool = False
    execution_claim: dict[str, Any] | None = None
    temporal_references: tuple[dict[str, Any], ...] = ()
    requires_truth_read: bool = False
    truth_scope: str | None = None
    needs_clarification: bool = False
    clarification_question: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
```

- [ ] **Step 4: Update the planner JSON contract, not with many rules**

Add to the existing JSON example:

```json
"temporal_references": [
  {"kind":"relative_day|weekday|date|part_of_day","value":"tomorrow|friday|YYYY-MM-DD|evening","role":"source|target|context"}
],
"requires_truth_read": false,
"truth_scope": "current_plan|previous_coach_claim|today|tomorrow|week|null"
```

Add only two few-shots:

```text
"On est mercredi aujourd'hui et je veux déplacer celle de demain jeudi à vendredi"
-> temporal_references=[today=wednesday context, tomorrow source, thursday source, friday target]

"T'es sûr du planning que tu m'annonces ?"
-> primary_intent=plan_lookup, requires_truth_read=true, truth_scope=previous_coach_claim
```

- [ ] **Step 5: Run planner tests**

Run:

```bash
./scripts/test-backend tests/test_conversation_turn_planner.py tests/test_conversation_temporal_grounding.py -q
```

Expected: pass.

---

### Task 2: Grounding Contract Module

**Files:**
- Create: `backend/src/fitmas/grounding_contract.py`
- Create: `tests/test_grounding_contract.py`

- [ ] **Step 1: Write tests for resolving typed temporal references**

```python
from datetime import date

from fitmas.grounding_contract import resolve_temporal_intents

def test_resolve_typed_relative_and_weekday_references():
    refs = (
        {"kind": "relative_day", "value": "tomorrow", "role": "source"},
        {"kind": "weekday", "value": "friday", "role": "target"},
    )

    resolved = resolve_temporal_intents(refs, local_date=date(2026, 5, 6))

    assert resolved["source"][0].iso_date == "2026-05-07"
    assert resolved["source"][0].day_label == "jeudi"
    assert resolved["target"][0].iso_date == "2026-05-08"
    assert resolved["target"][0].day_label == "vendredi"
```

- [ ] **Step 2: Implement typed resolution only**

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from fitmas.time_context import DAY_KEYS, DAY_LABELS_FR

@dataclass(frozen=True, slots=True)
class ResolvedTemporalReference:
    role: str
    kind: str
    value: str
    iso_date: str | None
    day_key: str | None
    day_label: str | None

def resolve_temporal_intents(
    refs: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    *,
    local_date: date,
) -> dict[str, tuple[ResolvedTemporalReference, ...]]:
    grouped: dict[str, list[ResolvedTemporalReference]] = {}
    for ref in refs or ():
        resolved = _resolve_one(ref, local_date=local_date)
        grouped.setdefault(resolved.role, []).append(resolved)
    return {key: tuple(value) for key, value in grouped.items()}
```

Implement `_resolve_one()` for `relative_day`, `weekday`, `date`. It must not inspect raw user text.

- [ ] **Step 3: Add plan window facts**

```python
@dataclass(frozen=True, slots=True)
class PlanWindowFact:
    session_id: int | None
    iso_date: str
    day_label: str
    sport_type: str
    session_title: str
    duration_min: int | None
    completion_status: str
    slot: str

@dataclass(frozen=True, slots=True)
class ReplyGroundingPacket:
    local_date: str
    temporal_references: tuple[ResolvedTemporalReference, ...] = ()
    plan_window: tuple[PlanWindowFact, ...] = ()
    committed_events: tuple[str, ...] = ()
    blocked_events: tuple[str, ...] = ()
```

- [ ] **Step 4: Run grounding tests**

Run:

```bash
./scripts/test-backend tests/test_grounding_contract.py -q
```

Expected: pass.

---

### Task 3: Durable Idempotency Metadata

**Files:**
- Modify: `backend/src/fitmas/schema.py`
- Modify: `backend/src/fitmas/db.py`
- Modify: `backend/src/fitmas/repo_conversation.py`
- Modify: `backend/src/fitmas/conversation_pipeline.py`
- Test: `tests/test_conversation_idempotency.py`

- [ ] **Step 1: Write failing test proving context metadata survives**

```python
def test_client_message_key_is_preserved_in_conversation_turn(test_db, onboarded_user, deps):
    reply = run_conversation_turn(
        ConversationTurnInput(text="Okay", client_message_key="telegram:1:99", source="telegram"),
        db=test_db,
        dependencies=deps.with_close_turn(),
    )

    row = repo.get_recent_conversation_turns(test_db, onboarded_user.id, limit=1)[0]
    assert row.client_message_key == "telegram:1:99"
```

- [ ] **Step 2: Add DB fields**

Add nullable columns:

```python
client_message_key: Mapped[str | None] = mapped_column(String(128), nullable=True, default=None)
source: Mapped[str | None] = mapped_column(String(32), nullable=True, default=None)
```

Keep existing `context_json` fallback during migration.

- [ ] **Step 3: Fix pipeline context overwrite**

Rename the early metadata:

```python
external_context = {}
if payload.client_message_key:
    external_context["client_message_key"] = payload.client_message_key
if payload.source:
    external_context["source"] = payload.source
```

When building the main `turn_context`, start with:

```python
turn_context = {
    **external_context,
    "profile_summary": ...,
}
```

- [ ] **Step 4: Store and lookup by column**

Update `repo_conversation.add_conversation_turn()` and `get_conversation_turn_by_client_message_key()` to use the column first, then fallback to context JSON.

- [ ] **Step 5: Run idempotency tests**

Run:

```bash
./scripts/test-backend tests/test_conversation_idempotency.py -q
```

Expected: duplicate same `client_message_key` returns the original turn and creates no new pending.

---

### Task 4: Stable Pending Confirmation Identity

**Files:**
- Modify: `backend/src/fitmas/conversation_pipeline.py`
- Test: `tests/test_core_flows.py`

- [ ] **Step 1: Write failing test for duplicate equivalent pending**

```python
def test_equivalent_plan_patch_does_not_supersede_existing_pending(test_db, onboarded_user, deps):
    first = run_conversation_turn(
        ConversationTurnInput(text="Réessaye d’échanger", client_message_key="telegram:1:1", source="telegram"),
        db=test_db,
        dependencies=deps.plan_patch_requires_confirmation(target_session_id=46, target_date="2026-05-08"),
    )
    second = run_conversation_turn(
        ConversationTurnInput(text="Réessaye d’échanger", client_message_key="telegram:1:2", source="telegram"),
        db=test_db,
        dependencies=deps.plan_patch_requires_confirmation(target_session_id=46, target_date="2026-05-08"),
    )

    pendings = repo.get_pending_mutation_confirmations_for_user(test_db, onboarded_user.id)
    assert [p.status for p in pendings].count("pending") == 1
    assert "mardi" not in second.assistant_message.text.lower()
```

- [ ] **Step 2: Compare pending patches as machine artifacts**

Add helper:

```python
def _plan_patch_equivalent_to_pending(patch: PlanPatch, pending_confirmation) -> bool:
    if pending_confirmation is None:
        return False
    if str(pending_confirmation.mutation_type or "") != "plan_patch":
        return False
    existing = deserialize_plan_patch_confirmation(pending_confirmation.decision_json)
    return _canonical_plan_patch(existing) == _canonical_plan_patch(patch)
```

Canonicalize only operation type, session ids, dates, new fields. Ignore prose.

- [ ] **Step 3: Reuse existing pending instead of superseding**

Before `repo.create_pending_mutation_confirmation()`, if equivalent pending exists:

```python
reply_text = _compose_pending_reminder_reply(existing_pending, service_result)
outcome = ConversationTurnOutcome(
    extraction=Extraction(confidence=0.85),
    reply_text=reply_text,
    response_mode="plan_patch_confirmation_existing",
    mutation_applied=False,
    pending_confirmation=True,
    pending_confirmation_id=existing_pending.id,
)
```

The reminder composer must receive the same grounding packet as confirmation, not free text.

- [ ] **Step 4: Run duplicate pending tests**

Run:

```bash
./scripts/test-backend tests/test_core_flows.py::test_equivalent_plan_patch_does_not_supersede_existing_pending -q
```

Expected: pass.

---

### Task 5: Grounded Confirmation And Pending-Accept Replies

**Files:**
- Modify: `backend/src/fitmas/conversation_pipeline.py`
- Modify: `backend/src/fitmas/final_reply.py`
- Test: `tests/test_final_reply_grounded_verifier.py`

- [ ] **Step 1: Write failing test for confirmation hallucinated weekday**

```python
def test_confirmation_reply_is_verified_against_patch_grounding():
    packet = ReplyGroundingPacket(
        local_date="2026-05-06",
        plan_window=(
            PlanWindowFact(46, "2026-05-07", "jeudi", "running", "Footing 40", 40, "planned", "training"),
            PlanWindowFact(33, "2026-05-08", "vendredi", "rest", "Repos", None, "planned", "free_flexible"),
        ),
    )

    reply = final_reply.verify_factual_reply(
        "ta semaine devient mardi aujourd'hui / jeudi rien / vendredi sortie",
        grounding=packet,
        request_text_fn=fake_verifier_repairing_to("Jeudi repos, vendredi footing. Tu confirmes ?"),
    )

    assert "mardi" not in reply.lower()
    assert "vendredi footing" in reply.lower()
```

- [ ] **Step 2: Add semantic factual verifier**

Create prompt builder in `final_reply.py`:

```python
def build_factual_reply_verifier_prompt(reply: str, grounding: ReplyGroundingPacket) -> tuple[str, str]:
    ...
```

Verifier returns:

```json
{"verdict":"allow|repair","reason":"short","repaired_reply":"..."}
```

It compares outgoing reply to `ReplyGroundingPacket`. No regex token extraction.

- [ ] **Step 3: Use grounded composer for `_build_plan_patch_confirmation_prompt()`**

Replace context that only has `Patch coach_message` with:

```python
grounding = _grounding_packet_for_plan_patch(service_result, local_date=...)
context = FinalReplyContext(
    pending_summary=summary,
    allowed_to_claim_mutation=False,
    pipeline="conversation",
    pipeline_capability="can_confirm",
    extra_facts=render_grounding_packet_for_prompt(grounding),
)
composed = final_reply.compose_final_reply(context)
verified = final_reply.verify_factual_reply(composed, grounding=grounding)
```

- [ ] **Step 4: Use post-event composer after pending accept**

In `_accept_pending_confirmation()`, replace:

```python
reply_text=_applied_patch_summary(service_result, fallback=patch.coach_message)
```

with the same path as normal applied `PlanPatch`:

```python
reply_text=_applied_plan_patch_reply(service_result, fallback=patch.coach_message)
```

Then verify against event snapshots.

- [ ] **Step 5: Run final reply tests**

Run:

```bash
./scripts/test-backend tests/test_final_reply.py tests/test_final_reply_grounded_verifier.py -q
```

Expected: pass.

---

### Task 6: Replace Plan-Lookup Token Guard With Grounded LLM Verifier

**Files:**
- Modify: `backend/src/fitmas/final_reply.py`
- Modify: `backend/src/fitmas/conversation_pipeline.py`
- Test: `tests/test_final_reply_grounded_verifier.py`

- [ ] **Step 1: Write failing test for token-guard replacement**

```python
def test_plan_lookup_reply_verified_against_db_grounding_not_original_draft():
    grounding = ReplyGroundingPacket(
        local_date="2026-05-07",
        plan_window=(
            PlanWindowFact(47, "2026-05-07", "jeudi", "rest", "Repos flexible", None, "adapted", "free_flexible"),
            PlanWindowFact(46, "2026-05-08", "vendredi", "running", "Footing endurance — 40 min Z2", 40, "adapted", "training"),
        ),
    )

    reply = final_reply.compose_plan_lookup_reply(
        user_text="T'es sûr du planning que tu m'annonces ?",
        original_llm_reply="Aujourd'hui repos, demain footing 40 min Z2.",
        grounding=grounding,
        request_text_fn=fake_composer("Repos aujourd'hui, footing 40 min Z2 demain."),
        verifier_text_fn=fake_verifier_allow(),
    )

    assert reply == "Repos aujourd'hui, footing 40 min Z2 demain."
```

- [ ] **Step 2: Change function signature**

```python
def compose_plan_lookup_reply(
    *,
    user_text: str,
    original_llm_reply: str,
    grounding: ReplyGroundingPacket,
    ...
) -> str | None:
```

- [ ] **Step 3: Remove `_plan_lookup_fact_tokens()` from the normal path**

Keep deterministic length/voice checks, but factuality goes through `verify_factual_reply()`.

- [ ] **Step 4: Build plan lookup grounding packet in pipeline**

For `plan_lookup` and `requires_truth_read`, include today through next 7 days from `state.scheduled_sessions`.

- [ ] **Step 5: Run factual composer tests**

Run:

```bash
./scripts/test-backend tests/test_final_reply_grounded_verifier.py tests/test_core_flows.py -q
```

Expected: no factual drift and no question on lookup replies.

---

### Task 7: Reality Check Lane

**Files:**
- Modify: `backend/src/fitmas/conversation_turn_planner.py`
- Modify: `backend/src/fitmas/conversation_pipeline.py`
- Test: `tests/test_conversation_turn_planner.py`
- Test: `tests/test_core_flows.py`

- [ ] **Step 1: Write failing planner test**

```python
def test_user_challenges_previous_planning_message_routes_to_plan_lookup():
    plan = fake_plan_turn("T'es sûr du planning que tu m'annonces ?")

    assert plan.primary_intent == "plan_lookup"
    assert plan.requires_truth_read is True
    assert plan.truth_scope == "previous_coach_claim"
```

- [ ] **Step 2: Add minimal planner examples**

Add examples to `_SYSTEM`:

```text
- "T'es sûr du planning que tu m'annonces ?" -> plan_lookup, requires_truth_read=true, truth_scope=previous_coach_claim.
- "C'est pas ce qui est sur mon planning" -> plan_lookup, requires_truth_read=true, truth_scope=current_plan.
```

- [ ] **Step 3: Pipeline capability mapping**

Treat `requires_truth_read=True` as `plan_lookup` for final composer even if primary intent comes back `needs_clarification` during provider drift:

```python
capability = "plan_lookup" if _turn_context_requires_truth_read(turn_context) else ...
```

This uses an LLM artifact, not user text.

- [ ] **Step 4: Run reality check tests**

Run:

```bash
./scripts/test-backend tests/test_conversation_turn_planner.py tests/test_core_flows.py -q
```

Expected: factual challenge gets direct verified answer, no trailing question.

---

### Task 8: Heartbeat Plan Window Truth

**Files:**
- Modify: `backend/src/fitmas/skills/heartbeat/context.py`
- Modify: `backend/src/fitmas/skills/heartbeat/heartbeat.py`
- Modify: `backend/src/fitmas/skills/heartbeat/roles.py`
- Test: `tests/test_heartbeat_plan_window_truth.py`

- [ ] **Step 1: Write failing test for Friday planned session in heartbeat prompt**

```python
def test_morning_briefing_prompt_includes_future_plan_window():
    bundle = build_heartbeat_context_bundle(
        today=date(2026, 5, 7),
        today_planned_session=rest_session("2026-05-07"),
        yesterday_planned_sessions=[running_done("2026-05-06")],
        yesterday_activities=[running_activity("2026-05-06")],
        yesterday_claims=[],
        week_recent_reality=recent_reality(),
        week_activities=[],
        future_scheduled_sessions=[running_session("2026-05-08", 40)],
    )

    rendered = render_heartbeat_context_bundle(bundle)

    assert "[PlanWindowTruth" in rendered
    assert "2026-05-08" in rendered
    assert "Footing" in rendered
    assert "40min" in rendered
```

- [ ] **Step 2: Add `PlanWindowTruth`**

```python
@dataclass(frozen=True, slots=True)
class PlanWindowTruth:
    start_date: date
    end_date: date
    sessions: tuple[PlannedSessionFact, ...]
```

Extend `HeartbeatContextBundle` with `plan_window`.

- [ ] **Step 3: Load future window in `morning_briefing()`**

Use `repo.get_scheduled_sessions_between_dates()` from today through today + 6.

- [ ] **Step 4: Render plan window as source truth**

Add after `TodayTruth`:

```text
[PlanWindowTruth — calendrier futur proche, source autoritaire pour demain/week-end]
- 2026-05-07 (jeudi): rest "Repos flexible" [adapted]
- 2026-05-08 (vendredi): running "Footing endurance — 40 min Z2" 40min [adapted]
```

- [ ] **Step 5: Run heartbeat tests**

Run:

```bash
./scripts/test-backend tests/test_heartbeat_plan_window_truth.py tests/test_heartbeat.py -q
```

Expected: prompt contains future plan truth.

---

### Task 9: Heartbeat Factual Verifier

**Files:**
- Modify: `backend/src/fitmas/skills/heartbeat/heartbeat.py`
- Modify: `backend/src/fitmas/final_reply.py`
- Test: `tests/test_heartbeat_plan_window_truth.py`

- [ ] **Step 1: Write failing test for invalid Friday empty claim**

```python
def test_heartbeat_blocks_or_repairs_future_plan_contradiction():
    grounding = ReplyGroundingPacket(
        local_date="2026-05-07",
        plan_window=(
            PlanWindowFact(47, "2026-05-07", "jeudi", "rest", "Repos flexible", None, "adapted", "free_flexible"),
            PlanWindowFact(46, "2026-05-08", "vendredi", "running", "Footing endurance — 40 min Z2", 40, "adapted", "training"),
        ),
    )

    repaired = final_reply.verify_factual_reply(
        "Vendredi tu laisses vide comme prévu.",
        grounding=grounding,
        request_text_fn=fake_verifier_repairing_to("Jeudi repos, demain footing 40 min Z2."),
    )

    assert repaired == "Jeudi repos, demain footing 40 min Z2."
```

- [ ] **Step 2: Reuse semantic factual verifier for heartbeat**

After `_llm_generate()` returns a briefing message, verify against the heartbeat grounding packet.

- [ ] **Step 3: Repair, then fallback to no-send if still invalid**

For heartbeat, prefer silence over a false proactive:

```python
verified = final_reply.verify_factual_reply(llm_msg, grounding=grounding)
if not verified:
    _trace_decision("no_send", "factual_verifier_blocked")
    return None
```

- [ ] **Step 4: Run heartbeat verifier tests**

Run:

```bash
./scripts/test-backend tests/test_heartbeat_plan_window_truth.py -q
```

Expected: future-plan contradictions are repaired or suppressed.

---

### Task 10: Terminal Close Grounding

**Files:**
- Modify: `backend/src/fitmas/final_reply.py`
- Modify: `backend/src/fitmas/conversation_pipeline.py`
- Test: `tests/test_final_reply.py`

- [ ] **Step 1: Write failing test for close turn adding unsupported day claim**

```python
def test_close_turn_does_not_add_new_temporal_plan_fact():
    reply = final_reply.compose_close_turn_reply(
        user_text="Parfait merci !",
        previous_agent_text="On décale le footing de jeudi à vendredi.",
        request_text_fn=fake_composer("Parfait. Tu souffles aujourd'hui et tu verras vendredi."),
        verifier_text_fn=fake_verifier_repairing_to("Parfait, on garde ça."),
    )

    assert reply == "Parfait, on garde ça."
```

- [ ] **Step 2: Make previous agent text context, not truth**

In `_close_turn_context()`, label previous text as conversation context only. Do not allow new plan facts unless `ReplyGroundingPacket` explicitly includes them.

- [ ] **Step 3: Optional grounding packet for close turn**

Pass only last committed event summaries, not the whole timeline. If no event this turn, close generic.

- [ ] **Step 4: Run close-turn tests**

Run:

```bash
./scripts/test-backend tests/test_final_reply.py tests/test_core_flows.py -q
```

Expected: no new day/session claim on pure social close.

---

### Task 11: Turn Ledger Before Side Effects

**Files:**
- Modify: `backend/src/fitmas/conversation_pipeline.py`
- Modify: `backend/src/fitmas/repository.py`
- Modify: `backend/src/fitmas/plan_mutation_service.py`
- Test: `tests/test_core_flows.py`

- [ ] **Step 1: Write failing test for event linked to conversation turn**

```python
def test_plan_mutation_event_links_to_conversation_turn(test_db, onboarded_user, deps):
    run_conversation_turn(
        ConversationTurnInput(text="oui je confirme", client_message_key="telegram:1:10", source="telegram"),
        db=test_db,
        dependencies=deps.accept_pending_move(),
    )

    event = repo.get_recent_plan_mutation_events(test_db, onboarded_user.id, limit=1)[0]
    assert event.conversation_turn_id is not None
```

- [ ] **Step 2: Create a pending turn record before commit**

Add a repository helper:

```python
def create_conversation_turn_stub(...)-> ConversationTurnRecord:
    ...
```

Use it before applying plan mutation, then update row with final reply/status after side effects.

- [ ] **Step 3: Pass `conversation_turn_id` into mutation service**

For `apply_patch_for_user()` and `apply_decisions_for_user()`, pass the stub id.

- [ ] **Step 4: Run audit-link tests**

Run:

```bash
./scripts/test-backend tests/test_core_flows.py::test_plan_mutation_event_links_to_conversation_turn -q
```

Expected: mutation events are traceable to the exact user turn.

---

### Task 12: Integration Smokes And Docs

**Files:**
- Modify: `docs/LLM-FIRST-CONVERSATION.md`
- Modify: `docs/COACH-RELIABILITY-REFACTOR.md`
- Modify: `docs/COACH-COHERENCE-REFACTOR.md`
- Modify: `docs/BUILD-ORDER.md`
- Add/extend smoke script if needed: `scripts/smoke-real-conversations`

- [ ] **Step 1: Document the new boundary**

Add doctrine:

```text
GroundingContract:
- LLM extracts typed temporal/truth intent.
- Backend resolves typed artifacts against DB/time.
- Final composer writes prose.
- Factual verifier judges prose against machine facts.
- No regex/keyword parsing of free user text.
```

- [ ] **Step 2: Add real dogfood scenarios**

Scenarios:

```text
duplicate_pending_move
pending_accept_move_thursday_to_friday
close_turn_after_move
heartbeat_after_move
reality_check_previous_briefing
```

- [ ] **Step 3: Run targeted tests**

```bash
./scripts/test-backend \
  tests/test_grounding_contract.py \
  tests/test_conversation_temporal_grounding.py \
  tests/test_conversation_idempotency.py \
  tests/test_final_reply_grounded_verifier.py \
  tests/test_heartbeat_plan_window_truth.py \
  tests/test_core_flows.py \
  -q
```

- [ ] **Step 4: Run full backend suite**

```bash
./scripts/test-backend -q
```

- [ ] **Step 5: Run real smoke battery**

```bash
ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-$DEEPSEEK_API_KEY}" \
./scripts/smoke-real-conversations \
  --scenario duplicate_pending_move \
  --scenario pending_accept_move_thursday_to_friday \
  --scenario close_turn_after_move \
  --scenario reality_check_previous_briefing
```

- [ ] **Step 6: Commit in logical slices**

Suggested commits:

```bash
git commit -m "feat: add conversation grounding contracts"
git commit -m "fix: persist telegram idempotency metadata"
git commit -m "feat: ground factual final replies"
git commit -m "feat: add heartbeat plan window truth"
git commit -m "test: add grounded dogfood regressions"
```

## Rollout Strategy

1. Ship idempotency + pending identity first.
2. Ship grounded confirmation / pending accepted replies.
3. Ship plan lookup semantic verifier.
4. Ship heartbeat plan window + verifier.
5. Ship turn ledger audit link.
6. Run dogfood overnight before deploy.

## Success Criteria

- Duplicate Telegram retry does not create competing pending confirmations.
- A confirmation reply cannot invent `mardi aujourd'hui` when local date is Wednesday.
- A pending accepted reply is derived from committed event snapshots.
- A close turn does not add a new day/session claim.
- Heartbeat cannot say Friday is empty when plan window has Friday running.
- “T’es sûr du planning ?” routes to factual truth read and returns a direct verified answer.
- No new deterministic parsing of free user text is introduced.
