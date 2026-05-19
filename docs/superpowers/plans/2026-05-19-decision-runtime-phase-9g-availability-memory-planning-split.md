---
summary: Phase 9G plan for separating availability memory-only turns from availability-driven planning turns
read_when:
  - continuing Decision Runtime legacy deletion after Phase 9F
  - debugging travel or availability turns that should only persist memory
  - deciding whether an availability constraint should trigger planning
---

# Decision Runtime Phase 9G Availability Memory/Planning Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development and superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make typed availability constraints memory-first by default, and route them into canonical planning only when the typed artifacts say the user requested an adaptation.

**Architecture:** The LLM/TurnPlan remains responsible for understanding free text. The backend only consumes typed artifacts: `availability_constraint`, `has_plan_mutation`, `planning_action`, `secondary_intents`, and `CoachUnderstanding.requested_change`. Pure availability turns persist memory and compose a memory/no-change reply. Availability + adaptation turns produce `RequestedPlanChange(kind="constraint_window")` and go through canonical planning.

**Tech Stack:** Python, pytest, SQLite smoke harness, FitMAS Decision Runtime, `ConversationTurnPlan`, `CoachUnderstanding`, `RequestedPlanChange`, canonical planning provider.

---

## Why This Slice

Phase 9F made `trip_constraint` safe by forcing a canonical planning block.

That is correct for:

```text
Je voyage de mercredi a vendredi, adapte si besoin
```

It is too broad for:

```text
Je voyage de mercredi a vendredi
```

The second message should primarily become durable memory:

```text
record_availability(scope=general, starts_on=..., ends_on=...)
```

No planning block should be shown unless the typed turn also carries a planning request.

## Target Behavior

Memory-only:

```text
User: Je voyage de mercredi a vendredi
TurnPlan:
  primary_intent=availability_constraint
  secondary_intents=()
  has_plan_mutation=false
  planning_action=null|unknown
  availability_constraint={scope=general, starts_on=..., ends_on=...}

Expected:
  memory_applied=1
  event_count=0
  pending_count=0
  no canonical_planning_provider handled trace
  no planning_snapshot_flow
```

Planning requested:

```text
User: Je voyage de mercredi a vendredi, adapte si besoin
TurnPlan:
  primary_intent=availability_constraint or plan_mutation
  secondary_intents includes plan_mutation OR has_plan_mutation=true OR planning_action=update_session
  availability_constraint={scope=general, starts_on=..., ends_on=...}

Expected:
  canonical_planning_provider.result=handled
  response_mode=planning_runtime_block
  event_count=0
  pending_count=0
  fallback_scenario_count=0
```

## Files

Modify:

- `backend/src/fitmas/legacy/conversation_canonical_planning_bridge.py`
  - Replace broad `_turn_plan_has_typed_planning_availability_constraint()` routing with an explicit typed planning-request predicate.
  - Keep sport-window + general-window conversion, but only after the predicate allows planning.

- `backend/src/fitmas/conversation_turn_planner.py`
  - Tighten prompt contract so “availability + adapt” must set `secondary_intents=["plan_mutation"]` or `mutation_signal=true`.
  - Keep pure availability as memory-only.

- `scripts/smoke_a_plus_api.py`
  - Add a memory-only travel scenario if missing.
  - Keep `trip_constraint` as canonical-planning-required.

Tests:

- `tests/test_conversation_canonical_planning_bridge.py`
- `tests/test_core_flows.py` or a smaller API/unit test if one already covers memory-only availability.
- `tests/test_smoke_a_plus_api.py`

Docs:

- `docs/BUILD-ORDER.md`
- `docs/DECISION-RUNTIME-REFACTOR.md`
- `docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md`

## Task 1: Add Explicit Planning-Request Predicate

**Files:**

- Modify: `backend/src/fitmas/legacy/conversation_canonical_planning_bridge.py`
- Test: `tests/test_conversation_canonical_planning_bridge.py`

- [ ] **Step 1: Write failing bridge tests**

Add tests:

```python
def test_availability_primary_without_planning_request_stays_memory_only(monkeypatch) -> None:
    monkeypatch.delenv("FITMAS_CANONICAL_PLANNING_PROVIDER", raising=False)
    understanding = CoachUnderstanding(
        intent="availability_signal",
        confidence=0.9,
        user_summary="Voyage de mercredi a vendredi.",
        extracted_signals=(),
        requested_change=None,
        pending_resolution=None,
        clarification_need=None,
    )
    turn_plan = SimpleNamespace(
        primary_intent="availability_constraint",
        secondary_intents=(),
        mutation_signal=False,
        planning_action=None,
        user_goal="voyage de mercredi a vendredi",
        confidence=0.95,
        temporal_references=(),
        availability_constraint={
            "availability": "unavailable",
            "scope": "general",
            "starts_on": "2026-05-20",
            "ends_on": "2026-05-22",
        },
    )

    assert not bridge.should_prepare_canonical_planning_understanding(
        turn_plan=turn_plan,
        pending_confirmation=None,
    )
    assert bridge.planning_understanding_for_provider(
        understanding=understanding,
        turn_plan=turn_plan,
    ) is understanding
```

Add a paired positive test:

```python
def test_availability_primary_with_typed_planning_request_can_use_canonical_planning(monkeypatch) -> None:
    monkeypatch.delenv("FITMAS_CANONICAL_PLANNING_PROVIDER", raising=False)
    understanding = CoachUnderstanding(
        intent="availability_signal",
        confidence=0.9,
        user_summary="Voyage de mercredi a vendredi, adaptation demandee.",
        extracted_signals=(),
        requested_change=None,
        pending_resolution=None,
        clarification_need=None,
    )
    turn_plan = SimpleNamespace(
        primary_intent="availability_constraint",
        secondary_intents=("plan_mutation",),
        mutation_signal=True,
        planning_action="update_session",
        user_goal="voyage de mercredi a vendredi, adapte si besoin",
        confidence=0.95,
        temporal_references=(),
        availability_constraint={
            "availability": "unavailable",
            "scope": "general",
            "starts_on": "2026-05-20",
            "ends_on": "2026-05-22",
        },
    )

    planned = bridge.planning_understanding_for_provider(understanding=understanding, turn_plan=turn_plan)

    assert bridge.should_prepare_canonical_planning_understanding(
        turn_plan=turn_plan,
        pending_confirmation=None,
    )
    assert planned is not None
    assert planned.intent == "plan_change"
    assert planned.requested_change is not None
    assert planned.requested_change.kind == "constraint_window"
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
./scripts/test-backend tests/test_conversation_canonical_planning_bridge.py::test_availability_primary_without_planning_request_stays_memory_only tests/test_conversation_canonical_planning_bridge.py::test_availability_primary_with_typed_planning_request_can_use_canonical_planning -q
```

Expected before implementation:

```text
first test fails because typed availability currently prepares canonical planning too broadly
```

- [ ] **Step 3: Implement typed predicate**

In `conversation_canonical_planning_bridge.py`, add:

```python
def _turn_plan_has_explicit_planning_request(turn_plan: Any) -> bool:
    primary_intent = str(getattr(turn_plan, "primary_intent", "") or "")
    secondary = {str(item or "") for item in tuple(getattr(turn_plan, "secondary_intents", ()) or ())}
    planning_action = str(getattr(turn_plan, "planning_action", "") or "").strip()
    if primary_intent == "plan_mutation" or "plan_mutation" in secondary:
        return True
    if bool(getattr(turn_plan, "mutation_signal", False)):
        return True
    return planning_action not in {"", "unknown", "none", "null"}
```

Then change `_turn_plan_allows_planning()` so typed availability only opens planning when `_turn_plan_has_explicit_planning_request(turn_plan)` is true.

- [ ] **Step 4: Run bridge tests**

Run:

```bash
./scripts/test-backend tests/test_conversation_canonical_planning_bridge.py -q
```

Expected:

```text
all pass
```

## Task 2: Tighten TurnPlan Prompt Contract

**Files:**

- Modify: `backend/src/fitmas/conversation_turn_planner.py`
- Test: `tests/test_conversation_turn_planner.py` if existing prompt tests fit; otherwise `tests/test_conversation_prompting.py`

- [ ] **Step 1: Add prompt assertion**

Add a test that the prompt explicitly distinguishes:

```text
availability-only = memory only
availability + adapte = plan_mutation secondary
```

Expected strings:

```python
assert "Disponibilite seule" in prompt
assert "ne declenche pas de planning" in prompt
assert "si le user demande d'adapter" in prompt
assert "secondary_intents inclut plan_mutation" in prompt
```

- [ ] **Step 2: Update prompt rules**

In `_build_prompt()`, add concise rules:

```text
- Disponibilite seule ("je voyage mercredi-vendredi") = availability_constraint, mutation_signal=false, planning_action=null.
- Si le user demande d'adapter/bouger/remplacer le plan avec cette disponibilite, ajoute plan_mutation en secondary_intents, mutation_signal=true, planning_action=update_session.
```

Do not add keyword parsing in runtime. This is LLM instruction only.

- [ ] **Step 3: Run prompt tests**

Run:

```bash
./scripts/test-backend tests/test_conversation_turn_planner.py tests/test_conversation_prompting.py -q
```

Expected:

```text
all pass
```

## Task 3: Add Smoke Coverage For Memory-Only Travel

**Files:**

- Modify: `scripts/smoke_a_plus_api.py`
- Test: `tests/test_smoke_a_plus_api.py`

- [ ] **Step 1: Add scenario**

Add:

```python
SmokeScenario(
    name="trip_memory_only",
    prompt="Je voyage de mercredi a vendredi",
    expectation="no_plan_write",
    description="Pure travel availability should persist memory without planning mutation.",
)
```

Do not add it to `_CANONICAL_PLANNING_PROVIDER_REQUIRED_SCENARIOS`.

- [ ] **Step 2: Add smoke unit guard**

Add a unit test proving `trip_memory_only` does not require canonical planning handled trace.

- [ ] **Step 3: Run smoke unit tests**

Run:

```bash
./scripts/test-backend tests/test_smoke_a_plus_api.py -q
```

Expected:

```text
all pass
```

## Task 4: Real Smoke Proof

**Files:**

- No code files unless failure reveals a real gap.

- [ ] **Step 1: Run memory-only smoke**

Run:

```bash
./scripts/smoke-a-plus-api --skip-generated-week --scenario trip_memory_only --fallback-census-json /tmp/fitmas-9g-trip-memory.json --timeout 240 --startup-timeout 45
```

Expected:

```text
RESULT: OK
events=+0
pending=+0
fallback_scenario_count=0
memory_applied visible in turn context or persisted availability fact present
```

- [ ] **Step 2: Run adaptation-request smoke**

Run:

```bash
./scripts/smoke-a-plus-api --skip-generated-week --scenario trip_constraint --fallback-census-json /tmp/fitmas-9g-trip-adapt.json --timeout 240 --startup-timeout 45
```

Expected:

```text
RESULT: OK
latest_response_mode=planning_runtime_block
fallback_scenario_count=0
events=+0
pending=+0
```

## Task 5: Docs

**Files:**

- Modify: `docs/BUILD-ORDER.md`
- Modify: `docs/DECISION-RUNTIME-REFACTOR.md`
- Modify: `docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md`

- [ ] **Step 1: Document Phase 9G**

Add:

```text
Phase 9G:
- availability-only turns are memory-first and do not enter planning
- availability + typed adaptation request enters canonical planning
- no free-text deterministic parsing added
- trip_memory_only smoke passes without writes/pending
- trip_constraint remains canonical planning block until multi-day candidates exist
```

- [ ] **Step 2: Run final verification**

Run:

```bash
./scripts/docs:list
git diff --check
./scripts/test-backend -q
```

Expected:

```text
docs list includes 9G plan
git diff --check has no output
backend tests pass
```

## Acceptance Criteria

- Pure typed travel availability persists memory and does not enter canonical planning.
- Typed travel + adaptation request enters canonical planning.
- No keyword/regex parser is added to conversation runtime.
- No legacy `planning_snapshot_flow` appears for either travel lane.
- `trip_memory_only` and `trip_constraint` real smokes pass.
- Full backend test suite passes.

## Next Slice After 9G

Only after 9G is stable:

```text
9H: build safe multi-day candidates for constraint_window
```

9H can then consider:

- move only flexible/support sessions out of the unavailable window;
- preserve key sessions unless policy explicitly allows pending;
- never auto-commit multiple operations in the first version;
- ask confirmation with a compact explanation.

