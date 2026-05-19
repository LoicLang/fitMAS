---
summary: Phase 9H plan for safe multi-day candidates from constraint_window
read_when:
  - implementing safe multi-day planning candidates for travel or broad availability windows
  - moving constraint_window from canonical block to pending confirmation
  - preventing broad availability rewrites from auto-committing
---

# Decision Runtime Phase 9H Constraint Window Candidates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development and superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `RequestedPlanChange(kind="constraint_window")` from a conservative block into safe, backend-built multi-day candidates that always require user confirmation.

**Architecture:** The LLM still only extracts typed availability/planning intent. The backend enriches the machine ref, resolves impacted `ScheduledSession`s, builds bounded `PlanPatch` candidates, evaluates them through the existing reviewer/policy path, and forces pending confirmation for any multi-day/window candidate. No free-text parsing, no legacy snapshot compiler, no automatic multi-operation commit.

**Tech Stack:** Python, pytest, SQLite smoke harness, FitMAS Decision Runtime, `RequestedPlanChange`, `ReferenceResolver`, `PlanCandidateBuilder`, `SportPolicy`, `PlanningCommandService`, `PlanPatch`.

---

## Why This Is The Best Approach

The tempting shortcut is to let the LLM write a broad `PlanPatch` for travel. That is exactly what the refactor is trying to kill: the LLM can understand “voyage mercredi-vendredi”, but it must not decide how to move fractionné, sortie longue, recovery, and weekly load by itself.

The best next step is therefore:

```text
typed availability window
→ deterministic reference resolution
→ deterministic candidate construction
→ existing evaluator/reviewer/policy
→ forced pending confirmation
→ CommandService writes pending only
```

This is best because:

- **Reliability:** every operation is on concrete `ScheduledSession.id` and ISO dates.
- **Safety:** multi-day changes never auto-commit in the first version.
- **Architecture:** planning logic stays in `domain/planning`, not in prompts, conversation pipeline, or legacy snapshot flow.
- **Extensibility:** later we can add richer candidate strategies without changing the conversation runtime.
- **Dogfood quality:** FitMAS can propose something useful instead of only blocking, but still avoids pretending it knows the whole real-life constraint.

## Scope

Input:

```text
RequestedPlanChange(
  kind="constraint_window",
  source_ref="availability_window:unavailable:general:2026-05-20:2026-05-22",
  target_ref=None,
  reason="voyage de mercredi a vendredi",
  risk_signals=("availability",),
)
```

Backward-compatible input still accepted:

```text
availability_window:general:2026-05-20:2026-05-22
```

Target behavior when candidate is feasible:

```text
response_mode=plan_adaptation_pending_confirmation
canonical_planning_provider.result=handled
legacy_decide.legacy_skipped=true
pending=+1
events=+0
fallback_scenario_count=0
```

Target behavior when candidate is not feasible:

```text
response_mode=planning_runtime_block
pending=+0
events=+0
fallback_scenario_count=0
```

## Non-Negotiables

- Do not parse free user text.
- Do not let Understanding produce `PlanPatch`.
- Do not use `planning_snapshot_flow`.
- Do not add a remove/cancel operation in 9H.
- Do not auto-commit multi-operation/window candidates.
- Do not move completed/skipped/canceled sessions.
- Do not move onto occupied stable training days.
- Do not create more than one session per target day.

## Files

Modify:

- `backend/src/fitmas/domain/planning/models.py`
  - Add `availability: str | None` to `PlanChangeReference`.

- `backend/src/fitmas/domain/planning/reference_resolver.py`
  - Parse both `availability_window:<scope>:<start>:<end>` and `availability_window:<availability>:<scope>:<start>:<end>`.

- `backend/src/fitmas/legacy/conversation_canonical_planning_bridge.py`
  - Emit v2 refs with availability:
    `availability_window:unavailable:general:2026-05-20:2026-05-22`.

- `backend/src/fitmas/domain/planning/candidate_builder.py`
  - Build `constraint_window` multi-move candidates.

- `backend/src/fitmas/domain/planning/decision_service.py`
  - Stop pre-blocking feasible `constraint_window`.
  - Keep block only when candidate set is empty.
  - Ask `SportPolicy` to force confirmation for window candidates.

- `backend/src/fitmas/domain/planning/policy.py`
  - Add `force_confirmation_reason` support.

- `scripts/smoke_a_plus_api.py`
  - Update `trip_constraint` expectation to accept pending as the preferred successful outcome.

Tests:

- `tests/test_domain_planning_reference_resolver.py`
- `tests/test_conversation_canonical_planning_bridge.py`
- `tests/test_domain_planning_candidate_builder.py`
- `tests/test_domain_planning_decision_service.py`
- `tests/test_domain_planning_evaluator_policy.py`
- `tests/test_smoke_a_plus_api.py`

Docs:

- `docs/BUILD-ORDER.md`
- `docs/DECISION-RUNTIME-REFACTOR.md`
- `docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md`

## Candidate Strategy V1

Only one strategy in 9H:

```text
move_affected_sessions_after_window_preserving_order
```

Rules:

1. collect active training sessions with `scheduled_date` inside the window;
2. ignore completed/skipped/canceled/rest/off sessions;
3. sort affected sessions by original date/time;
4. find open target dates after `ends_on`, up to `ends_on + 10 days`;
5. target dates must not already contain stable active training;
6. assign one affected session per target date, preserving order;
7. emit one `PlanPatch` with multiple `move_session` operations;
8. if not enough target dates, return no candidate and block;
9. force pending confirmation even if evaluator says commit-safe.

Rationale:

- moving is safer than changing sport/content;
- preserving order protects workout intent;
- after-window targets avoid scheduling into a travel window;
- pending avoids silent multi-day rewrite.

## Task 1: Availability Window Ref V2

**Files:**

- Modify: `backend/src/fitmas/domain/planning/models.py`
- Modify: `backend/src/fitmas/domain/planning/reference_resolver.py`
- Modify: `backend/src/fitmas/legacy/conversation_canonical_planning_bridge.py`
- Test: `tests/test_domain_planning_reference_resolver.py`
- Test: `tests/test_conversation_canonical_planning_bridge.py`

- [ ] **Step 1: Write failing resolver test**

Add to `tests/test_domain_planning_reference_resolver.py`:

```python
def test_resolver_accepts_typed_availability_window_ref_with_status() -> None:
    requested = RequestedPlanChange(
        kind="constraint_window",
        source_ref="availability_window:unavailable:general:2026-05-20:2026-05-22",
        target_ref=None,
        desired_sport=None,
        desired_duration_min=None,
        desired_intensity=None,
        reason="travel unavailable",
        risk_signals=("availability",),
    )

    resolved = ReferenceResolver(_context(_session(42, "2026-05-21"))).resolve(requested)

    assert resolved.source.kind == "availability_window"
    assert resolved.source.availability == "unavailable"
    assert resolved.source.scope == "general"
    assert resolved.source.starts_on == date(2026, 5, 20)
    assert resolved.source.ends_on == date(2026, 5, 22)
    assert resolved.warnings == ()
```

- [ ] **Step 2: Write failing bridge test**

Add to `tests/test_conversation_canonical_planning_bridge.py`:

```python
def test_turn_plan_general_unavailability_emits_availability_window_with_status(monkeypatch) -> None:
    monkeypatch.delenv("FITMAS_CANONICAL_PLANNING_PROVIDER", raising=False)
    understanding = CoachUnderstanding(
        intent="availability_signal",
        confidence=0.9,
        user_summary="Voyage avec adaptation demandee.",
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

    assert planned is not None
    assert planned.requested_change is not None
    assert planned.requested_change.source_ref == "availability_window:unavailable:general:2026-05-20:2026-05-22"
```

- [ ] **Step 3: Run tests and verify failure**

Run:

```bash
./scripts/test-backend \
  tests/test_domain_planning_reference_resolver.py::test_resolver_accepts_typed_availability_window_ref_with_status \
  tests/test_conversation_canonical_planning_bridge.py::test_turn_plan_general_unavailability_emits_availability_window_with_status -q
```

Expected:

```text
fails because availability field/v2 ref is not implemented
```

- [ ] **Step 4: Implement v2 parsing**

In `backend/src/fitmas/domain/planning/models.py`, add:

```python
availability: str | None = None
```

to `PlanChangeReference`.

In `backend/src/fitmas/domain/planning/reference_resolver.py`, replace `_parse_availability_window_payload()` with:

```python
def _parse_availability_window_payload(payload: str) -> tuple[str | None, str | None, date | None, date | None]:
    parts = [part.strip() for part in str(payload or "").split(":")]
    if len(parts) == 3:
        raw_availability = "unavailable"
        raw_scope, raw_start, raw_end = parts
    elif len(parts) == 4:
        raw_availability, raw_scope, raw_start, raw_end = parts
    else:
        return None, None, None, None
    availability = _availability_status(raw_availability)
    scope = _availability_window_scope(raw_scope)
    if availability is None or scope is None:
        return None, None, None, None
    try:
        starts_on = date.fromisoformat(raw_start[:10])
        ends_on = date.fromisoformat(raw_end[:10])
    except ValueError:
        return None, None, None, None
    if ends_on < starts_on:
        return None, None, None, None
    return availability, scope, starts_on, ends_on


def _availability_status(value: str) -> str | None:
    status = str(value or "").strip().lower()
    if status in {"unavailable", "limited"}:
        return status
    return None
```

Update `_availability_window_ref()` to set `availability=availability`.

In `conversation_canonical_planning_bridge.py`, emit:

```python
source_ref=f"availability_window:{availability}:{scope}:{starts_on}:{ends_on}"
```

and update `_availability_window_constraint_from_payload()` to return `(availability, scope, starts_on, ends_on)`.

- [ ] **Step 5: Run ref tests**

Run:

```bash
./scripts/test-backend tests/test_domain_planning_reference_resolver.py tests/test_conversation_canonical_planning_bridge.py -q
```

Expected:

```text
all pass
```

## Task 2: Build Constraint Window Candidates

**Files:**

- Modify: `backend/src/fitmas/domain/planning/candidate_builder.py`
- Test: `tests/test_domain_planning_candidate_builder.py`

- [ ] **Step 1: Write failing candidate test**

Add helpers if needed:

```python
def _window_resolved() -> ResolvedPlanChange:
    requested = RequestedPlanChange(
        kind="constraint_window",
        source_ref="availability_window:unavailable:general:2026-05-20:2026-05-22",
        target_ref=None,
        desired_sport=None,
        desired_duration_min=None,
        desired_intensity=None,
        reason="travel unavailable",
        risk_signals=("availability",),
    )
    return ResolvedPlanChange(
        requested_change=requested,
        source=PlanChangeReference(
            kind="availability_window",
            raw=requested.source_ref,
            session_id=None,
            date=None,
            availability="unavailable",
            scope="general",
            starts_on=date(2026, 5, 20),
            ends_on=date(2026, 5, 22),
        ),
        target=PlanChangeReference(kind="unknown", raw=None, session_id=None, date=None),
        warnings=(),
    )
```

Add test:

```python
def test_builder_builds_multi_move_candidate_for_unavailable_window() -> None:
    candidate_set = PlanCandidateBuilder(
        _context(
            _session(1, "2026-05-20", sport_type="running"),
            _session(2, "2026-05-22", sport_type="strength"),
            _session(3, "2026-05-24", sport_type="cycling"),
        )
    ).build(_window_resolved())

    assert len(candidate_set.candidates) == 1
    candidate = candidate_set.candidates[0]
    assert candidate.candidate_ref == "backend:constraint_window:2026-05-20:2026-05-22:move_after"
    assert "availability" in candidate.risk_notes
    assert "multi_day" in candidate.risk_notes
    patch = candidate_set.backend_candidate_patches[candidate.candidate_ref]
    assert [op.operation_type for op in patch.operations] == ["move_session", "move_session"]
    assert [op.target_session_id for op in patch.operations] == [1, 2]
    assert [op.target_date for op in patch.operations] == ["2026-05-23", "2026-05-25"]
```

The occupied target `2026-05-24` forces the second moved session to `2026-05-25`.

- [ ] **Step 2: Write failing empty-candidate test**

```python
def test_builder_returns_empty_when_window_has_no_open_targets() -> None:
    sessions = (
        _session(1, "2026-05-20", sport_type="running"),
        _session(2, "2026-05-23", sport_type="cycling"),
        _session(3, "2026-05-24", sport_type="strength"),
        _session(4, "2026-05-25", sport_type="running"),
        _session(5, "2026-05-26", sport_type="cycling"),
        _session(6, "2026-05-27", sport_type="strength"),
        _session(7, "2026-05-28", sport_type="running"),
        _session(8, "2026-05-29", sport_type="cycling"),
        _session(9, "2026-05-30", sport_type="strength"),
        _session(10, "2026-05-31", sport_type="running"),
        _session(11, "2026-06-01", sport_type="cycling"),
    )

    candidate_set = PlanCandidateBuilder(_context(*sessions)).build(_window_resolved())

    assert candidate_set.candidates == ()
    assert candidate_set.backend_candidate_patches == {}
```

- [ ] **Step 3: Run candidate tests and verify failure**

Run:

```bash
./scripts/test-backend \
  tests/test_domain_planning_candidate_builder.py::test_builder_builds_multi_move_candidate_for_unavailable_window \
  tests/test_domain_planning_candidate_builder.py::test_builder_returns_empty_when_window_has_no_open_targets -q
```

Expected:

```text
fails because constraint_window candidate building is not implemented
```

- [ ] **Step 4: Implement candidate builder**

In `PlanCandidateBuilder.build()` before `_patch_for_change()`:

```python
if resolved_change.kind == "constraint_window" and resolved_change.source.kind == "availability_window":
    return self._build_constraint_window_candidates(resolved_change)
```

Add:

```python
def _build_constraint_window_candidates(self, resolved_change: ResolvedPlanChange) -> PlanningCandidateSet:
    patch = self._constraint_window_move_after_patch(resolved_change)
    if patch is None:
        return PlanningCandidateSet(candidates=(), backend_candidate_patches={})
    source = resolved_change.source
    ref = f"backend:constraint_window:{source.starts_on.isoformat()}:{source.ends_on.isoformat()}:move_after"
    candidate = PlanPatchCandidate(
        id=ref,
        patches=(),
        rationale=resolved_change.reason or "Fenetre d'indisponibilite a adapter.",
        expected_tradeoff="Deplacer les seances touchees apres la fenetre, en gardant l'ordre, avec confirmation obligatoire.",
        confidence=0.75,
        assumptions=("Fenetre indisponible confirmee par artifact type.",),
        risk_notes=tuple(dict.fromkeys((*resolved_change.requested_change.risk_signals, "multi_day"))),
        created_from_plan_id=_PLAN_ID,
        created_from_plan_version=_PLAN_VERSION,
        candidate_ref=ref,
    )
    return PlanningCandidateSet(candidates=(candidate,), backend_candidate_patches={ref: patch})
```

Add `_constraint_window_move_after_patch()`:

```python
def _constraint_window_move_after_patch(self, resolved_change: ResolvedPlanChange) -> PlanPatch | None:
    source = resolved_change.source
    if source.availability != "unavailable" or source.starts_on is None or source.ends_on is None:
        return None
    affected = _affected_training_sessions(
        self._context,
        starts_on=source.starts_on,
        ends_on=source.ends_on,
    )
    if not affected:
        return None
    targets = _open_target_dates_after_window(
        self._context,
        starts_after=source.ends_on,
        count=len(affected),
    )
    if len(targets) < len(affected):
        return None
    operations = [
        PlanPatchOperation(
            operation_type="move_session",
            target_session_id=_int_value(session, "id"),
            target_date=target.isoformat(),
            rationale=resolved_change.reason,
        )
        for session, target in zip(affected, targets)
        if _int_value(session, "id") is not None
    ]
    if len(operations) != len(affected):
        return None
    return PlanPatch(
        operations=operations,
        coach_message=_USER_SAFE_PATCH_MESSAGE,
        confirmation_reason="Fenetre large: confirmation obligatoire avant de deplacer plusieurs seances.",
    )
```

Add helper functions:

```python
def _affected_training_sessions(context: Any, *, starts_on: date, ends_on: date) -> tuple[Any, ...]:
    return tuple(
        session
        for session in sorted(_scheduled_sessions(context), key=lambda item: (_session_date(item) or date.max))
        if _is_active_training_session(session)
        if (session_date := _session_date(session)) is not None
        if starts_on <= session_date <= ends_on
    )


def _open_target_dates_after_window(context: Any, *, starts_after: date, count: int) -> tuple[date, ...]:
    targets: list[date] = []
    current = starts_after
    for offset in range(1, 11):
        candidate = current.fromordinal(starts_after.toordinal() + offset)
        if _has_active_training_on_date(context, candidate):
            continue
        targets.append(candidate)
        if len(targets) == count:
            break
    return tuple(targets)


def _has_active_training_on_date(context: Any, target_date: date) -> bool:
    return any(
        _is_active_training_session(session) and _session_date(session) == target_date
        for session in _scheduled_sessions(context)
    )


def _is_active_training_session(session: Any) -> bool:
    if _session_is_completed(session):
        return False
    status = str(_value(session, "completion_status") or "").strip().lower()
    if status in {"skipped", "canceled", "cancelled"}:
        return False
    sport = str(_value(session, "sport_type") or "").strip().lower()
    session_type = str(_value(session, "session_type") or "").strip().lower()
    return sport not in {"", "rest", "off"} and session_type not in {"rest", "off"}
```

- [ ] **Step 5: Run candidate tests**

Run:

```bash
./scripts/test-backend tests/test_domain_planning_candidate_builder.py -q
```

Expected:

```text
all pass
```

## Task 3: Force Pending Confirmation For Window Candidates

**Files:**

- Modify: `backend/src/fitmas/domain/planning/policy.py`
- Modify: `backend/src/fitmas/domain/planning/decision_service.py`
- Test: `tests/test_domain_planning_evaluator_policy.py`
- Test: `tests/test_domain_planning_decision_service.py`

- [ ] **Step 1: Write failing policy test**

In `tests/test_domain_planning_evaluator_policy.py`, add a helper if the file already has `_evaluated()`. Then add:

```python
def test_policy_can_force_pending_confirmation_for_window_candidate() -> None:
    evaluated = _evaluated(score_total=92, policy_hint="commit_safe")

    decision = SportPolicy().decide(
        (evaluated,),
        force_confirmation_reason="Fenetre large: confirmation obligatoire.",
    )

    assert decision.action == "pending_confirmation"
    assert decision.selected_candidate_id == evaluated.candidate.id
    assert decision.requires_confirmation_reason == "Fenetre large: confirmation obligatoire."
    assert decision.risk_level == "medium"
```

- [ ] **Step 2: Implement policy force**

In `backend/src/fitmas/domain/planning/policy.py`:

```python
from dataclasses import replace
```

Change signature:

```python
def decide(..., force_confirmation_reason: str | None = None) -> AdaptationPolicyDecision:
```

Then:

```python
decision = decide_adaptation_policy(evaluated_candidates, reviewer_decision=reviewer_decision)
if force_confirmation_reason and decision.action == "commit":
    return replace(
        decision,
        action="pending_confirmation",
        reason=force_confirmation_reason,
        user_facing_reason=force_confirmation_reason,
        requires_confirmation_reason=force_confirmation_reason,
        risk_level="medium",
        pending_event={
            "candidate_id": decision.selected_candidate_id,
            "reason": force_confirmation_reason,
            "risk_level": "medium",
        },
    )
return decision
```

- [ ] **Step 3: Write failing decision service test**

Add to `tests/test_domain_planning_decision_service.py`:

```python
def test_decide_plan_change_forces_pending_for_constraint_window(monkeypatch) -> None:
    class FakeEvaluator:
        def __init__(self, *, db, user):
            pass

        def evaluate(self, candidate_set, **kwargs):
            from fitmas.plan_patch import PlanPatchValidation
            from fitmas.plan_patch_adaptation_policy import AdaptationPolicyDecision
            from fitmas.plan_patch_candidate_evaluator import EvaluatedPlanPatchCandidate
            from fitmas.plan_patch_candidates import PlanPatchCandidateValidation
            from fitmas.week_coherence import WeekCoherenceScore

            candidate = candidate_set.candidates[0]
            patch = candidate_set.backend_candidate_patches[candidate.candidate_ref]
            return (
                EvaluatedPlanPatchCandidate(
                    candidate=candidate,
                    candidate_validation=PlanPatchCandidateValidation(
                        status="valid",
                        patch_count=0,
                        operation_count=0,
                        operation_results=(),
                        summary="valid",
                    ),
                    patch=patch,
                    patch_validation=PlanPatchValidation(status="valid", operation_results=(), summary="valid"),
                    week_context=None,
                    facts=None,
                    score=WeekCoherenceScore(total=92, load_balance=90, recovery_spacing=90, specificity=90, feasibility=90),
                    findings=(),
                    score_delta=0,
                    policy_hint="commit_safe",
                    evaluation_summary="ok",
                ),
            )

    monkeypatch.setattr("fitmas.domain.planning.decision_service.PlanCandidateEvaluator", FakeEvaluator)
    requested = RequestedPlanChange(
        kind="constraint_window",
        source_ref="availability_window:unavailable:general:2026-05-20:2026-05-22",
        target_ref=None,
        desired_sport=None,
        desired_duration_min=None,
        desired_intensity=None,
        reason="travel unavailable",
        risk_signals=("availability",),
    )

    result = decide_plan_change(
        requested,
        context=_window_context_with_open_targets(),
        db=object(),
        user=SimpleNamespace(id=1, timezone="Europe/Paris"),
        coach_state_bundle=None,
        reviewer_request_json_fn=None,
    )

    assert result.kind == "pending_confirmation"
    assert result.selected_patch is not None
    assert len(result.selected_patch.operations) >= 1
    assert "confirmation obligatoire" in result.reason
```

Add `_window_context_with_open_targets()` in the test file with two affected sessions and open dates after the window.

- [ ] **Step 4: Update decision service**

In `decision_service.py`, remove the unconditional `_constraint_window_block_reason()` early block. Replace it with an empty-candidate reason only.

When calling policy:

```python
policy_decision = SportPolicy().decide(
    evaluated,
    reviewer_decision=reviewer_decision,
    force_confirmation_reason=_force_confirmation_reason(resolved),
)
```

Add:

```python
def _force_confirmation_reason(resolved) -> str | None:
    if resolved.kind == "constraint_window":
        return "Fenetre large: confirmation obligatoire avant de deplacer plusieurs seances."
    return None
```

Update `_block_reason_from_empty_candidate_set()` for `availability_window`:

```python
if source.kind == "availability_window":
    starts_on = _date_label(getattr(source, "starts_on", None))
    ends_on = _date_label(getattr(source, "ends_on", None))
    if starts_on and ends_on:
        return (
            f"Je note la contrainte du {starts_on} au {ends_on}, "
            "mais je ne trouve pas assez de jours libres pour proposer un deplacement propre. "
            "Je ne touche pas au plan."
        )
```

- [ ] **Step 5: Run policy and decision tests**

Run:

```bash
./scripts/test-backend tests/test_domain_planning_evaluator_policy.py tests/test_domain_planning_decision_service.py -q
```

Expected:

```text
all pass
```

## Task 4: Pending Command Integration

**Files:**

- Test: `tests/test_domain_planning_mutation_service.py`
- No production change unless the test reveals missing serialization.

- [ ] **Step 1: Add pending multi-operation patch test**

Add:

```python
def test_command_service_persists_pending_multi_operation_window_patch(monkeypatch) -> None:
    pending_rows = []

    def fake_create_pending_mutation_confirmation(db, **kwargs):
        pending_rows.append(kwargs)
        return SimpleNamespace(id=123)

    monkeypatch.setattr(
        "fitmas.domain.planning.mutation_service.repo.create_pending_mutation_confirmation",
        fake_create_pending_mutation_confirmation,
    )
    monkeypatch.setattr(
        "fitmas.domain.planning.mutation_service.repo.get_active_pending_mutation_confirmation",
        lambda db, user_id: None,
    )
    patch = PlanPatch(
        coach_message="Je te propose un ajustement prudent.",
        confirmation_reason="Fenetre large.",
        operations=[
            PlanPatchOperation(operation_type="move_session", target_session_id=1, target_date="2026-05-23", rationale="travel"),
            PlanPatchOperation(operation_type="move_session", target_session_id=2, target_date="2026-05-24", rationale="travel"),
        ],
    )

    result = PlanningCommandService(db=object(), user=SimpleNamespace(id=1)).apply(
        _decision("pending_confirmation", patch=patch),
        source_text="adapte mon voyage",
        coach_state_bundle=None,
        activities=(),
        active_facts=(),
    )

    assert result.status == "pending"
    assert result.pending_confirmation_id == 123
    assert pending_rows[0]["mutation_type"] == "plan_patch"
    assert "move_session" in pending_rows[0]["decision_json"]
```

- [ ] **Step 2: Run mutation service tests**

Run:

```bash
./scripts/test-backend tests/test_domain_planning_mutation_service.py -q
```

Expected:

```text
all pass
```

## Task 5: Smoke Gates

**Files:**

- Modify: `scripts/smoke_a_plus_api.py`
- Test: `tests/test_smoke_a_plus_api.py`

- [ ] **Step 1: Add expected pending response for trip_constraint**

Keep `trip_constraint` in `_CANONICAL_PLANNING_PROVIDER_REQUIRED_SCENARIOS`.

Add a smoke unit test:

```python
def test_trip_constraint_accepts_canonical_pending_confirmation(monkeypatch):
    smoke = _load_smoke_module()
    monkeypatch.delenv("FITMAS_CANONICAL_PLANNING_PROVIDER", raising=False)
    scenario = smoke.SmokeScenario(
        name="trip_constraint",
        prompt="Je voyage de mercredi a vendredi, adapte si besoin",
        expectation="coherent_commit_or_pending",
    )
    before = smoke.DbSnapshot(events=(), pending=(), sessions=(), latest_turn=None)
    after = smoke.DbSnapshot(
        events=(),
        pending=({"id": 1, "status": "pending", "mutation_type": "plan_patch"},),
        sessions=(),
        latest_turn={
            "response_mode": "plan_adaptation_pending_confirmation",
            "pending_confirmation": True,
            "assistant_message": "Je te propose un ajustement, tu confirmes ?",
        },
        turns=(
            {
                "id": 1,
                "context_json": (
                    '{"canonical_planning_provider":{"result":"handled"},'
                    '"legacy_decide":{"legacy_skipped":true}}'
                ),
            },
        ),
    )

    result = smoke.evaluate_scenario_result(scenario, before, after)

    assert result.ok
```

- [ ] **Step 2: Run smoke tests**

Run:

```bash
./scripts/test-backend tests/test_smoke_a_plus_api.py -q
```

Expected:

```text
all pass
```

## Task 6: Real Smokes

**Files:**

- No code files unless failure reveals a real bug.

- [ ] **Step 1: Run trip memory-only smoke**

Run:

```bash
./scripts/smoke-a-plus-api --skip-generated-week --scenario trip_memory_only --fallback-census-json /tmp/fitmas-9h-trip-memory.json --timeout 240 --startup-timeout 45
```

Expected:

```text
RESULT: OK
latest_response_mode=no_change_composed
events=+0
pending=+0
fallback_scenario_count=0
```

- [ ] **Step 2: Run trip adaptation smoke**

Run:

```bash
./scripts/smoke-a-plus-api --skip-generated-week --scenario trip_constraint --fallback-census-json /tmp/fitmas-9h-trip-adapt.json --timeout 240 --startup-timeout 45
```

Expected if candidate feasible in generated seed:

```text
RESULT: OK
latest_response_mode=plan_adaptation_pending_confirmation
events=+0
pending=+1
fallback_scenario_count=0
```

Acceptable fallback if candidate not feasible:

```text
RESULT: OK
latest_response_mode=planning_runtime_block
events=+0
pending=+0
fallback_scenario_count=0
```

If it produces `planning_snapshot_flow`, `adaptation_candidate_flow`, or unclassified legacy fallback, fix the canonical path.

## Task 7: Docs And Final Verification

**Files:**

- Modify: `docs/BUILD-ORDER.md`
- Modify: `docs/DECISION-RUNTIME-REFACTOR.md`
- Modify: `docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md`

- [ ] **Step 1: Document Phase 9H**

Add:

```text
Phase 9H:
- constraint_window can build backend multi-move candidates
- availability_window refs now carry availability status
- multi-day/window candidates always require confirmation
- no auto-commit for broad windows
- trip_constraint remains canonical and legacy-free
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
docs list includes 9H plan
git diff --check has no output
backend tests pass
```

## Acceptance Criteria

- `availability_window:unavailable:general:<start>:<end>` resolves.
- Legacy v1 refs still resolve.
- `constraint_window` builds at least one backend candidate when open target days exist.
- Candidate uses only `move_session` operations in 9H.
- Multi-day/window candidates cannot auto-commit.
- `PlanningCommandService` can persist pending multi-operation patches.
- Pure availability memory-only still does not enter planning.
- `trip_constraint` remains canonical provider handled with no fallback census.
- Full backend test suite passes.

## Out Of Scope

- cancel/remove session operation;
- automatic commit for travel rewrites;
- LLM-authored multi-day PlanPatch;
- parsing travel words in runtime;
- sophisticated target-day optimization;
- UI display of impacted sessions.

## Next Slice After 9H

```text
9I: richer constraint_window strategies
```

Candidate strategies to consider later:

- move only support sessions, ask about key sessions;
- replace limited-availability sessions with travel-compatible mobility;
- choose among two options: "preserve all load" vs "drop support load";
- expose impacted sessions and candidate options in app cockpit.

