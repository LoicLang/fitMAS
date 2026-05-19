---
summary: Phase 9E plan for migrating remaining planning snapshot and candidate fallbacks into canonical planning
read_when:
  - continuing Decision Runtime legacy deletion after Phase 9D
  - reducing planning_snapshot_flow or adaptation_candidate_flow
  - migrating create/lighten/broad-constraint planning lanes to canonical planning
---

# Decision Runtime Phase 9E Planning Snapshot Flow Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce the remaining planning-owned legacy fallback surface by migrating one active `planning_snapshot_flow` lane into the canonical `PlanningDecisionPipeline`, and keep all still-active fallbacks classified by census.

**Architecture:** Phase 9E does not delete all planning legacy. It moves a bounded requested-change kind from `planning_snapshot_flow` / `adaptation_candidate_flow` into `domain/planning/*`, then proves via real smokes that the lane is canonical or explicitly blocked without legacy authority. The LLM still only emits typed `CoachUnderstanding`; backend policy decides and commands write.

**Tech Stack:** Python, pytest, SQLite smoke harness, FitMAS Decision Runtime, `CoachUnderstanding`, `RequestedPlanChange`, `PlanCandidateBuilder`, `PlanningDecisionService`, `fallback_census`.

---

## Scope

Implement 9E-A: migrate the `create` planning lane represented by:

```text
add_hard_dense
requested_change.kind=create
target_ref=date:2026-05-20
desired_intensity=hard
risk_signals=["load"]
```

Target behavior:

```text
response_mode=planning_runtime_block
canonical_planning_provider.result=handled
legacy_decide.legacy_skipped=true
no planning_snapshot_flow
no adaptation_candidate_flow
no pending
no event
```

Why this lane first:

- it is active in the core smoke;
- it is safety-sensitive because it asks for more hard load in a dense week;
- canonical handling can be deterministic after typed Understanding;
- it removes a real `planning_snapshot_flow` owner without needing broad travel/multi-op support yet.

Out of scope for 9E:

- full travel constraint migration;
- free-text deterministic parsing;
- reply polish for `sport=course`;
- read-only `legacy_provider` cleanup;
- deleting `planning_snapshot_flow` globally.

## Files

Modify:

- `backend/src/fitmas/domain/planning/models.py`
  - Add or verify `RequestedPlanChange.kind == "create"` support remains explicit.

- `backend/src/fitmas/domain/planning/reference_resolver.py`
  - Ensure `target_ref=date:*` resolves for create even when `source_ref` is empty.

- `backend/src/fitmas/domain/planning/candidate_builder.py`
  - Build bounded `create_session` candidates from typed `RequestedPlanChange(kind="create")`.
  - For dense hard requests on an occupied or already hard day, build no unsafe candidate and expose a policy-friendly warning.

- `backend/src/fitmas/domain/planning/decision_service.py`
  - Return a canonical `DecisionOutcome` block when create has no safe candidate or violates density/load policy.
  - Keep pending/commit disabled for unsafe hard create in the first slice.

- `backend/src/fitmas/legacy/conversation_canonical_planning_bridge.py`
  - Make `create` with `target_ref=date:*` applicable to canonical planning.
  - Do not route this lane to `planning_snapshot_flow`.

- `backend/src/fitmas/legacy/planning_outcome_adapter.py`
  - Ensure canonical block becomes user-visible `planning_runtime_block` / `plan_adaptation_block` consistently.

- `scripts/smoke_a_plus_api.py`
  - Add `add_hard_dense` to canonical planning required scenarios only after canonical trace is stable.

- `docs/BUILD-ORDER.md`
- `docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md`
- `docs/DECISION-RUNTIME-REFACTOR.md`
  - Record 9E status and residual owners.

Tests:

- `tests/test_domain_planning_reference_resolver.py`
- `tests/test_domain_planning_candidate_builder.py`
- `tests/test_domain_planning_decision_service.py`
- `tests/test_conversation_canonical_planning_bridge.py`
- `tests/test_smoke_a_plus_api.py`
- `tests/test_phase9a_legacy_physical_delete_architecture.py`

## Task 1: Lock The 9E Smoke Expectation

- [ ] **Step 1: Add `add_hard_dense` to the canonical required set**

Modify `scripts/smoke_a_plus_api.py`:

```python
_CANONICAL_PLANNING_PROVIDER_REQUIRED_SCENARIOS = frozenset(
    {
        "move_easy_then_confirm",
        "swap_by_day",
        "move_hard_close",
        "replace_swim_with_bike",
        "swim_unavailable_two_weeks",
        "add_hard_dense",
    }
)
```

- [ ] **Step 2: Add a unit test for this gate**

Add to `tests/test_smoke_a_plus_api.py`:

```python
def test_default_planning_provider_requires_canonical_trace_for_add_hard_dense(monkeypatch):
    smoke = _load_smoke_module()
    monkeypatch.delenv("FITMAS_CANONICAL_PLANNING_PROVIDER", raising=False)
    scenario = smoke.SmokeScenario(
        name="add_hard_dense",
        prompt="ajoute une seance dure mercredi",
        expectation="guarded_no_commit",
    )
    before = smoke.DbSnapshot(events=(), pending=(), sessions=(), latest_turn=None)
    after = smoke.DbSnapshot(
        events=(),
        pending=(),
        sessions=(),
        latest_turn={
            "response_mode": "planning_snapshot_clarification",
            "assistant_message": "Tu veux remplacer ou ajouter ?",
        },
        turns=(
            {
                "id": 1,
                "context_json": (
                    '{"canonical_planning_provider":{"result":"fallback_legacy"},'
                    '"fallback_census":[{"owner":"planning","source":"planning_snapshot_flow"}]}'
                ),
            },
        ),
    )

    result = smoke.evaluate_scenario_result(scenario, before, after)

    assert not result.ok
    assert "canonical planning provider did not handle supported planning turn" in result.reasons
```

- [ ] **Step 3: Run the targeted test and expect failure before implementation**

Run:

```bash
./scripts/test-backend -q tests/test_smoke_a_plus_api.py::test_default_planning_provider_requires_canonical_trace_for_add_hard_dense
```

Expected:

```text
1 passed
```

The test passes immediately because it checks evaluator behavior. The real smoke will still fail until implementation.

## Task 2: Make Create Requests Canonical-Applicable

- [ ] **Step 1: Add bridge tests for typed create**

Add to `tests/test_conversation_canonical_planning_bridge.py`:

```python
def test_canonical_planning_provider_accepts_create_with_date_target(monkeypatch) -> None:
    monkeypatch.delenv("FITMAS_CANONICAL_PLANNING_PROVIDER", raising=False)

    assert bridge.should_use_canonical_planning_without_legacy(
        understanding=_understanding(
            requested_change=_requested_change(
                kind="create",
                source_ref=None,
                target_ref="date:2026-05-20",
                desired_sport="running",
                desired_duration_min=45,
                desired_intensity="hard",
            )
        ),
        turn_plan=_turn_plan(),
        pending_confirmation=None,
    )
```

- [ ] **Step 2: Run it and verify failure if create is not applicable**

Run:

```bash
./scripts/test-backend -q tests/test_conversation_canonical_planning_bridge.py::test_canonical_planning_provider_accepts_create_with_date_target
```

Expected before implementation:

```text
FAILED
```

- [ ] **Step 3: Update canonical support rules**

Modify `backend/src/fitmas/legacy/conversation_canonical_planning_bridge.py` so create requires only a date-like target:

```python
def _requested_change_is_supported(requested_change: RequestedPlanChange | None) -> bool:
    if requested_change is None:
        return False
    kind = str(getattr(requested_change, "kind", "") or "").strip()
    source_ref = getattr(requested_change, "source_ref", None)
    target_ref = getattr(requested_change, "target_ref", None)
    if kind == "create":
        return _is_date_like_ref(target_ref)
    if kind == "move":
        return _is_session_role_ref(source_ref) and _is_date_like_ref(target_ref)
    if kind == "swap":
        return _is_session_role_ref(source_ref) and _is_session_role_ref(target_ref)
    if kind in {"lighten", "replace"}:
        return _is_session_role_ref(source_ref) or (kind == "replace" and _is_sport_window_ref(source_ref))
    return False
```

- [ ] **Step 4: Run bridge test**

Run:

```bash
./scripts/test-backend -q tests/test_conversation_canonical_planning_bridge.py::test_canonical_planning_provider_accepts_create_with_date_target
```

Expected:

```text
1 passed
```

## Task 3: Resolve Create Date Targets In Domain

- [ ] **Step 1: Add resolver test**

Add to `tests/test_domain_planning_reference_resolver.py`:

```python
def test_resolver_allows_create_with_date_target_and_empty_source() -> None:
    requested = RequestedPlanChange(
        kind="create",
        source_ref=None,
        target_ref="date:2026-05-20",
        desired_sport="running",
        desired_duration_min=45,
        desired_intensity="hard",
        reason="typed create request",
        risk_signals=("load",),
    )

    resolved = ReferenceResolver(_context()).resolve(requested)

    assert resolved.source.kind == "none"
    assert resolved.target.kind == "date"
    assert resolved.target.date == date(2026, 5, 20)
    assert "unresolved_source_ref" not in resolved.warnings
```

- [ ] **Step 2: Run resolver test**

Run:

```bash
./scripts/test-backend -q tests/test_domain_planning_reference_resolver.py::test_resolver_allows_create_with_date_target_and_empty_source
```

Expected before implementation:

```text
FAILED
```

- [ ] **Step 3: Update `ReferenceResolver.resolve`**

In `backend/src/fitmas/domain/planning/reference_resolver.py`, ensure missing source is not a warning for create:

```python
if requested_change.kind == "create":
    source = PlanChangeReference(kind="none", raw=None, session_id=None, date=None)
else:
    source = self._resolve_source_ref(self._parse_ref(requested_change.source_ref), warnings)
```

The exact helper names must match the current file; keep the behavior scoped to `kind == "create"`.

- [ ] **Step 4: Run resolver test**

Run:

```bash
./scripts/test-backend -q tests/test_domain_planning_reference_resolver.py::test_resolver_allows_create_with_date_target_and_empty_source
```

Expected:

```text
1 passed
```

## Task 4: Build Create Candidates Safely

- [ ] **Step 1: Add candidate builder tests**

Add to `tests/test_domain_planning_candidate_builder.py`:

```python
def test_create_hard_on_existing_hard_day_returns_no_candidate_with_warning() -> None:
    context = _context(
        _session(
            session_id=1,
            scheduled_date="2026-05-20",
            sport_type="running",
            session_type="threshold",
            intensity="hard",
            duration_min=65,
        )
    )
    requested = RequestedPlanChange(
        kind="create",
        source_ref=None,
        target_ref="date:2026-05-20",
        desired_sport="running",
        desired_duration_min=45,
        desired_intensity="hard",
        reason="add hard day",
        risk_signals=("load",),
    )
    resolved = ReferenceResolver(context).resolve(requested)

    result = PlanCandidateBuilder(context).build(requested, resolved)

    assert result.candidates == ()
    assert "target_day_already_has_hard_session" in result.warnings
```

Add a positive bounded case:

```python
def test_create_easy_on_free_day_builds_create_session_candidate() -> None:
    context = _context()
    requested = RequestedPlanChange(
        kind="create",
        source_ref=None,
        target_ref="date:2026-05-25",
        desired_sport="running",
        desired_duration_min=30,
        desired_intensity="easy",
        reason="easy support session",
        risk_signals=(),
    )
    resolved = ReferenceResolver(context).resolve(requested)

    result = PlanCandidateBuilder(context).build(requested, resolved)

    assert len(result.candidates) == 1
    patch = result.candidates[0].patch
    assert patch.operations[0].operation_type == "create_session"
    assert patch.operations[0].target_date == "2026-05-25"
    assert patch.operations[0].new_sport_type == "running"
    assert patch.operations[0].new_duration_min == 30
```

- [ ] **Step 2: Run candidate tests**

Run:

```bash
./scripts/test-backend -q tests/test_domain_planning_candidate_builder.py -k 'create_hard_on_existing_hard_day or create_easy_on_free_day'
```

Expected before implementation:

```text
FAILED
```

- [ ] **Step 3: Implement create handling in candidate builder**

In `backend/src/fitmas/domain/planning/candidate_builder.py`, add create handling in the existing build dispatcher:

```python
if requested_change.kind == "create":
    return self._build_create(requested_change, resolved)
```

Add `_build_create` with this behavior:

```python
def _build_create(self, requested_change, resolved):
    target_date = resolved.target.date
    if target_date is None:
        return PlanCandidateBuildResult(candidates=(), warnings=("unresolved_target_ref",))
    sport = _normalize_sport(requested_change.desired_sport) or "running"
    intensity = _normalize_intensity(requested_change.desired_intensity) or "easy"
    duration = requested_change.desired_duration_min or (30 if intensity == "easy" else 45)
    sessions_on_day = _sessions_on_date(self._context, target_date)
    if intensity == "hard" and any(_session_intensity(session) == "hard" for session in sessions_on_day):
        return PlanCandidateBuildResult(
            candidates=(),
            warnings=("target_day_already_has_hard_session",),
        )
    operation = PlanPatchOperation(
        operation_type="create_session",
        target_date=target_date.isoformat(),
        new_sport_type=sport,
        new_session_type="easy" if intensity == "easy" else "workout",
        new_duration_min=duration,
        new_intensity=intensity,
        rationale=requested_change.reason,
    )
    return PlanCandidateBuildResult(
        candidates=(self._candidate_from_operation(operation, "create_session"),),
        warnings=(),
    )
```

Use existing local helper names where available. Do not introduce text parsing.

- [ ] **Step 4: Run candidate tests**

Run:

```bash
./scripts/test-backend -q tests/test_domain_planning_candidate_builder.py -k 'create_hard_on_existing_hard_day or create_easy_on_free_day'
```

Expected:

```text
2 passed
```

## Task 5: Return Canonical Block For Unsafe Create

- [ ] **Step 1: Add decision service test**

Add to `tests/test_domain_planning_decision_service.py`:

```python
def test_decision_service_blocks_create_hard_on_existing_hard_day() -> None:
    context = _context(
        _session(
            session_id=1,
            scheduled_date="2026-05-20",
            sport_type="running",
            session_type="threshold",
            intensity="hard",
            duration_min=65,
        )
    )
    requested = RequestedPlanChange(
        kind="create",
        source_ref=None,
        target_ref="date:2026-05-20",
        desired_sport="running",
        desired_duration_min=None,
        desired_intensity="hard",
        reason="user wants extra hard session",
        risk_signals=("load",),
    )

    outcome = PlanningDecisionService(context).decide(requested)

    assert outcome.kind == "plan_blocked"
    assert outcome.selected_candidate_id is None
    assert outcome.explanation.reason_summary
    assert "target_day_already_has_hard_session" in outcome.explanation.evidence
```

- [ ] **Step 2: Run decision service test**

Run:

```bash
./scripts/test-backend -q tests/test_domain_planning_decision_service.py::test_decision_service_blocks_create_hard_on_existing_hard_day
```

Expected before implementation:

```text
FAILED
```

- [ ] **Step 3: Implement no-candidate create block**

In `backend/src/fitmas/domain/planning/decision_service.py`, where no candidates are available:

```python
if requested_change.kind == "create" and "target_day_already_has_hard_session" in build_result.warnings:
    return DecisionOutcome(
        kind="plan_blocked",
        applied_commands=(),
        candidates=(),
        selected_candidate_id=None,
        explanation=DecisionExplanation(
            decision_label="Seance non ajoutee",
            reason_summary="La journee cible contient deja une seance dure.",
            evidence=("target_day_already_has_hard_session",),
            tradeoff="On protege la recuperation et la coherence de la semaine.",
            impact={},
            protected=("recuperation", "charge", "risque blessure"),
            next_step=None,
        ),
        reply_contract=ReplyContract(mode="plan_blocked"),
    )
```

Use current constructor names and tuple/list conventions from existing tests.

- [ ] **Step 4: Run decision service test**

Run:

```bash
./scripts/test-backend -q tests/test_domain_planning_decision_service.py::test_decision_service_blocks_create_hard_on_existing_hard_day
```

Expected:

```text
1 passed
```

## Task 6: Prove Real Smoke No Longer Uses Snapshot/Candidate For `add_hard_dense`

- [ ] **Step 1: Run targeted smoke with census**

Run:

```bash
./scripts/smoke-a-plus-api --skip-generated-week --scenario add_hard_dense --keep-db --db-path .tmp-9e-add-hard.db --fallback-census-json .tmp-9e-add-hard-census.json --timeout 420
```

Expected:

```text
RESULT: OK (1 check(s))
mode=planning_runtime_block
events=+0
pending=+0
```

- [ ] **Step 2: Inspect census JSON**

Run:

```bash
.venv/bin/python - <<'PY'
import json
data=json.load(open('.tmp-9e-add-hard-census.json'))
report=data['reports'][0]
print(report['latest_response_mode'])
print(report['fallback_turn_count'])
print(report['turns'])
PY
```

Expected:

```text
planning_runtime_block
0
[]
```

- [ ] **Step 3: If the smoke still shows `planning_snapshot_flow`, stop and inspect typed refs**

Run:

```bash
.venv/bin/python - <<'PY'
import json, sqlite3
con=sqlite3.connect('.tmp-9e-add-hard.db')
raw=con.execute('select context_json from conversation_turns order by id desc limit 1').fetchone()[0]
ctx=json.loads(raw)
print(json.dumps(ctx.get('canonical_understanding'), ensure_ascii=False, indent=2))
print(json.dumps(ctx.get('canonical_planning_provider'), ensure_ascii=False, indent=2))
print(json.dumps(ctx.get('planning_snapshot_flow'), ensure_ascii=False, indent=2))
PY
```

Use the printed typed artifact to adjust canonical ref normalization or create support. Do not add keyword parsing.

## Task 7: Update Architecture Gates

- [ ] **Step 1: Add a delete gate for add-hard dense**

Add to `tests/test_phase9a_legacy_physical_delete_architecture.py`:

```python
def test_add_hard_dense_is_required_canonical_planning_lane() -> None:
    source = _read("scripts/smoke_a_plus_api.py")

    required_block = source[source.index("_CANONICAL_PLANNING_PROVIDER_REQUIRED_SCENARIOS") :]
    assert '"add_hard_dense"' in required_block
```

- [ ] **Step 2: Add a route guard that create support does not call free-text parsing**

Add to the same file:

```python
def test_create_planning_support_uses_typed_refs_not_user_text_parsing() -> None:
    source = _read("backend/src/fitmas/domain/planning/candidate_builder.py")

    assert "user_text" not in source
    assert "user_message" not in source
    assert "re.search" not in source
```

- [ ] **Step 3: Run architecture gates**

Run:

```bash
./scripts/test-backend -q tests/test_phase9a_legacy_physical_delete_architecture.py
```

Expected:

```text
all tests pass
```

## Task 8: Full Verification And Docs

- [ ] **Step 1: Run targeted unit pack**

Run:

```bash
./scripts/test-backend -q \
  tests/test_conversation_canonical_planning_bridge.py \
  tests/test_domain_planning_reference_resolver.py \
  tests/test_domain_planning_candidate_builder.py \
  tests/test_domain_planning_decision_service.py \
  tests/test_smoke_a_plus_api.py \
  tests/test_phase9a_legacy_physical_delete_architecture.py
```

Expected:

```text
all tests pass
```

- [ ] **Step 2: Run real core smoke with census**

Run:

```bash
./scripts/smoke-a-plus-api --skip-generated-week --keep-db --db-path .tmp-9e-core.db --fallback-census-json .tmp-9e-core-census.json --timeout 420
```

Expected:

```text
RESULT: OK (15 check(s))
```

- [ ] **Step 3: Run real daily smoke with census**

Run:

```bash
./scripts/smoke-a-plus-api --daily --skip-generated-week --keep-db --db-path .tmp-9e-daily.db --fallback-census-json .tmp-9e-daily-census.json --timeout 420
```

Expected:

```text
RESULT: OK (26 check(s))
```

- [x] **Step 4: Run full backend**

Run:

```bash
./scripts/test-backend -q
```

Expected:

```text
all tests pass
```

- [x] **Step 5: Run whitespace gate**

Run:

```bash
git diff --check
```

Expected:

```text
no output
```

- [x] **Step 6: Update docs**

Update:

- `docs/BUILD-ORDER.md`
- `docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md`
- `docs/DECISION-RUNTIME-REFACTOR.md`

Add:

```text
Phase 9E:
- add_hard_dense migrated from planning_snapshot/adaptation candidate fallback to canonical planning;
- create hard on an already hard/dense day returns a canonical block;
- no legacy pending is created;
- census shows add_hard_dense fallback_turn_count=0;
- remaining owners: trip_constraint/broad constraints, ambiguous incomplete refs, read-only legacy provider.
```

## Result 2026-05-19

Implemented.

- `add_hard_dense` is now a canonical-required smoke scenario.
- `TurnPlan.create_session` with a typed date target can produce a canonical
  `RequestedPlanChange(kind="create")` even when the Understanding LLM asks a
  clarification because the sport is missing.
- The planning domain owns target-only creates: occupied stable training days
  block canonically, missing sport on a free day blocks canonically, and no
  legacy candidate/snapshot route is needed.
- Hard create intensity is normalized from typed artifacts, including
  `high -> hard`, before candidate building or policy.
- Dense/occupied hard creates block before candidate evaluation and before any
  command service can write.

Verification:

```text
./scripts/test-backend -q tests/test_conversation_canonical_planning_bridge.py tests/test_domain_planning_reference_resolver.py tests/test_domain_planning_candidate_builder.py tests/test_domain_planning_decision_service.py tests/test_smoke_a_plus_api.py
88 passed

./scripts/smoke-a-plus-api --skip-generated-week --scenario add_hard_dense --keep-db --db-path .tmp-9e-add-hard-3.db --fallback-census-json .tmp-9e-add-hard-census-3.json --timeout 420
RESULT: OK (1 check(s))
latest_response_mode=planning_runtime_block
fallback_scenario_count=0

./scripts/test-backend -q
1419 passed, 11 skipped, 11 subtests passed

git diff --check
no output
```

## Acceptance Criteria

- `add_hard_dense` is canonical-required in `scripts/smoke_a_plus_api.py`.
- Real smoke `add_hard_dense` has `canonical_planning_provider.result=handled`.
- Real smoke `add_hard_dense` has no `planning_snapshot_flow`.
- Real smoke `add_hard_dense` has no `adaptation_candidate_flow`.
- Real smoke `add_hard_dense` creates no pending and no event.
- `availability_no_affected_session` remains physically absent.
- No deterministic free-text parsing is introduced.
- Full backend and core/daily smokes pass.

## Next Slice After 9E

Phase 9F should target broad constraints:

```text
trip_constraint
requested_change.kind=unknown
risk_signals=["availability"]
target_ref=date:2026-05-20
```

Do not start 9F inside 9E. Broad constraints need a separate canonical model:

```text
RequestedAvailabilityWindowChange
or RequestedPlanChange(kind="constraint_window")
```
