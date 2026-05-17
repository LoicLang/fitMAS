---
summary: implementation plan for Decision Runtime Phase 8J canonical planning cutover dogfood
read_when:
  - implementing Decision Runtime Phase 8J
  - dogfooding FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER
  - deciding whether canonical planning can become default
  - hardening duplicate pending and planning artifact gates
---

# Decision Runtime Phase 8J Canonical Planning Cutover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove that canonical `CoachUnderstanding.requested_change` can drive planning adaptations under `FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER=1` across a strict dogfood matrix, without duplicate pending, fake claims or silent legacy fallthrough.

**Architecture:** 8J is a hardening and proof slice before any default-enable or aggressive shrink. `CoachDecision` remains the default provider contract. The canonical planning path is opt-in and must still write only through `PlanningCommandService`, resolve pending through `conversation_pending_bridge`, and speak only through `DecisionOutcome -> DecisionReplyComposer`.

**Tech Stack:** Python 3.13, pytest/unittest, existing FastAPI smoke scripts, zsh smoke wrappers, SQLAlchemy test DB fixtures.

---

## Implementation Status

Delivered locally on 2026-05-15.

Evidence:

```text
targeted 8J gates -> 8 passed
pending/core cutover -> 3 passed
architecture pack Phase 8 -> 59 passed
canonical planning wrapper -> RESULT: OK (9 checks)
full backend -> 1207 passed, 11 skipped, 11 subtests passed
```

Dogfood finding fixed during implementation:

```text
reply_grounding_gap: "Candidate backend, pas une reponse finale" leaked into
a visible pending reply. The fix removed internal candidate messages from
backend PlanPatch candidates, stripped backend ids from reply candidate
summaries, and hardened both voice guard and smoke harness.
```

## CTO Decision

Do 8J before refactoring `decide()`.

Reason:

```text
8I proved canonical commands and pending can work under flags.
The explicit planning cutover reproducer is now stable on one scenario.
The next risk is breadth, not architecture naming.
```

8J answers one question:

```text
Can canonical planning cutover survive real planning dogfood without creating
duplicate pending, fake commits, ungrounded replies or hidden legacy fallback?
```

If yes, the next phase can default-enable a narrow canonical lane.
If no, every failure must be classified by layer before any shrink.

## Scope

8J includes:

```text
1. Architecture gates for canonical planning cutover.
2. A dedicated smoke wrapper that enables all canonical flags including planning.
3. Strict smoke assertions for duplicate pending and artifact coherence.
4. A planning scenario matrix with real API/provider calls.
5. Deterministic regression tests for pending acceptance under canonical cutover.
6. Failure classification so fixes land in the right layer.
7. Docs update with results and remaining debt.
```

8J does not include:

```text
1. Default-enabling `FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER`.
2. Deleting `CoachDecision`.
3. Refactoring the body of `decide()`.
4. Shrinking `conversation_pipeline.py` aggressively.
5. Moving root services into `domain/*`.
6. Adding deterministic parsing of user text.
7. Adding new local fallbacks in `conversation_pipeline.py`.
```

## Non-Negotiables

```text
1. No deterministic parsing of free user text.
2. No regex/keyword heuristic on user messages.
3. No planning write outside `PlanningCommandService`.
4. No pending resolution outside `conversation_pending_bridge`.
5. No visible planning reply outside `DecisionOutcome -> DecisionReplyComposer`.
6. Canonical flags stay off by default.
7. Planning cutover dogfood uses an explicit wrapper only.
8. A scenario that expects a planning artifact cannot pass by doing nothing and claiming success.
9. Duplicate active pending is a hard failure.
10. Hidden legacy fallthrough is a hard failure when canonical cutover is enabled.
```

## File Map

Create:

```text
tests/test_phase8j_canonical_planning_cutover_architecture.py
scripts/smoke-decision-runtime-canonical-planning
```

Modify:

```text
scripts/smoke_a_plus_api.py
tests/test_smoke_a_plus_api.py
tests/test_core_flows.py
docs/DECISION-RUNTIME-REFACTOR.md
docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md
docs/BUILD-ORDER.md
docs/README.md
```

Modify only if a failing test proves it necessary:

```text
backend/src/fitmas/conversation_pipeline.py
backend/src/fitmas/legacy/conversation_understanding_bridge.py
backend/src/fitmas/legacy/conversation_planning_bridge.py
backend/src/fitmas/legacy/conversation_pending_bridge.py
backend/src/fitmas/domain/planning/*
```

Do not modify:

```text
backend/src/fitmas/llm/decision_legacy.py
backend/src/fitmas/conversation_prompt_modules.py
backend/src/fitmas/final_reply.py
backend/src/fitmas/tools/registry.py
```

## Target Flag Set

The 8J wrapper must run with:

```text
FITMAS_UNDERSTANDING_RUNTIME_SHADOW=1
FITMAS_COMMANDS_FROM_UNDERSTANDING=1
FITMAS_PENDING_FROM_UNDERSTANDING=1
FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER=1
```

The 8I wrapper must keep excluding:

```text
FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER=1
```

That separation matters. 8I proves canonical non-planning paths. 8J proves
canonical planning cutover.

## Scenario Matrix

Run these through `scripts/smoke_a_plus_api.py` under the 8J wrapper:

| Scenario | Expected result |
|----------|-----------------|
| `move_easy_then_confirm` | commit after confirmation, no duplicate pending |
| `swap_by_day` | coherent commit or pending, no claim without artifact |
| `lighten_tomorrow` | coherent commit or pending, no hidden no-op claim |
| `replace_swim_with_bike` | coherent commit or pending, references resolved from DB truth |
| `future_evening_unavailable` | coherent commit or pending, no text parser shortcut |
| `fatigue_tomorrow` | coherent commit or pending, guarded if sport risk is high |
| `avoid_back_to_back` | coherent commit or pending, no deterministic keyword shortcut |
| `swim_unavailable_two_weeks` | coherent commit or pending, sport-specific constraint handled by typed artifacts |
| `confirm_without_pending` | no planning write, no pending creation |

Provider variability is acceptable only inside these boundaries:

```text
commit with event is acceptable
pending with one pending row is acceptable
block/clarification is acceptable for ambiguous or risky changes
no-op plus mutation claim is not acceptable
duplicate pending is not acceptable
planning write on confirm_without_pending is not acceptable
internal jargon in user reply is not acceptable
```

## Failure Labels

When a scenario fails, classify it with one of these labels:

```text
understanding_bad_intent
requested_change_missing
reference_resolution_gap
candidate_builder_gap
policy_gap
pending_gate_gap
duplicate_pending
reply_grounding_gap
provider_timeout_or_json_error
legacy_fallthrough_regression
smoke_harness_gap
```

The label guides the fix:

```text
understanding_bad_intent       -> `llm/prompts/understanding.py` or parser schema
requested_change_missing       -> `CoachUnderstanding` compilation
reference_resolution_gap       -> `domain/planning/reference_resolver.py`
candidate_builder_gap          -> `domain/planning/candidate_builder.py`
policy_gap                     -> `domain/planning/policy.py`
pending_gate_gap               -> `conversation_pending_bridge` or shared pending gate
duplicate_pending              -> pending arbitration / active pending uniqueness
reply_grounding_gap            -> reply composer / verifier
provider_timeout_or_json_error -> gateway/smoke reliability, not planning logic
legacy_fallthrough_regression  -> bridge source selection
smoke_harness_gap              -> test harness assertion is underspecified
```

---

## Task 1 - Add 8J Architecture Gates

**Files:**

- Create: `tests/test_phase8j_canonical_planning_cutover_architecture.py`

- [ ] **Step 1: Write failing architecture tests**

Create `tests/test_phase8j_canonical_planning_cutover_architecture.py`:

```python
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"


def _source(relative: str) -> str:
    return (SRC / relative).read_text(encoding="utf-8")


def _imports(relative: str) -> set[str]:
    tree = ast.parse((SRC / relative).read_text(encoding="utf-8"), filename=relative)
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def test_8j_has_dedicated_canonical_planning_wrapper() -> None:
    script = ROOT / "scripts" / "smoke-decision-runtime-canonical-planning"

    assert script.exists()
    source = script.read_text(encoding="utf-8")
    assert "FITMAS_UNDERSTANDING_RUNTIME_SHADOW=1" in source
    assert "FITMAS_COMMANDS_FROM_UNDERSTANDING=1" in source
    assert "FITMAS_PENDING_FROM_UNDERSTANDING=1" in source
    assert "FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER=1" in source
    assert "move_easy_then_confirm" in source
    assert "swap_by_day" in source
    assert "lighten_tomorrow" in source
    assert "replace_swim_with_bike" in source
    assert "future_evening_unavailable" in source
    assert "fatigue_tomorrow" in source
    assert "avoid_back_to_back" in source
    assert "swim_unavailable_two_weeks" in source
    assert "confirm_without_pending" in source


def test_8j_keeps_8i_wrapper_without_planning_cutover() -> None:
    source = (ROOT / "scripts" / "smoke-decision-runtime-canonical-flags").read_text(encoding="utf-8")

    assert "FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER=1" not in source


def test_8j_planning_cutover_flag_stays_opt_in() -> None:
    bridge = _source("legacy/conversation_understanding_bridge.py")

    assert "FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER" in bridge
    assert 'os.getenv("FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER"' in bridge
    assert "setdefault(\"FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER\"" not in bridge


def test_8j_decision_package_stays_pure() -> None:
    forbidden = {
        "fitmas.legacy",
        "fitmas.llm",
        "fitmas.conversation_pipeline",
        "fitmas.memory_mutation_service",
        "fitmas.execution_mutation_service",
        "fitmas.plan_mutation_service",
    }
    for path in (SRC / "decision").glob("*.py"):
        imports = _imports(f"decision/{path.name}")
        assert not forbidden.intersection(imports), f"{path.name}: {forbidden.intersection(imports)}"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
./scripts/test-backend -q tests/test_phase8j_canonical_planning_cutover_architecture.py
```

Expected:

```text
FAIL because `scripts/smoke-decision-runtime-canonical-planning` does not exist yet.
```

---

## Task 2 - Harden Smoke Artifact Checks

**Files:**

- Modify: `scripts/smoke_a_plus_api.py`
- Modify: `tests/test_smoke_a_plus_api.py`

- [ ] **Step 1: Add failing tests for duplicate pending and strict canonical planning**

Append these tests to `tests/test_smoke_a_plus_api.py`:

```python
def test_canonical_planning_fails_on_duplicate_active_pending(monkeypatch):
    smoke = _load_smoke_module()
    monkeypatch.setenv("FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER", "1")
    scenario = smoke.SmokeScenario(
        name="move_easy_then_confirm",
        prompt="deplace la recuperation puis confirme",
        expectation="coherent_commit_or_pending",
        followups=("oui je confirme",),
    )
    before = smoke.DbSnapshot(events=(), pending=(), sessions=(), latest_turn=None)
    after = smoke.DbSnapshot(
        events=(),
        pending=(
            {"id": 1, "status": "pending", "mutation_type": "plan_patch"},
            {"id": 2, "status": "pending", "mutation_type": "plan_patch"},
        ),
        sessions=(),
        latest_turn={"response_mode": "plan_patch_confirmation", "assistant_message": "Tu confirmes ?"},
    )

    result = smoke.evaluate_scenario_result(scenario, before, after)

    assert not result.ok
    assert "duplicate_pending" in result.reasons


def test_canonical_planning_confirm_without_pending_cannot_write(monkeypatch):
    smoke = _load_smoke_module()
    monkeypatch.setenv("FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER", "1")
    scenario = smoke.SmokeScenario(
        name="confirm_without_pending",
        prompt="oui je confirme",
        expectation="no_plan_write",
    )
    before = smoke.DbSnapshot(events=(), pending=(), sessions=(), latest_turn=None)
    after = smoke.DbSnapshot(
        events=({"id": 1, "command_type": "move_session"},),
        pending=(),
        sessions=(),
        latest_turn={"response_mode": "mutation_applied", "assistant_message": "C'est fait."},
    )

    result = smoke.evaluate_scenario_result(scenario, before, after)

    assert not result.ok
    assert "confirm_without_pending wrote planning artifact" in result.reasons


def test_canonical_planning_followup_path_allows_one_pending_row(monkeypatch):
    smoke = _load_smoke_module()
    monkeypatch.setenv("FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER", "1")
    scenario = smoke.SmokeScenario(
        name="move_easy_then_confirm",
        prompt="deplace la recuperation",
        expectation="coherent_commit_or_pending",
        followups=("oui je confirme",),
    )
    before = smoke.DbSnapshot(events=(), pending=(), sessions=(), latest_turn=None)
    after = smoke.DbSnapshot(
        events=({"id": 7, "command_type": "apply_plan_patch"},),
        pending=({"id": 3, "status": "accepted", "mutation_type": "plan_patch"},),
        sessions=(),
        latest_turn={
            "response_mode": "pending_accepted",
            "mutation_applied": True,
            "assistant_message": "C'est applique.",
        },
    )

    result = smoke.evaluate_scenario_result(scenario, before, after)

    assert result.ok
    assert result.reasons == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
./scripts/test-backend -q tests/test_smoke_a_plus_api.py -k "canonical_planning"
```

Expected:

```text
FAIL because duplicate active pending and confirm_without_pending are not yet classified by the smoke evaluator.
```

- [ ] **Step 3: Implement strict canonical planning checks**

Modify `scripts/smoke_a_plus_api.py`.

Add helpers near `_row_delta`:

```python
def _canonical_planning_cutover_enabled() -> bool:
    return os.getenv("FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _active_pending_rows(snapshot: DbSnapshot) -> tuple[dict[str, Any], ...]:
    return tuple(row for row in snapshot.pending if str(row.get("status") or "") == "pending")
```

Add this block inside `evaluate_scenario_result`, after `new_pending` is
computed and before expectation-specific checks:

```python
    if _canonical_planning_cutover_enabled():
        active_pending = _active_pending_rows(after)
        if len(active_pending) > 1:
            reasons.append("duplicate_pending")
        if scenario.name == "confirm_without_pending" and (event_delta or pending_delta or mutation_applied):
            reasons.append("confirm_without_pending wrote planning artifact")
        if scenario.name == "move_easy_then_confirm" and scenario.followups:
            if pending_delta > 1:
                reasons.append("duplicate_pending")
            if mutation_applied and not event_delta:
                reasons.append("pending acceptance marked mutation_applied without event")
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
./scripts/test-backend -q tests/test_smoke_a_plus_api.py -k "canonical_planning"
```

Expected:

```text
3 passed
```

---

## Task 3 - Add Canonical Planning Smoke Wrapper

**Files:**

- Create: `scripts/smoke-decision-runtime-canonical-planning`

- [ ] **Step 1: Create wrapper**

Create `scripts/smoke-decision-runtime-canonical-planning`:

```zsh
#!/usr/bin/env zsh

set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
cd "$repo_root"

export FITMAS_UNDERSTANDING_RUNTIME_SHADOW=1
export FITMAS_COMMANDS_FROM_UNDERSTANDING=1
export FITMAS_PENDING_FROM_UNDERSTANDING=1
export FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER=1

echo "canonical planning flags:"
echo "  FITMAS_UNDERSTANDING_RUNTIME_SHADOW=$FITMAS_UNDERSTANDING_RUNTIME_SHADOW"
echo "  FITMAS_COMMANDS_FROM_UNDERSTANDING=$FITMAS_COMMANDS_FROM_UNDERSTANDING"
echo "  FITMAS_PENDING_FROM_UNDERSTANDING=$FITMAS_PENDING_FROM_UNDERSTANDING"
echo "  FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER=$FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER"

./scripts/test-backend -q \
  tests/test_phase8j_canonical_planning_cutover_architecture.py \
  tests/test_smoke_a_plus_api.py -k "canonical_planning"

./scripts/test-backend -q \
  tests/test_core_flows.py -k "canonical_pending_accept_survives_legacy_decide_none or post_decide_candidate_flow_respects_active_pending_gate"

./scripts/smoke-a-plus-api \
  --skip-generated-week \
  --scenario move_easy_then_confirm \
  --scenario swap_by_day \
  --scenario lighten_tomorrow \
  --scenario replace_swim_with_bike \
  --scenario future_evening_unavailable \
  --scenario fatigue_tomorrow \
  --scenario avoid_back_to_back \
  --scenario swim_unavailable_two_weeks \
  --scenario confirm_without_pending \
  --timeout 240
```

- [ ] **Step 2: Make wrapper executable**

Run:

```bash
chmod +x scripts/smoke-decision-runtime-canonical-planning
```

- [ ] **Step 3: Run architecture gate**

Run:

```bash
./scripts/test-backend -q tests/test_phase8j_canonical_planning_cutover_architecture.py
```

Expected:

```text
4 passed
```

---

## Task 4 - Add Deterministic Pending Cutover Regression Coverage

**Files:**

- Modify: `tests/test_core_flows.py`

- [ ] **Step 1: Add a regression for canonical cutover confirmation not creating a second pending**

Add a test next to `test_canonical_pending_accept_survives_legacy_decide_none`:

```python
def test_canonical_planning_cutover_confirmation_keeps_single_pending_row(self) -> None:
    _, target = self._create_plan_with_tomorrow_session()
    patch = PlanPatch(
        operations=[
            PlanPatchOperation(
                op="move_session",
                session_id=target.id,
                target_date=(target.scheduled_date + timedelta(days=1)).date().isoformat(),
            )
        ],
        reason="test pending",
        source="test",
    )
    pending = repo.create_pending_mutation_confirmation(
        self.db,
        user_id=self.user.id,
        mutation_type="plan_patch",
        payload=serialize_plan_patch_confirmation(patch),
        expires_at=default_confirmation_expiry(self.user.timezone),
    )

    def fake_decide(*args, **kwargs):
        return None

    def fake_understanding(*args, **kwargs):
        from fitmas.decision.understanding import CoachUnderstanding, PendingResolution

        return CoachUnderstanding(
            intent="pending_response",
            confidence=0.96,
            user_summary="confirmation explicite",
            pending_resolution=PendingResolution(action="accept_pending", confidence=0.94),
        )

    deps = ConversationPipelineDependencies(decide=fake_decide)
    original = conversation_pipeline.build_shadow_understanding_for_turn
    conversation_pipeline.build_shadow_understanding_for_turn = fake_understanding
    self.addCleanup(lambda: setattr(conversation_pipeline, "build_shadow_understanding_for_turn", original))

    with unittest.mock.patch.dict(
        os.environ,
        {
            "FITMAS_UNDERSTANDING_RUNTIME_SHADOW": "1",
            "FITMAS_PENDING_FROM_UNDERSTANDING": "1",
            "FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER": "1",
        },
        clear=False,
    ):
        result = conversation_pipeline.run_conversation_turn(
            self.db,
            self.user,
            ConversationTurnInput(text="oui je confirme"),
            dependencies=deps,
        )

    self.assertTrue(result.mutation_applied)
    self.assertIsNone(repo.get_active_pending_mutation_confirmation(self.db, self.user.id))
    pending_rows = (
        self.db.query(s.PendingMutationConfirmation)
        .filter(s.PendingMutationConfirmation.user_id == self.user.id)
        .all()
    )
    self.assertEqual(len(pending_rows), 1)
    self.assertEqual(pending_rows[0].id, pending.id)
    self.assertEqual(pending_rows[0].status, "accepted")
```

- [ ] **Step 2: Run the specific regression**

Run:

```bash
./scripts/test-backend -q tests/test_core_flows.py -k "canonical_planning_cutover_confirmation_keeps_single_pending_row"
```

Expected:

```text
1 passed
```

---

## Task 5 - Classify Real Dogfood Failures

**Files:**

- Modify only if needed: `scripts/smoke_a_plus_api.py`
- Modify only if needed: `docs/DECISION-RUNTIME-REFACTOR.md`

- [ ] **Step 1: Run the wrapper once**

Run:

```bash
./scripts/smoke-decision-runtime-canonical-planning
```

Expected if stable:

```text
RESULT: OK (9 check(s))
```

Expected if unstable:

```text
RESULT: FAIL
```

For each failed scenario, capture:

```text
scenario name
assistant reply
events delta
pending delta
response_mode
failure label
responsible layer
```

- [ ] **Step 2: Fix only the responsible layer**

Use this routing table:

```text
understanding_bad_intent       -> understanding prompt/parser
requested_change_missing       -> canonical Understanding compilation
reference_resolution_gap       -> planning reference resolver
candidate_builder_gap          -> planning candidate builder
policy_gap                     -> planning policy
pending_gate_gap               -> pending bridge or shared pending gate
duplicate_pending              -> pending arbitration, never reply layer
reply_grounding_gap            -> reply composer/verifier
provider_timeout_or_json_error -> gateway/smoke, not planning logic
legacy_fallthrough_regression  -> conversation understanding/planning bridge
smoke_harness_gap              -> smoke script/tests
```

Do not fix a failed scenario by adding a new branch in `conversation_pipeline.py`
unless the failure is explicitly a bridge orchestration bug and the new code
removes or centralizes logic.

- [ ] **Step 3: Re-run the same failed scenario**

Run one scenario at a time:

```bash
FITMAS_UNDERSTANDING_RUNTIME_SHADOW=1 \
FITMAS_COMMANDS_FROM_UNDERSTANDING=1 \
FITMAS_PENDING_FROM_UNDERSTANDING=1 \
FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER=1 \
./scripts/smoke-a-plus-api --skip-generated-week --scenario move_easy_then_confirm --timeout 240
```

Replace `move_easy_then_confirm` with the failed scenario name.

Expected:

```text
RESULT: OK (1 check(s))
```

---

## Task 6 - Add Docs Evidence After Implementation

**Files:**

- Modify: `docs/DECISION-RUNTIME-REFACTOR.md`
- Modify: `docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md`
- Modify: `docs/BUILD-ORDER.md`
- Modify: `docs/README.md`

- [ ] **Step 1: Update `DECISION-RUNTIME-REFACTOR.md`**

Add a `Livres en Phase 8J` block after Phase 8I:

```text
Livres en Phase 8J :

- plan d'execution :
  `docs/superpowers/plans/2026-05-15-decision-runtime-phase-8j-canonical-planning-cutover.md` ;
- `scripts/smoke-decision-runtime-canonical-planning` active shadow
  Understanding, commandes canoniques, pending canonique et planning cutover ;
- `tests/test_phase8j_canonical_planning_cutover_architecture.py` verrouille
  que 8J reste opt-in et separe du wrapper 8I ;
- `scripts/smoke_a_plus_api.py` echoue sur duplicate pending et sur
  confirmation nue qui write sous cutover canonique ;
- la matrice planning 8J couvre `move_easy_then_confirm`, `swap_by_day`,
  `lighten_tomorrow`, `replace_swim_with_bike`, `future_evening_unavailable`,
  `fatigue_tomorrow`, `avoid_back_to_back`, `swim_unavailable_two_weeks` et
  `confirm_without_pending`.

Tests Phase 8J :

- targeted 8J :
  `./scripts/test-backend -q tests/test_phase8j_canonical_planning_cutover_architecture.py tests/test_smoke_a_plus_api.py -k "canonical_planning"` ;
- wrapper canonical planning :
  `./scripts/smoke-decision-runtime-canonical-planning` ;
- architecture pack Phase 8 :
  `./scripts/test-backend -q tests/test_decision_runtime_architecture.py tests/test_phase8a_legacy_audit.py tests/test_phase8b_cutover_architecture.py tests/test_phase8c_legacy_kill_architecture.py tests/test_phase8d_bridge_shrink_architecture.py tests/test_phase8e_understanding_cutover_architecture.py tests/test_phase8f_command_extraction_architecture.py tests/test_phase8g_pending_resolution_architecture.py tests/test_phase8h_pending_reply_architecture.py tests/test_phase8i_canonical_flag_dogfood_architecture.py tests/test_phase8j_canonical_planning_cutover_architecture.py` ;
- verification complete :
  `./scripts/test-backend -q`.

Dette restante apres Phase 8J :

- flags canoniques encore off par defaut ;
- `CoachDecision` reste provider actif ;
- `decide()` reste a refactorer apres preuve cutover ;
- `conversation_pipeline.py` reste a shrinker ;
- services root encore a migrer vers `domain/*`.
```

When implementing, append the real pass/fail counts after each command in this
block. Keep the command text intact so future agents can rerun the same gates.

- [ ] **Step 2: Update `DECISION-RUNTIME-LEGACY-KILL-LIST.md`**

Add a `Phase 8J` status block:

```text
Phase 8J dogfood le planning cutover canonique :

- wrapper dedie `scripts/smoke-decision-runtime-canonical-planning` ;
- `FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER=1` reste opt-in ;
- duplicate pending devient un hard fail du smoke evaluator ;
- les scenarios planning larges restent artifact-coherent sous cutover ;
- aucun chemin legacy nouveau n'est autorise.
```

- [ ] **Step 3: Update `BUILD-ORDER.md`**

Add Phase 8J evidence under the Phase 8 section and make the next decision
explicit:

```text
Apres 8J, choisir entre :

1. 8K default-enable un sous-ensemble canonique si la matrice passe.
2. 8J-fix par classification si un scenario echoue.
3. Refactor `decide()` seulement apres stabilisation du cutover.
```

- [ ] **Step 4: Update `README.md`**

Add:

```text
- `superpowers/plans/2026-05-15-decision-runtime-phase-8j-canonical-planning-cutover.md` — Phase 8J : dogfood strict du planning cutover canonique.
```

---

## Task 7 - Verification Gate

Run these commands before claiming 8J complete:

```bash
./scripts/test-backend -q \
  tests/test_phase8j_canonical_planning_cutover_architecture.py \
  tests/test_smoke_a_plus_api.py -k "canonical_planning"
```

Expected:

```text
8 passed
```

Run:

```bash
./scripts/test-backend -q \
  tests/test_core_flows.py -k "canonical_pending_accept_survives_legacy_decide_none or post_decide_candidate_flow_respects_active_pending_gate or canonical_planning_cutover_confirmation_keeps_single_pending_row"
```

Expected:

```text
3 passed
```

Run:

```bash
./scripts/test-backend -q \
  tests/test_decision_runtime_architecture.py \
  tests/test_phase8a_legacy_audit.py \
  tests/test_phase8b_cutover_architecture.py \
  tests/test_phase8c_legacy_kill_architecture.py \
  tests/test_phase8d_bridge_shrink_architecture.py \
  tests/test_phase8e_understanding_cutover_architecture.py \
  tests/test_phase8f_command_extraction_architecture.py \
  tests/test_phase8g_pending_resolution_architecture.py \
  tests/test_phase8h_pending_reply_architecture.py \
  tests/test_phase8i_canonical_flag_dogfood_architecture.py \
  tests/test_phase8j_canonical_planning_cutover_architecture.py
```

Expected:

```text
all selected architecture tests pass
```

Run:

```bash
./scripts/smoke-decision-runtime-canonical-planning
```

Expected:

```text
RESULT: OK (9 check(s))
```

Run:

```bash
./scripts/test-backend -q
```

Expected:

```text
full backend suite passes
```

## Acceptance Criteria

8J is complete only if:

```text
1. The dedicated 8J wrapper exists and enables planning cutover explicitly.
2. The 8I wrapper still excludes planning cutover.
3. Duplicate pending is a smoke hard failure.
4. `confirm_without_pending` cannot write under canonical planning cutover.
5. `move_easy_then_confirm` can accept without creating a second pending.
6. The planning scenario matrix passes or every failure is classified and fixed.
7. No canonical flag is default-enabled.
8. No new free-text parser, regex or keyword shortcut is added.
9. No new visible reply path appears outside ReplyComposer.
10. Docs include real verification evidence.
```

## After 8J

If 8J is green:

```text
Phase 8K = default-enable the safest canonical lane.
Preferred first candidate: pending from Understanding or commands from Understanding,
not full planning cutover.
```

If 8J is unstable:

```text
Do 8J-fix by failure label.
Do not refactor `decide()` until planning cutover failures are understood.
```

`decide()` should still be refactored, but after this proof. The refactor will
be safer once we know which parts of the legacy decision contract are still
needed only for provider compatibility and which parts are masking real
canonical gaps.
