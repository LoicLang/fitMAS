---
summary: implementation plan for Decision Runtime Phase 8I canonical flag dogfood
read_when:
  - implementing Decision Runtime Phase 8I
  - proving CoachUnderstanding can drive memory, execution and pending under flags
  - running canonical flag dogfood without removing CoachDecision
  - deciding whether canonical Understanding can become default later
---

# Decision Runtime Phase 8I Canonical Flag Dogfood Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove, under explicit flags only, that canonical `CoachUnderstanding` can safely carry memory commands, execution commands and pending resolution through real conversation paths.

**Architecture:** 8I is a dogfood proof, not a legacy deletion. `CoachDecision` remains the default provider contract. The canonical path is exercised only behind `FITMAS_UNDERSTANDING_RUNTIME_SHADOW=1`, `FITMAS_COMMANDS_FROM_UNDERSTANDING=1` and `FITMAS_PENDING_FROM_UNDERSTANDING=1`, with optional targeted planning cutover via `FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER=1`.

**Tech Stack:** Python 3.13, pytest/unittest, existing FastAPI smoke scripts, SQLAlchemy test DB fixtures, zsh smoke wrapper.

---

## CTO Decision

Do 8I before more shrink.

Reason:

```text
8F extracted commands.
8G extracted pending resolution.
8H extracted pending speech.

Now we need proof that canonical Understanding can actually drive those
bridges before we make it default or delete CoachDecision.
```

This phase must avoid false confidence.

Good outcome:

```text
flags on -> canonical commands/pending work in targeted paths
flags off -> current dogfood behavior unchanged
smokes show no ghost commit, no fake pending accept, no claim without event
```

Bad outcome:

```text
turn on flags globally
delete legacy provider
shrink conversation_pipeline before proving canonical artifacts are stable
```

## Scope

8I includes:

```text
1. Architecture gates for canonical flag dogfood.
2. Unit tests proving `FITMAS_COMMANDS_FROM_UNDERSTANDING`.
3. Unit tests proving `FITMAS_PENDING_FROM_UNDERSTANDING`.
4. A smoke wrapper that runs targeted dogfood with canonical flags.
5. One optional targeted planning cutover smoke, kept explicit and separate.
6. Docs update with evidence and remaining debt.
```

8I does not include:

```text
1. Default-enabling canonical flags.
2. Removing `CoachDecision`.
3. Removing `llm/decision_legacy.py`.
4. Removing `conversation_prompt_modules.py`.
5. Removing `final_reply.py`.
6. Moving memory/execution root services into `domain/*`.
7. Large `conversation_pipeline.py` shrink.
```

## Non-Negotiables

```text
1. No deterministic parsing of free user text.
2. No new regex/keywords on user messages.
3. No new writer path outside command bridges/services.
4. No visible reply path outside `DecisionOutcome -> ReplyComposer` for newly touched pending/plan replies.
5. All canonical flags remain off by default.
6. If canonical commands are empty, fallback to `CoachDecision` remains explicit.
7. Pending accept/reject still requires structured `pending_resolution`.
8. `decision/` stays pure.
9. Smokes must report artifacts: events delta, pending delta, response mode.
```

## File Map

Create:

```text
tests/test_phase8i_canonical_flag_dogfood_architecture.py
scripts/smoke-decision-runtime-canonical-flags
```

Modify:

```text
tests/test_conversation_command_bridge.py
tests/test_conversation_pending_bridge.py
docs/DECISION-RUNTIME-REFACTOR.md
docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md
docs/BUILD-ORDER.md
docs/README.md
```

Modify only if a failing test proves it necessary:

```text
backend/src/fitmas/legacy/conversation_command_bridge.py
backend/src/fitmas/legacy/coach_command_adapter.py
backend/src/fitmas/legacy/conversation_pending_bridge.py
backend/src/fitmas/legacy/conversation_understanding_bridge.py
```

Do not modify:

```text
backend/src/fitmas/llm/decision_legacy.py
backend/src/fitmas/conversation_prompt_modules.py
backend/src/fitmas/final_reply.py
backend/src/fitmas/conversation_pipeline.py
backend/src/fitmas/tools/registry.py
```

## Target Flow Under Flags

```text
User message
  -> legacy CoachDecision still runs
  -> canonical Understanding shadow runs
  -> command bridge chooses canonical commands if flag + commands exist
  -> pending bridge chooses canonical pending if flag + pending exists
  -> planning may optionally consume canonical requested_change if planning cutover flag is on
  -> writes still go through CommandBus / PlanMutationService
  -> replies still come from composed outcomes
```

Flags:

```text
FITMAS_UNDERSTANDING_RUNTIME_SHADOW=1
FITMAS_COMMANDS_FROM_UNDERSTANDING=1
FITMAS_PENDING_FROM_UNDERSTANDING=1
```

Optional targeted planning flag:

```text
FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER=1
```

Do not put the optional planning flag into the default smoke wrapper until its
single targeted smoke is stable.

---

## Task 1 — Add 8I Architecture Gates

**Files:**

- Create: `tests/test_phase8i_canonical_flag_dogfood_architecture.py`

- [x] **Step 1: Write failing architecture tests**

Create `tests/test_phase8i_canonical_flag_dogfood_architecture.py`:

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


def test_8i_canonical_flags_exist_and_default_off() -> None:
    understanding = _source("legacy/conversation_understanding_bridge.py")
    commands = _source("legacy/conversation_command_bridge.py")
    pending = _source("legacy/conversation_pending_bridge.py")

    assert "FITMAS_UNDERSTANDING_RUNTIME_SHADOW" in understanding
    assert "FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER" in understanding
    assert "FITMAS_COMMANDS_FROM_UNDERSTANDING" in commands
    assert "FITMAS_PENDING_FROM_UNDERSTANDING" in pending
    assert "return str(os.getenv(\"FITMAS_UNDERSTANDING_RUNTIME_SHADOW\") or \"\").strip() in" in understanding
    assert "return os.getenv(\"FITMAS_COMMANDS_FROM_UNDERSTANDING\", \"\").strip().lower() in" in commands
    assert "return os.getenv(\"FITMAS_PENDING_FROM_UNDERSTANDING\", \"\").strip().lower() in" in pending


def test_8i_dogfood_smoke_wrapper_exists() -> None:
    script = ROOT / "scripts" / "smoke-decision-runtime-canonical-flags"

    assert script.exists()
    source = script.read_text(encoding="utf-8")
    assert "FITMAS_UNDERSTANDING_RUNTIME_SHADOW=1" in source
    assert "FITMAS_COMMANDS_FROM_UNDERSTANDING=1" in source
    assert "FITMAS_PENDING_FROM_UNDERSTANDING=1" in source
    assert "FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER=1" not in source
    assert "smoke-real-conversations" in source
    assert "smoke-a-plus-api" in source


def test_8i_decision_package_stays_pure() -> None:
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

- [x] **Step 2: Run test to verify it fails**

Run:

```bash
./scripts/test-backend -q tests/test_phase8i_canonical_flag_dogfood_architecture.py
```

Expected:

```text
FAIL because `scripts/smoke-decision-runtime-canonical-flags` does not exist yet.
```

---

## Task 2 — Prove Commands From Understanding

**Files:**

- Modify: `tests/test_conversation_command_bridge.py`
- Modify only if needed: `backend/src/fitmas/legacy/conversation_command_bridge.py`
- Modify only if needed: `backend/src/fitmas/legacy/coach_command_adapter.py`

- [x] **Step 1: Add canonical command tests**

Add imports to `tests/test_conversation_command_bridge.py`:

```python
from fitmas.decision import CoachUnderstanding, UserSignal
```

Add this helper:

```python
def _understanding_with_availability_signal() -> CoachUnderstanding:
    return CoachUnderstanding(
        intent="availability_signal",
        confidence=0.91,
        user_summary="Piscine indisponible pendant deux semaines.",
        extracted_signals=(
            UserSignal(
                type="availability",
                label="piscine fermee",
                status="new",
                severity="medium",
                confidence=0.9,
                evidence="piscine fermee deux semaines",
                payload={
                    "availability": "unavailable",
                    "sport_type": "swimming",
                    "scope": "sport",
                    "starts_on": "2026-05-15",
                    "ends_on": "2026-05-29",
                    "window_text": "piscine fermee deux semaines",
                },
            ),
        ),
        requested_change=None,
        pending_resolution=None,
        clarification_need=None,
    )
```

Add tests:

```python
def test_commands_from_understanding_flag_uses_canonical_commands(self) -> None:
    writes: list[dict] = []
    decision = CoachDecision(
        response_type="reply",
        rationale="legacy has no actions",
        fitmas_message="ok",
        memory_actions=(),
    )

    old_flag = os.environ.get("FITMAS_COMMANDS_FROM_UNDERSTANDING")
    os.environ["FITMAS_COMMANDS_FROM_UNDERSTANDING"] = "1"
    try:
        metrics = apply_coach_decision_commands(
            db=self.db,
            user=self.user,
            decision=decision,
            turn_memory_writes=writes,
            unresolved_execution_followup=None,
            turn_plan=None,
            canonical_understanding=_understanding_with_availability_signal(),
        )
    finally:
        if old_flag is None:
            os.environ.pop("FITMAS_COMMANDS_FROM_UNDERSTANDING", None)
        else:
            os.environ["FITMAS_COMMANDS_FROM_UNDERSTANDING"] = old_flag

    self.assertEqual(metrics["command_source"], "coach_understanding")
    self.assertEqual(metrics["memory_applied"], 1)
    self.assertEqual(writes[0]["source"], "coach_understanding")


def test_commands_from_understanding_flag_falls_back_when_empty(self) -> None:
    writes: list[dict] = []
    decision = CoachDecision(
        response_type="reply",
        rationale="legacy carries memory action",
        fitmas_message="ok",
        memory_actions=(
            AvailabilityConstraintAction(
                type="record_availability",
                window_text="piscine fermee",
                availability="unavailable",
                sport_type="swimming",
                starts_on="2026-05-15",
                ends_on="2026-05-29",
                confidence=0.9,
                evidence="legacy action",
            ),
        ),
    )
    empty_understanding = CoachUnderstanding(
        intent="general_answer",
        confidence=0.7,
        user_summary="no command",
        extracted_signals=(),
        requested_change=None,
        pending_resolution=None,
        clarification_need=None,
    )

    old_flag = os.environ.get("FITMAS_COMMANDS_FROM_UNDERSTANDING")
    os.environ["FITMAS_COMMANDS_FROM_UNDERSTANDING"] = "1"
    try:
        metrics = apply_coach_decision_commands(
            db=self.db,
            user=self.user,
            decision=decision,
            turn_memory_writes=writes,
            unresolved_execution_followup=None,
            turn_plan=None,
            canonical_understanding=empty_understanding,
        )
    finally:
        if old_flag is None:
            os.environ.pop("FITMAS_COMMANDS_FROM_UNDERSTANDING", None)
        else:
            os.environ["FITMAS_COMMANDS_FROM_UNDERSTANDING"] = old_flag

    self.assertEqual(metrics["command_source"], "coach_decision")
    self.assertEqual(metrics["memory_applied"], 1)
    self.assertEqual(writes[0]["source"], "coach_decision")
```

- [x] **Step 2: Run tests to verify current state**

Run:

```bash
./scripts/test-backend -q tests/test_conversation_command_bridge.py
```

Expected:

```text
PASS if the existing 8F bridge already supports the flag.
If FAIL, fix only `legacy/conversation_command_bridge.py` or `legacy/coach_command_adapter.py`.
```

- [x] **Step 3: If needed, fix canonical command adapter only**

Allowed fix pattern:

```python
def _command_bundle(
    *,
    decision: Any,
    turn_plan: Any | None,
    canonical_understanding: CoachUnderstanding | None,
) -> CoachCommandBundle:
    if commands_from_understanding_enabled() and isinstance(canonical_understanding, CoachUnderstanding):
        bundle = commands_from_understanding(canonical_understanding)
        if bundle.commands:
            return bundle
        logger.info("canonical_understanding_commands_empty falling_back_to_legacy_decision")
    return commands_from_legacy_decision(decision, turn_plan=turn_plan)
```

Do not add parsing of `user_text`.

---

## Task 3 — Prove Pending From Understanding

**Files:**

- Modify: `tests/test_conversation_pending_bridge.py`
- Modify only if needed: `backend/src/fitmas/legacy/conversation_pending_bridge.py`

- [x] **Step 1: Add canonical pending precedence tests**

Add this test to `tests/test_conversation_pending_bridge.py`:

```python
def test_canonical_understanding_pending_resolution_wins_when_flag_enabled(self) -> None:
    session = self._scheduled_session()
    target_date = (session.scheduled_date.date() + timedelta(days=2)).isoformat()
    pending = self._pending_plan_patch(
        PlanPatch(
            coach_message="Je deplace la seance.",
            operations=(
                PlanPatchOperation(
                    operation_type="move_session",
                    target_session_id=session.id,
                    target_date=target_date,
                    rationale="Demande a confirmer.",
                ),
            ),
        )
    )
    decision = CoachDecision(
        response_type="no_change",
        rationale="legacy thinks accept",
        fitmas_message="legacy must not decide",
        pending_resolution=llm.AcceptPendingResolution(type="accept_pending"),
    )
    understanding = CoachUnderstanding(
        intent="pending_response",
        confidence=0.9,
        user_summary="Le user refuse finalement.",
        extracted_signals=(),
        requested_change=None,
        pending_resolution=PendingResolution(
            type="reject_pending",
            reason="refus explicite",
            selected_candidate_id=None,
            requested_changes=None,
            question=None,
        ),
        clarification_need=None,
    )

    old_flag = os.environ.get("FITMAS_PENDING_FROM_UNDERSTANDING")
    os.environ["FITMAS_PENDING_FROM_UNDERSTANDING"] = "1"
    try:
        outcome = conversation_pending_bridge.apply_pending_resolution(
            db=self.db,
            user=self.user,
            decision=decision,
            canonical_understanding=understanding,
            pending_confirmation=pending,
            user_text="non",
            verify_pending_accept_resolution_fn=lambda **kwargs: "reject_pending",
        )
    finally:
        if old_flag is None:
            os.environ.pop("FITMAS_PENDING_FROM_UNDERSTANDING", None)
        else:
            os.environ["FITMAS_PENDING_FROM_UNDERSTANDING"] = old_flag

    self.db.expire_all()
    refreshed = repo.get_scheduled_session(self.db, self.user.id, session.id)
    refreshed_pending = self.db.get(s.PendingMutationConfirmation, pending.id)
    self.assertIsNotNone(outcome)
    self.assertEqual(outcome.response_mode, "pending_rejected")
    self.assertFalse(outcome.mutation_applied)
    self.assertNotEqual(refreshed.scheduled_date.date().isoformat(), target_date)
    self.assertEqual(refreshed_pending.status, "rejected")
```

Add fallback test:

```python
def test_pending_from_understanding_flag_falls_back_when_canonical_has_no_pending(self) -> None:
    session = self._scheduled_session()
    target_date = (session.scheduled_date.date() + timedelta(days=2)).isoformat()
    pending = self._pending_plan_patch(
        PlanPatch(
            coach_message="Je deplace la seance.",
            operations=(
                PlanPatchOperation(
                    operation_type="move_session",
                    target_session_id=session.id,
                    target_date=target_date,
                    rationale="Demande confirmee.",
                ),
            ),
        )
    )
    decision = CoachDecision(
        response_type="no_change",
        rationale="legacy accept",
        fitmas_message="legacy accept",
        pending_resolution=llm.AcceptPendingResolution(type="accept_pending"),
    )
    understanding = CoachUnderstanding(
        intent="general_answer",
        confidence=0.7,
        user_summary="pas de pending canonical",
        extracted_signals=(),
        requested_change=None,
        pending_resolution=None,
        clarification_need=None,
    )

    old_flag = os.environ.get("FITMAS_PENDING_FROM_UNDERSTANDING")
    os.environ["FITMAS_PENDING_FROM_UNDERSTANDING"] = "1"
    try:
        outcome = conversation_pending_bridge.apply_pending_resolution(
            db=self.db,
            user=self.user,
            decision=decision,
            canonical_understanding=understanding,
            pending_confirmation=pending,
            user_text="oui",
            verify_pending_accept_resolution_fn=lambda **kwargs: "accept_pending",
        )
    finally:
        if old_flag is None:
            os.environ.pop("FITMAS_PENDING_FROM_UNDERSTANDING", None)
        else:
            os.environ["FITMAS_PENDING_FROM_UNDERSTANDING"] = old_flag

    self.db.expire_all()
    refreshed = repo.get_scheduled_session(self.db, self.user.id, session.id)
    self.assertIsNotNone(outcome)
    self.assertEqual(outcome.response_mode, "pending_accepted")
    self.assertTrue(outcome.mutation_applied)
    self.assertEqual(refreshed.scheduled_date.date().isoformat(), target_date)
```

- [x] **Step 2: Run tests**

Run:

```bash
./scripts/test-backend -q tests/test_conversation_pending_bridge.py
```

Expected:

```text
PASS if the existing 8G bridge already supports canonical precedence/fallback.
If FAIL, fix only `legacy/conversation_pending_bridge.py`.
```

- [x] **Step 3: If needed, preserve this source rule**

Allowed source rule:

```python
def pending_resolution_from_sources(
    *,
    decision: Any,
    canonical_understanding: CoachUnderstanding | None,
) -> PendingResolutionArtifact | None:
    if pending_from_understanding_enabled() and isinstance(canonical_understanding, CoachUnderstanding):
        artifact = _artifact_from_resolution(
            canonical_understanding.pending_resolution,
            source="coach_understanding",
        )
        if artifact is not None:
            return artifact
    return _artifact_from_resolution(getattr(decision, "pending_resolution", None), source="coach_decision")
```

Do not add deterministic yes/no parsing.

---

## Task 4 — Add Canonical Flag Smoke Wrapper

**Files:**

- Create: `scripts/smoke-decision-runtime-canonical-flags`

- [x] **Step 1: Add script**

Create `scripts/smoke-decision-runtime-canonical-flags`:

```zsh
#!/usr/bin/env zsh

set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
cd "$repo_root"

export FITMAS_UNDERSTANDING_RUNTIME_SHADOW=1
export FITMAS_COMMANDS_FROM_UNDERSTANDING=1
export FITMAS_PENDING_FROM_UNDERSTANDING=1

echo "canonical flags:"
echo "  FITMAS_UNDERSTANDING_RUNTIME_SHADOW=$FITMAS_UNDERSTANDING_RUNTIME_SHADOW"
echo "  FITMAS_COMMANDS_FROM_UNDERSTANDING=$FITMAS_COMMANDS_FROM_UNDERSTANDING"
echo "  FITMAS_PENDING_FROM_UNDERSTANDING=$FITMAS_PENDING_FROM_UNDERSTANDING"

./scripts/test-backend -q \
  tests/test_conversation_understanding_bridge.py \
  tests/test_conversation_command_bridge.py \
  tests/test_conversation_pending_bridge.py

./scripts/smoke-real-conversations \
  --scenario execution_update \
  --scenario today_unavailability \
  --scenario fatigue_today \
  --scenario health_signal \
  --scenario heartbeat_non_completion

./scripts/smoke-a-plus-api \
  --scenario move_easy_then_confirm \
  --scenario confirm_without_pending \
  --timeout 240
```

- [x] **Step 2: Make script executable**

Run:

```bash
chmod +x scripts/smoke-decision-runtime-canonical-flags
```

- [x] **Step 3: Run architecture gate**

Run:

```bash
./scripts/test-backend -q tests/test_phase8i_canonical_flag_dogfood_architecture.py
```

Expected:

```text
PASS.
```

---

## Task 5 — Optional Targeted Planning Cutover Probe

**Files:**

- No code required unless the smoke exposes a bug.

- [x] **Step 1: Run one explicit planning cutover smoke**

Run:

```bash
FITMAS_UNDERSTANDING_RUNTIME_SHADOW=1 \
FITMAS_COMMANDS_FROM_UNDERSTANDING=1 \
FITMAS_PENDING_FROM_UNDERSTANDING=1 \
FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER=1 \
./scripts/smoke-a-plus-api --scenario move_easy_then_confirm --timeout 240
```

Expected:

```text
RESULT: OK.
events and pending artifacts must explain the visible reply.
```

- [x] **Step 2: If it fails, classify the failure**

Use this classification:

```text
understanding_bad_intent        -> fix llm/prompts/understanding.py or parser tests
reference_resolution_gap        -> fix domain/planning/reference_resolver.py
candidate_builder_gap           -> fix domain/planning/candidate_builder.py
policy_or_reviewer_gap          -> fix domain/planning/evaluator.py or policy.py
reply_contract_gap              -> fix reply composer/adapters
provider_timeout_or_json_error  -> document as provider instability, do not patch runtime blindly
```

Do not add a fallback in `conversation_pipeline.py`.

---

## Task 6 — Verification Pack

**Files:**

- No source changes unless a test proves a scoped bug.

- [x] **Step 1: Run 8I targeted tests**

Run:

```bash
./scripts/test-backend -q \
  tests/test_phase8i_canonical_flag_dogfood_architecture.py \
  tests/test_conversation_understanding_bridge.py \
  tests/test_conversation_command_bridge.py \
  tests/test_conversation_pending_bridge.py
```

Expected:

```text
PASS.
```

- [x] **Step 2: Run Phase 8 architecture pack**

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
  tests/test_phase8i_canonical_flag_dogfood_architecture.py
```

Expected:

```text
PASS.
```

- [x] **Step 3: Run full backend**

Run:

```bash
./scripts/test-backend -q
```

Expected:

```text
PASS.
```

- [x] **Step 4: Run canonical smoke wrapper**

Run:

```bash
./scripts/smoke-decision-runtime-canonical-flags
```

Expected:

```text
Unit gates PASS.
Selected real conversation smokes PASS.
Selected API smokes RESULT: OK.
```

---

## Task 7 — Update Durable Docs

**Files:**

- Modify: `docs/DECISION-RUNTIME-REFACTOR.md`
- Modify: `docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md`
- Modify: `docs/BUILD-ORDER.md`
- Modify: `docs/README.md`

- [x] **Step 1: Add Phase 8I status**

Document:

```text
Phase 8I proves canonical flags under dogfood:
- shadow Understanding on;
- commands from Understanding on;
- pending from Understanding on;
- planning cutover remains optional and explicit.
```

- [x] **Step 2: Add evidence**

Document exact command results after running them:

```text
8I targeted tests -> N passed
Phase 8 architecture pack -> N passed
full backend -> N passed, N skipped, N subtests passed
canonical smoke wrapper -> RESULT details
optional planning cutover smoke -> RESULT details or documented provider/runtime failure
```

- [x] **Step 3: Update next debt**

Document:

```text
If canonical flags are stable:
  next = choose 8J conversation_pipeline shrink or 8K default-enable one flag at a time.

If canonical flags are not stable:
  next = fix the specific layer shown by smoke classification.
```

- [x] **Step 4: Run docs list**

Run:

```bash
./scripts/docs:list | rg "8i|DECISION-RUNTIME|BUILD-ORDER|README"
```

Expected:

```text
The 8I plan appears and core docs still list correctly.
```

---

## Execution Evidence — 2026-05-15

```text
targeted 8I tests -> 21 passed
Phase 8 architecture pack -> 55 passed
full backend -> 1197 passed, 11 skipped, 11 subtests passed
canonical smoke wrapper -> unit gates 18 passed, real conversation smokes completed, API smokes RESULT: OK (2 checks)
duplicate pending hardening tests -> 2 passed
pending/core gate after hardening -> 40 passed
optional planning cutover probe after hardening -> RESULT: OK, events=+1, pending=+1, mode=pending_accepted
```

Observed caveats:

```text
1. The three canonical flags are safe to dogfood together, but remain off by default.
2. Real provider turns can still fall back to `command_source=coach_decision`.
3. Shadow Understanding adds high latency on real smokes, so wrappers use `--timeout 240`.
4. The duplicate pending gap is fixed for `move_easy_then_confirm`, but explicit planning cutover still needs broader dogfood before default enablement.
5. Next work should keep hardening canonical artifacts before default-enabling flags.
```

## Acceptance

```text
1. Canonical flag dogfood plan exists.
2. Architecture gates prove flags remain opt-in.
3. Command bridge proves canonical Understanding can apply memory/execution commands under flag.
4. Command bridge proves fallback to CoachDecision when canonical commands are empty.
5. Pending bridge proves canonical pending can win under flag.
6. Pending bridge proves fallback to CoachDecision when canonical pending is absent.
7. Smoke wrapper runs targeted dogfood with the three core canonical flags.
8. Optional planning cutover probe is run and classified.
9. Full backend passes.
10. Docs record exact evidence and remaining debt.
```

## Remaining Debt After 8I

```text
1. `CoachDecision` still remains provider default.
2. Canonical flags still remain off by default.
3. `FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER` is not globally trusted yet.
4. Real dogfood can still fall back to `command_source=coach_decision`.
5. Shadow Understanding latency is high enough to require longer smoke timeouts.
6. `final_reply.py` still remains backend legacy for some composed replies.
7. `conversation_pipeline.py` still needs shrink.
8. Root memory/execution/planning services still need final domain relocation.
```

## Recommended Next Slice

If 8I passes cleanly:

```text
8J — Conversation pipeline shrink:
  extract turn persistence, output guard routing and candidate orchestration.
```

If 8I exposes canonical instability:

```text
8I-fix — Targeted canonical hardening:
  fix the exact layer shown by the smoke classification before shrinking.
```

Do not default-enable canonical flags until at least two dogfood runs are clean.
