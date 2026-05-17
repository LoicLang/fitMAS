---
summary: implementation plan for Decision Runtime Phase 8K canonical non-planning defaults
read_when:
  - implementing Decision Runtime Phase 8K
  - default-enabling canonical Understanding for commands or pending
  - keeping planning cutover opt-in after Phase 8J
  - reducing CoachDecision authority without refactoring decide yet
---

# Decision Runtime Phase 8K Canonical Default Lanes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Make canonical `CoachUnderstanding` the default source for memory/execution commands and pending resolution, while keeping canonical planning cutover explicitly opt-in.

**Architecture:** 8K is a controlled default-enable slice, not a `decide()` refactor. Canonical Understanding should run by default only when a non-planning consumer needs it: active pending, execution/memory-capable turns, or explicit shadow mode. Planning still consumes canonical `RequestedPlanChange` only when `FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER=1`.

**Tech Stack:** Python 3.13, pytest/unittest, FastAPI smoke scripts, zsh smoke wrappers, SQLAlchemy test DB fixtures.

---

## CTO Decision

Do not default-enable full planning cutover yet.

8J proved the matrix, but the next safe move is narrower:

```text
commands from Understanding -> default on
pending from Understanding  -> default on
planning from Understanding -> still explicit
```

Reason:

```text
memory/execution/pending are easier to rollback and already have deterministic command bridges.
planning has broader policy/ref-resolution blast radius and remains a separate default decision.
```

The subtle part:

```text
If we turn commands/pending on but keep Understanding shadow off, nothing changes.
If we turn Understanding on globally, every trivial lookup pays another provider call.
```

So 8K introduces a scoped canonical Understanding gate:

```text
run canonical Understanding by default only when a default-on canonical consumer can use it
```

No free-text parser. The gate uses typed runtime artifacts only:

```text
pending_confirmation status
turn_plan primary/secondary intents
turn_plan has_plan_mutation / mutation_signal / availability/execution fields
explicit env flags
```

## Scope

8K includes:

```text
1. Default-enable `FITMAS_COMMANDS_FROM_UNDERSTANDING`.
2. Default-enable `FITMAS_PENDING_FROM_UNDERSTANDING`.
3. Keep `FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER` off by default.
4. Add scoped canonical Understanding execution for non-planning consumers.
5. Add opt-out rollback flags by setting command/pending/non-planning cutover to `0`.
6. Add a smoke wrapper proving defaults work without exporting commands/pending flags.
7. Update architecture docs with the new default boundary.
```

8K does not include:

```text
1. Refactoring `decide()`.
2. Removing `CoachDecision`.
3. Default-enabling canonical planning cutover.
4. Removing legacy `fitmas_message`.
5. Shrinking `conversation_pipeline.py`.
6. Adding deterministic user-text parsing.
7. Adding new prompt rules to compensate for backend gaps.
```

## Non-Negotiables

```text
1. No regex/keyword heuristic on free user text.
2. Default canonical Understanding must be scoped, not global-all-turns.
3. Commands and pending default on must still fallback to `CoachDecision` when canonical artifacts are absent.
4. Planning cutover remains opt-in.
5. Every default has a local env rollback.
6. The 8I explicit wrapper remains valid, even if some flags become redundant.
7. The 8J planning wrapper remains the only wrapper that sets planning cutover.
8. No new writer path outside CommandBus / PlanningCommandService.
9. No visible reply path outside `DecisionOutcome -> DecisionReplyComposer`.
```

## File Map

Create:

```text
tests/test_phase8k_canonical_default_lanes_architecture.py
scripts/smoke-decision-runtime-canonical-defaults
```

Modify:

```text
backend/src/fitmas/legacy/conversation_understanding_bridge.py
backend/src/fitmas/legacy/conversation_command_bridge.py
backend/src/fitmas/legacy/conversation_pending_bridge.py
tests/test_conversation_understanding_bridge.py
tests/test_conversation_command_bridge.py
tests/test_conversation_pending_bridge.py
docs/DECISION-RUNTIME-REFACTOR.md
docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md
docs/BUILD-ORDER.md
docs/README.md
```

Do not modify:

```text
backend/src/fitmas/conversation_pipeline.py
backend/src/fitmas/llm/decision_legacy.py
backend/src/fitmas/conversation_prompt_modules.py
backend/src/fitmas/domain/planning/*
backend/src/fitmas/final_reply.py
backend/src/fitmas/tools/registry.py
```

If a test seems to require touching `conversation_pipeline.py`, stop and
classify the failure first. 8K should be bridge-level.

## Target Defaults

After 8K:

```text
FITMAS_COMMANDS_FROM_UNDERSTANDING default = on
FITMAS_PENDING_FROM_UNDERSTANDING default = on
FITMAS_CANONICAL_NON_PLANNING_CUTOVER default = on
FITMAS_UNDERSTANDING_RUNTIME_SHADOW default = off unless explicit all-turn shadow is requested
FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER default = off
```

Rollback examples:

```bash
FITMAS_COMMANDS_FROM_UNDERSTANDING=0
FITMAS_PENDING_FROM_UNDERSTANDING=0
FITMAS_CANONICAL_NON_PLANNING_CUTOVER=0
```

Explicit all-turn observability still works:

```bash
FITMAS_UNDERSTANDING_RUNTIME_SHADOW=1
```

Planning cutover remains explicit:

```bash
FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER=1
```

---

## Task 1 - Add 8K Architecture Gates

**Files:**

- Create: `tests/test_phase8k_canonical_default_lanes_architecture.py`

- [x] **Step 1: Write failing architecture tests**

Create `tests/test_phase8k_canonical_default_lanes_architecture.py`:

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


def test_8k_defaults_commands_and_pending_from_understanding_on() -> None:
    command_bridge = _source("legacy/conversation_command_bridge.py")
    pending_bridge = _source("legacy/conversation_pending_bridge.py")

    assert 'FITMAS_COMMANDS_FROM_UNDERSTANDING", default=True' in command_bridge
    assert 'FITMAS_PENDING_FROM_UNDERSTANDING", default=True' in pending_bridge
    assert "return _env_flag_enabled(" in command_bridge
    assert "return _env_flag_enabled(" in pending_bridge


def test_8k_keeps_planning_cutover_default_off() -> None:
    understanding = _source("legacy/conversation_understanding_bridge.py")

    assert 'FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER", default=False' in understanding


def test_8k_has_scoped_non_planning_understanding_gate() -> None:
    understanding = _source("legacy/conversation_understanding_bridge.py")

    assert "FITMAS_CANONICAL_NON_PLANNING_CUTOVER" in understanding
    assert "def should_run_canonical_understanding(" in understanding
    assert "pending_confirmation" in understanding
    assert "_turn_plan_can_produce_non_planning_commands" in understanding


def test_8k_default_smoke_wrapper_proves_defaults_without_exporting_command_or_pending_flags() -> None:
    script = ROOT / "scripts" / "smoke-decision-runtime-canonical-defaults"

    assert script.exists()
    source = script.read_text(encoding="utf-8")
    assert "FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER=0" in source
    assert "FITMAS_COMMANDS_FROM_UNDERSTANDING=1" not in source
    assert "FITMAS_PENDING_FROM_UNDERSTANDING=1" not in source
    assert "smoke-real-conversations" in source
    assert "smoke-a-plus-api" in source


def test_8k_decision_package_stays_pure() -> None:
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
./scripts/test-backend -q tests/test_phase8k_canonical_default_lanes_architecture.py
```

Expected:

```text
FAIL because the 8K wrapper and default helpers do not exist yet.
```

---

## Task 2 - Add Shared Env Flag Helpers And Default Commands/Pending On

**Files:**

- Modify: `backend/src/fitmas/legacy/conversation_command_bridge.py`
- Modify: `backend/src/fitmas/legacy/conversation_pending_bridge.py`
- Modify: `tests/test_conversation_command_bridge.py`
- Modify: `tests/test_conversation_pending_bridge.py`

- [x] **Step 1: Add failing tests for default-on and opt-out command source**

Add these tests to `tests/test_conversation_command_bridge.py`:

```python
    def test_commands_from_understanding_default_on_when_artifact_exists(self) -> None:
        writes: list[dict] = []
        decision = CoachDecision(
            response_type="reply",
            rationale="legacy has no actions",
            fitmas_message="ok",
            memory_actions=(),
        )

        old_flag = os.environ.pop("FITMAS_COMMANDS_FROM_UNDERSTANDING", None)
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
            if old_flag is not None:
                os.environ["FITMAS_COMMANDS_FROM_UNDERSTANDING"] = old_flag

        self.assertEqual(metrics["command_source"], "coach_understanding")
        self.assertEqual(metrics["memory_applied"], 1)
        self.assertEqual(writes[0]["source"], "coach_understanding")

    def test_commands_from_understanding_can_be_disabled(self) -> None:
        writes: list[dict] = []
        decision = CoachDecision(
            response_type="reply",
            rationale="legacy carries action",
            fitmas_message="ok",
            memory_actions=(
                AvailabilityConstraintAction(
                    type="record_availability",
                    window_text="piscine fermee",
                    availability="unavailable",
                    sport_type="swimming",
                    starts_on="2026-05-14",
                    ends_on="2026-05-28",
                    confidence=0.9,
                    evidence="piscine fermee",
                ),
            ),
        )

        old_flag = os.environ.get("FITMAS_COMMANDS_FROM_UNDERSTANDING")
        os.environ["FITMAS_COMMANDS_FROM_UNDERSTANDING"] = "0"
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

        self.assertEqual(metrics["command_source"], "coach_decision")
        self.assertEqual(writes[0]["source"], "coach_decision")
```

- [x] **Step 2: Add failing tests for default-on and opt-out pending source**

Add these tests to `tests/test_conversation_pending_bridge.py`:

```python
    def test_pending_from_understanding_default_on_when_artifact_exists(self) -> None:
        decision = CoachDecision(
            response_type="reply",
            rationale="legacy sans pending",
            fitmas_message="ok",
            pending_resolution=None,
        )
        understanding = CoachUnderstanding(
            intent="pending_response",
            confidence=0.92,
            user_summary="confirmation",
            pending_resolution=PendingResolution(type="accept_pending", reason="ok"),
        )

        old_flag = os.environ.pop("FITMAS_PENDING_FROM_UNDERSTANDING", None)
        try:
            artifact = conversation_pending_bridge.pending_resolution_from_sources(
                decision=decision,
                canonical_understanding=understanding,
            )
        finally:
            if old_flag is not None:
                os.environ["FITMAS_PENDING_FROM_UNDERSTANDING"] = old_flag

        self.assertIsNotNone(artifact)
        self.assertEqual(artifact.source, "coach_understanding")
        self.assertEqual(artifact.type, "accept_pending")

    def test_pending_from_understanding_can_be_disabled(self) -> None:
        decision = CoachDecision(
            response_type="reply",
            rationale="legacy pending",
            fitmas_message="ok",
            pending_resolution=llm.IgnorePendingResolution(type="ignore"),
        )
        understanding = CoachUnderstanding(
            intent="pending_response",
            confidence=0.92,
            user_summary="confirmation",
            pending_resolution=PendingResolution(type="accept_pending", reason="ok"),
        )

        old_flag = os.environ.get("FITMAS_PENDING_FROM_UNDERSTANDING")
        os.environ["FITMAS_PENDING_FROM_UNDERSTANDING"] = "0"
        try:
            artifact = conversation_pending_bridge.pending_resolution_from_sources(
                decision=decision,
                canonical_understanding=understanding,
            )
        finally:
            if old_flag is None:
                os.environ.pop("FITMAS_PENDING_FROM_UNDERSTANDING", None)
            else:
                os.environ["FITMAS_PENDING_FROM_UNDERSTANDING"] = old_flag

        self.assertIsNotNone(artifact)
        self.assertEqual(artifact.source, "coach_decision")
        self.assertEqual(artifact.type, "ignore")
```

- [x] **Step 3: Run tests to verify they fail**

Run:

```bash
./scripts/test-backend -q tests/test_conversation_command_bridge.py tests/test_conversation_pending_bridge.py -k "default_on or can_be_disabled"
```

Expected:

```text
FAIL because both bridges still default canonical source off.
```

- [x] **Step 4: Implement default-on env helper in command bridge**

Modify `backend/src/fitmas/legacy/conversation_command_bridge.py`:

```python
def _env_flag_enabled(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def commands_from_understanding_enabled() -> bool:
    return _env_flag_enabled("FITMAS_COMMANDS_FROM_UNDERSTANDING", default=True)
```

- [x] **Step 5: Implement default-on env helper in pending bridge**

Modify `backend/src/fitmas/legacy/conversation_pending_bridge.py`:

```python
def _env_flag_enabled(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def pending_from_understanding_enabled() -> bool:
    return _env_flag_enabled("FITMAS_PENDING_FROM_UNDERSTANDING", default=True)
```

- [x] **Step 6: Run tests to verify they pass**

Run:

```bash
./scripts/test-backend -q tests/test_conversation_command_bridge.py tests/test_conversation_pending_bridge.py -k "default_on or can_be_disabled"
```

Expected:

```text
4 passed
```

---

## Task 3 - Add Scoped Canonical Understanding Gate

**Files:**

- Modify: `backend/src/fitmas/legacy/conversation_understanding_bridge.py`
- Modify: `tests/test_conversation_understanding_bridge.py`

- [x] **Step 1: Add failing scoped-gate tests**

Add tests to `tests/test_conversation_understanding_bridge.py`:

```python
def test_default_non_planning_cutover_runs_for_active_pending(monkeypatch) -> None:
    monkeypatch.delenv("FITMAS_UNDERSTANDING_RUNTIME_SHADOW", raising=False)
    monkeypatch.delenv("FITMAS_CANONICAL_NON_PLANNING_CUTOVER", raising=False)
    monkeypatch.delenv("FITMAS_PENDING_FROM_UNDERSTANDING", raising=False)

    assert conversation_understanding_bridge.should_run_canonical_understanding(
        turn_plan=SimpleNamespace(primary_intent="close_turn", secondary_intents=(), has_plan_mutation=False),
        pending_confirmation=SimpleNamespace(status="pending"),
    )


def test_default_non_planning_cutover_runs_for_execution_turn(monkeypatch) -> None:
    monkeypatch.delenv("FITMAS_UNDERSTANDING_RUNTIME_SHADOW", raising=False)
    monkeypatch.delenv("FITMAS_CANONICAL_NON_PLANNING_CUTOVER", raising=False)
    monkeypatch.delenv("FITMAS_COMMANDS_FROM_UNDERSTANDING", raising=False)

    assert conversation_understanding_bridge.should_run_canonical_understanding(
        turn_plan=SimpleNamespace(
            primary_intent="execution_report",
            secondary_intents=(),
            has_plan_mutation=False,
            mutation_signal=False,
        ),
        pending_confirmation=None,
    )


def test_default_non_planning_cutover_skips_read_only_lookup(monkeypatch) -> None:
    monkeypatch.delenv("FITMAS_UNDERSTANDING_RUNTIME_SHADOW", raising=False)
    monkeypatch.delenv("FITMAS_CANONICAL_NON_PLANNING_CUTOVER", raising=False)

    assert not conversation_understanding_bridge.should_run_canonical_understanding(
        turn_plan=SimpleNamespace(primary_intent="plan_lookup", secondary_intents=(), has_plan_mutation=False),
        pending_confirmation=None,
    )


def test_non_planning_cutover_can_be_disabled(monkeypatch) -> None:
    monkeypatch.setenv("FITMAS_CANONICAL_NON_PLANNING_CUTOVER", "0")
    monkeypatch.delenv("FITMAS_UNDERSTANDING_RUNTIME_SHADOW", raising=False)

    assert not conversation_understanding_bridge.should_run_canonical_understanding(
        turn_plan=SimpleNamespace(primary_intent="execution_report", secondary_intents=(), has_plan_mutation=False),
        pending_confirmation=SimpleNamespace(status="pending"),
    )


def test_explicit_shadow_runs_even_when_non_planning_cutover_disabled(monkeypatch) -> None:
    monkeypatch.setenv("FITMAS_CANONICAL_NON_PLANNING_CUTOVER", "0")
    monkeypatch.setenv("FITMAS_UNDERSTANDING_RUNTIME_SHADOW", "1")

    assert conversation_understanding_bridge.should_run_canonical_understanding(
        turn_plan=SimpleNamespace(primary_intent="plan_lookup", secondary_intents=(), has_plan_mutation=False),
        pending_confirmation=None,
    )
```

- [x] **Step 2: Run tests to verify they fail**

Run:

```bash
./scripts/test-backend -q tests/test_conversation_understanding_bridge.py -k "non_planning_cutover or scoped or explicit_shadow"
```

Expected:

```text
FAIL because `should_run_canonical_understanding` does not exist.
```

- [x] **Step 3: Implement scoped gate**

Modify `backend/src/fitmas/legacy/conversation_understanding_bridge.py`:

```python
_COMMAND_INTENTS = {
    "execution_report",
    "health_signal",
    "availability_signal",
    "preference_signal",
    "memory_update",
}


def _env_flag_enabled(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def understanding_runtime_shadow_enabled() -> bool:
    return _env_flag_enabled("FITMAS_UNDERSTANDING_RUNTIME_SHADOW", default=False)


def understanding_runtime_planning_cutover_enabled() -> bool:
    return _env_flag_enabled("FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER", default=False)


def canonical_non_planning_cutover_enabled() -> bool:
    return _env_flag_enabled("FITMAS_CANONICAL_NON_PLANNING_CUTOVER", default=True)


def _commands_from_understanding_default_enabled() -> bool:
    return _env_flag_enabled("FITMAS_COMMANDS_FROM_UNDERSTANDING", default=True)


def _pending_from_understanding_default_enabled() -> bool:
    return _env_flag_enabled("FITMAS_PENDING_FROM_UNDERSTANDING", default=True)


def should_run_canonical_understanding(*, turn_plan, pending_confirmation) -> bool:
    if understanding_runtime_shadow_enabled():
        return True
    if not canonical_non_planning_cutover_enabled():
        return False
    if _pending_from_understanding_default_enabled() and _has_active_pending(pending_confirmation):
        return True
    if _commands_from_understanding_default_enabled() and _turn_plan_can_produce_non_planning_commands(turn_plan):
        return True
    return False


def _has_active_pending(pending_confirmation) -> bool:
    return pending_confirmation is not None and str(getattr(pending_confirmation, "status", "") or "") == "pending"


def _turn_plan_can_produce_non_planning_commands(turn_plan) -> bool:
    if turn_plan is None:
        return False
    intents = {
        str(getattr(turn_plan, "primary_intent", "") or ""),
        *(str(item or "") for item in tuple(getattr(turn_plan, "secondary_intents", ()) or ())),
    }
    if intents.intersection(_COMMAND_INTENTS):
        return True
    if getattr(turn_plan, "availability_constraint", None) is not None:
        return True
    if getattr(turn_plan, "execution_update", None) is not None:
        return True
    return False
```

Then replace the first line of `run_canonical_understanding_shadow`:

```python
    if not should_run_canonical_understanding(turn_plan=turn_plan, pending_confirmation=pending_confirmation):
        return None
```

- [x] **Step 4: Run tests to verify they pass**

Run:

```bash
./scripts/test-backend -q tests/test_conversation_understanding_bridge.py -k "non_planning_cutover or scoped or explicit_shadow"
```

Expected:

```text
5 passed
```

---

## Task 4 - Update 8I Tests Into Historical Flag Tests

**Files:**

- Modify: `tests/test_phase8i_canonical_flag_dogfood_architecture.py`

- [x] **Step 1: Update the old default-off assertion**

Replace `test_8i_canonical_flags_exist_and_default_off` with:

```python
def test_8i_canonical_flags_and_8k_defaults_are_documented() -> None:
    understanding = _source("legacy/conversation_understanding_bridge.py")
    commands = _source("legacy/conversation_command_bridge.py")
    pending = _source("legacy/conversation_pending_bridge.py")

    assert "FITMAS_UNDERSTANDING_RUNTIME_SHADOW" in understanding
    assert "FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER" in understanding
    assert "FITMAS_CANONICAL_NON_PLANNING_CUTOVER" in understanding
    assert "FITMAS_COMMANDS_FROM_UNDERSTANDING" in commands
    assert "FITMAS_PENDING_FROM_UNDERSTANDING" in pending
    assert 'FITMAS_COMMANDS_FROM_UNDERSTANDING", default=True' in commands
    assert 'FITMAS_PENDING_FROM_UNDERSTANDING", default=True' in pending
    assert 'FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER", default=False' in understanding
```

- [x] **Step 2: Run tests**

Run:

```bash
./scripts/test-backend -q tests/test_phase8i_canonical_flag_dogfood_architecture.py tests/test_phase8k_canonical_default_lanes_architecture.py
```

Expected:

```text
all selected tests pass
```

---

## Task 5 - Add Default-Lanes Smoke Wrapper

**Files:**

- Create: `scripts/smoke-decision-runtime-canonical-defaults`

- [x] **Step 1: Create wrapper**

Create `scripts/smoke-decision-runtime-canonical-defaults`:

```zsh
#!/usr/bin/env zsh

set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
cd "$repo_root"

unset FITMAS_UNDERSTANDING_RUNTIME_SHADOW
unset FITMAS_COMMANDS_FROM_UNDERSTANDING
unset FITMAS_PENDING_FROM_UNDERSTANDING
unset FITMAS_CANONICAL_NON_PLANNING_CUTOVER
export FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER=0

echo "canonical default lanes:"
echo "  FITMAS_COMMANDS_FROM_UNDERSTANDING=<default on>"
echo "  FITMAS_PENDING_FROM_UNDERSTANDING=<default on>"
echo "  FITMAS_CANONICAL_NON_PLANNING_CUTOVER=<default on>"
echo "  FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER=$FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER"

./scripts/test-backend -q \
  tests/test_phase8k_canonical_default_lanes_architecture.py \
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
  --skip-generated-week \
  --scenario move_easy_then_confirm \
  --scenario confirm_without_pending \
  --timeout 240
```

- [x] **Step 2: Make wrapper executable**

Run:

```bash
chmod +x scripts/smoke-decision-runtime-canonical-defaults
```

- [x] **Step 3: Run architecture wrapper test**

Run:

```bash
./scripts/test-backend -q tests/test_phase8k_canonical_default_lanes_architecture.py
```

Expected:

```text
5 passed
```

---

## Task 6 - Run Default-Lane Dogfood And Fix Only Responsible Layers

**Files:**

- Modify only if needed: bridge files listed above
- Do not modify: `conversation_pipeline.py`

- [x] **Step 1: Run the wrapper**

Run:

```bash
./scripts/smoke-decision-runtime-canonical-defaults
```

Expected:

```text
unit gates pass
real conversation smokes pass
API smokes RESULT: OK
```

- [x] **Step 2: If failure occurs, classify**

Use this table:

```text
understanding_not_run_when_needed -> scoped gate too narrow
understanding_run_on_lookup       -> scoped gate too broad
canonical_command_missing         -> coach_command_adapter gap
canonical_pending_missing         -> pending bridge gap
legacy_fallback_expected          -> acceptable if canonical artifact absent
reply_grounding_gap               -> reply composer/verifier, not command bridge
provider_timeout_or_json_error    -> gateway/provider, not architecture
planning_cutover_leak             -> planning flag regression, block immediately
```

- [x] **Step 3: Re-run failed scenario only**

Example:

```bash
./scripts/smoke-real-conversations --scenario execution_update
```

or:

```bash
./scripts/smoke-a-plus-api --skip-generated-week --scenario move_easy_then_confirm --timeout 240
```

Expected:

```text
scenario passes after the responsible-layer fix
```

---

## Task 7 - Documentation Updates

**Files:**

- Modify: `docs/DECISION-RUNTIME-REFACTOR.md`
- Modify: `docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md`
- Modify: `docs/BUILD-ORDER.md`
- Modify: `docs/README.md`

- [x] **Step 1: Update `DECISION-RUNTIME-REFACTOR.md`**

Add a Phase 8K block after 8J:

```text
Livres en Phase 8K :

- `FITMAS_COMMANDS_FROM_UNDERSTANDING` est default-on avec opt-out `0` ;
- `FITMAS_PENDING_FROM_UNDERSTANDING` est default-on avec opt-out `0` ;
- `FITMAS_CANONICAL_NON_PLANNING_CUTOVER` lance Understanding par defaut
  uniquement pour les tours ou commandes/pending peuvent consommer l'artefact ;
- `FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER` reste off par defaut ;
- `scripts/smoke-decision-runtime-canonical-defaults` prouve les defaults sans
  exporter les flags commands/pending.

Tests Phase 8K :

- targeted 8K :
  `./scripts/test-backend -q tests/test_phase8k_canonical_default_lanes_architecture.py tests/test_conversation_understanding_bridge.py tests/test_conversation_command_bridge.py tests/test_conversation_pending_bridge.py` ;
- wrapper defaults :
  `./scripts/smoke-decision-runtime-canonical-defaults` ;
- architecture pack Phase 8 :
  `./scripts/test-backend -q tests/test_decision_runtime_architecture.py tests/test_phase8a_legacy_audit.py tests/test_phase8b_cutover_architecture.py tests/test_phase8c_legacy_kill_architecture.py tests/test_phase8d_bridge_shrink_architecture.py tests/test_phase8e_understanding_cutover_architecture.py tests/test_phase8f_command_extraction_architecture.py tests/test_phase8g_pending_resolution_architecture.py tests/test_phase8h_pending_reply_architecture.py tests/test_phase8i_canonical_flag_dogfood_architecture.py tests/test_phase8j_canonical_planning_cutover_architecture.py tests/test_phase8k_canonical_default_lanes_architecture.py` ;
- full backend :
  `./scripts/test-backend -q`.
```

When implementing, append real pass/fail counts after these command lines.
Keep the command text intact so future agents can rerun the same gates.

- [x] **Step 2: Update `DECISION-RUNTIME-LEGACY-KILL-LIST.md`**

Add:

```text
Phase 8K rend canoniques par defaut les lanes non-planning :

- commands depuis Understanding default-on ;
- pending depuis Understanding default-on ;
- Understanding scoped default-on uniquement si un consumer non-planning peut
  utiliser l'artefact ;
- planning cutover toujours opt-in.
```

- [x] **Step 3: Update `BUILD-ORDER.md`**

Add:

```text
Phase 8K livree localement :
- defaults commands/pending canoniques actives ;
- scoped Understanding gate ;
- planning cutover toujours off ;
- wrapper defaults OK ;
- prochaine decision : 8L refactor `decide()` ou default-enable planning cutover.
```

- [x] **Step 4: Update `README.md`**

Add:

```text
- `superpowers/plans/2026-05-15-decision-runtime-phase-8k-canonical-default-lanes.md` — Phase 8K : default-enable controle des lanes canoniques commands/pending.
```

---

## Task 8 - Verification Gate

Run:

```bash
./scripts/test-backend -q \
  tests/test_phase8k_canonical_default_lanes_architecture.py \
  tests/test_conversation_understanding_bridge.py \
  tests/test_conversation_command_bridge.py \
  tests/test_conversation_pending_bridge.py
```

Expected:

```text
all selected tests pass
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
  tests/test_phase8j_canonical_planning_cutover_architecture.py \
  tests/test_phase8k_canonical_default_lanes_architecture.py
```

Expected:

```text
all selected architecture tests pass
```

Run:

```bash
./scripts/smoke-decision-runtime-canonical-defaults
```

Expected:

```text
RESULT: OK for the API smoke section, real conversation smokes pass
```

Run:

```bash
./scripts/smoke-decision-runtime-canonical-planning
```

Expected:

```text
RESULT: OK (9 checks)
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

8K is complete only if:

```text
1. Commands from Understanding are default-on and opt-out works.
2. Pending from Understanding is default-on and opt-out works.
3. Canonical Understanding runs by default for active pending.
4. Canonical Understanding runs by default for execution/memory-capable turns.
5. Canonical Understanding does not run by default for read-only lookups.
6. Planning cutover remains default-off.
7. 8J planning wrapper still passes.
8. No new deterministic user-text parser is added.
9. No new write path is added.
10. Docs include real verification evidence.
```

## After 8K

If 8K is green:

```text
8L should tackle one of two choices:
1. refactor `decide()` into a provider-only legacy adapter, or
2. default-enable canonical planning cutover for a narrower planning subset.
```

Recommendation:

```text
Prefer 8L = `decide()` shrink.
Reason: after commands/pending defaults, `decide()` should lose authority before
planning cutover becomes default.
```

## Implementation Result

Delivered locally on 2026-05-15:

```text
- commands from Understanding default-on, opt-out `0`
- pending from Understanding default-on, opt-out `0`
- scoped non-planning Understanding default-on, opt-out `0`
- planning cutover still default-off
- default wrapper added without exporting command/pending flags
```

Fresh verification:

```text
- targeted 8K: 33 passed
- architecture pack Phase 8: 64 passed
- smoke-decision-runtime-canonical-defaults: RESULT: OK (2 API checks)
- smoke-decision-runtime-canonical-planning: RESULT: OK (9 checks)
- full backend: 1222 passed, 11 skipped, 11 subtests passed
```
