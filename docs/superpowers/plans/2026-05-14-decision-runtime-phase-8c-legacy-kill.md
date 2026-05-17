---
summary: implementation plan for Decision Runtime Phase 8C legacy runtime removal
read_when:
  - implementing Decision Runtime Phase 8C
  - deleting active MutationDecision, final_reply, heartbeat, tools or WeeklyPlan legacy routes
  - making runtime cutovers default behavior
  - preparing the repo for the target architecture
---

# Decision Runtime Phase 8C Legacy Kill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove active legacy runtime authority route by route, after Phase 8B proved planning and heartbeat parity under flags.

**Architecture:** 8C is destructive but not broad cleanup. Each cut removes one active legacy decision route, adds an architecture test that would fail before the cut, and preserves a narrow `legacy/` bridge only when needed for compatibility. The target remains: `InputEvent -> CoachContext -> Understanding -> DecisionEngine -> CommandBus -> DecisionOutcome -> ReplyComposer`.

**Tech Stack:** Python 3.13, pytest static architecture tests, existing smoke wrappers, FitMAS Decision Runtime packages, existing SQLAlchemy repository until domain repositories fully replace legacy reads.

---

## CTO Decision

Do not execute all 8C at once.

Recommended order:

```text
8C1 conversation planning legacy kill
8C2 conversation reply legacy isolation
8C3 heartbeat runtime default path
8C4 tools registry legacy removal
8C5 WeeklyPlan / DayPlan runtime isolation
8C6 MutationDecision module archive
```

Reason:

```text
Planning and reply are still coupled through conversation_pipeline.py.
Heartbeat is mostly bridged already.
Tools and WeeklyPlan/DayPlan touch broader tests and should not be mixed with conversation cuts.
MutationDecision physical archive only becomes safe after all runtime importers are gone.
```

## Non-Negotiables

```text
1. No deletion without a failing architecture test first.
2. No deterministic parser over free user text.
3. No new prompt rule to compensate for backend boundaries.
4. No new local reply string outside ReplyComposer or legacy reply bridge.
5. No write outside CommandService or the explicitly documented legacy writer bridge being retired.
6. Keep dogfood rollback scoped to legacy/ adapters only while executing a slice.
7. Run `./scripts/smoke-decision-runtime-cutover` after every slice that changes conversation, heartbeat or planning behavior.
8. Update `DECISION-RUNTIME-LEGACY-KILL-LIST.md` after every successful slice.
```

## Current Evidence From 8B

```text
flag-on unit gate -> 30 passed
./scripts/smoke-decision-runtime-cutover -> exit 0
./scripts/test-backend -q -> 1111 passed, 11 skipped, 11 subtests passed
```

8C may start from this evidence, but each cut needs fresh verification.

## File Map

Create:

```text
tests/test_phase8c_legacy_kill_architecture.py
backend/src/fitmas/legacy/conversation_reply_adapter.py
backend/src/fitmas/legacy/tools_compat.py
backend/src/fitmas/legacy/weekly_plan_compat.py
```

Modify:

```text
backend/src/fitmas/conversation_pipeline.py
backend/src/fitmas/legacy/planning_runtime_adapter.py
backend/src/fitmas/legacy/final_reply_backend.py
backend/src/fitmas/app/telegram/scheduler.py
backend/src/fitmas/telegram_commands.py
backend/src/fitmas/api_debug.py
backend/src/fitmas/api_ops.py
backend/src/fitmas/tools/registry.py
backend/src/fitmas/plan_mutation_service.py
backend/src/fitmas/api_read.py
backend/src/fitmas/repository.py
tests/test_phase8a_legacy_audit.py
tests/test_phase8b_cutover_harness.py
docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md
docs/DECISION-RUNTIME-REFACTOR.md
docs/BUILD-ORDER.md
```

Allowed to keep until final archive:

```text
backend/src/fitmas/llm/decision_legacy.py
backend/src/fitmas/legacy/coach_understanding_adapter.py
backend/src/fitmas/legacy/final_reply_backend.py
backend/src/fitmas/legacy/heartbeat_runtime_adapter.py
```

Forbidden as active runtime after 8C:

```text
conversation_pipeline.py importing MutationDecision
conversation_pipeline.py importing final_reply directly
conversation_pipeline.py calling apply_patch_for_user from CoachDecision PlanPatch branches
conversation_pipeline.py converting CoachDecision -> MutationDecision
scheduler/manual/debug/ops calling heartbeat factories without runtime adapter
tools registry offering propose_replan or draft_* by default
plan_mutation_service.py reading WeeklyPlan/DayPlan for runtime mutations
```

## Task 1 — Add 8C Architecture Tests

**Files:**

- Create: `tests/test_phase8c_legacy_kill_architecture.py`

- [ ] **Step 1: Write failing architecture tests**

Create `tests/test_phase8c_legacy_kill_architecture.py`:

```python
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"


def _source(relative: str) -> str:
    return (SRC / relative).read_text(encoding="utf-8")


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_8c1_conversation_has_no_active_mutationdecision_planning_routes() -> None:
    source = _source("conversation_pipeline.py")
    forbidden = {
        "from fitmas.llm import MutationDecision",
        "MutationDecision(",
        'response_type == "mutation_decision"',
        'response_type == "requires_confirmation"',
        'response_type == "plan_patch"',
        "_should_try_legacy_plan_adaptation_after_decide",
        "_apply_matching_legacy_pending_acceptance",
        "apply_decisions_for_user",
    }

    assert sorted(token for token in forbidden if token in source) == []


def test_8c2_only_legacy_modules_import_final_reply() -> None:
    offenders: list[str] = []
    allowed = {
        SRC / "final_reply.py",
        SRC / "legacy" / "final_reply_backend.py",
        SRC / "legacy" / "conversation_reply_adapter.py",
        SRC / "skills" / "heartbeat" / "reply_context.py",
        SRC / "skills" / "heartbeat" / "heartbeat.py",
    }
    for path in sorted(SRC.rglob("*.py")):
        if path in allowed:
            continue
        imports = _imports(path)
        if "fitmas.final_reply" in imports or any(
            node in imports for node in {"fitmas.final_reply", "fitmas"}
        ) and "final_reply" in path.read_text(encoding="utf-8"):
            offenders.append(str(path.relative_to(SRC)))

    assert offenders == []


def test_8c3_telegram_heartbeat_defaults_to_runtime_adapter() -> None:
    source = _source("app/telegram/scheduler.py")

    assert "heartbeat_runtime_cutover_enabled()" not in source
    assert "run_heartbeat_trigger" in source
    assert "_heartbeat_draft_factory" in source


def test_8c4_tools_registry_does_not_offer_legacy_mutation_tools_by_default() -> None:
    source = _source("tools/registry.py")
    forbidden = {
        'name="propose_replan"',
        'name="draft_move_session"',
        'name="draft_swap_sessions"',
        'name="draft_replace_session"',
        'name="draft_lighten_day"',
        'name="draft_create_session"',
    }

    assert sorted(token for token in forbidden if token in source) == []


def test_8c5_runtime_files_do_not_read_weeklyplan_dayplan() -> None:
    checked = {
        "conversation_pipeline.py",
        "plan_mutation_service.py",
        "decision/context_builder.py",
        "domain/planning/mutation_service.py",
        "api_read.py",
    }
    forbidden = {
        "get_active_plan(",
        "get_active_plan_optional(",
        "get_day_plan(",
        "to_pydantic_plan(",
        "WeeklyPlan",
        "DayPlan",
    }
    offenders: list[str] = []
    for relative in checked:
        source = _source(relative)
        offenders.extend(f"{relative}: {token}" for token in forbidden if token in source)

    assert offenders == []
```

- [ ] **Step 2: Run and verify red**

Run:

```bash
./scripts/test-backend -q tests/test_phase8c_legacy_kill_architecture.py
```

Expected:

```text
At least 8C1, 8C2, 8C3, 8C4 and 8C5 fail on current code.
```

## Task 2 — 8C1 Conversation Planning Legacy Kill

**Files:**

- Modify: `backend/src/fitmas/conversation_pipeline.py`
- Modify: `backend/src/fitmas/legacy/planning_runtime_adapter.py`
- Modify: `tests/test_phase8b_planning_cutover.py`
- Modify: `tests/test_phase8c_legacy_kill_architecture.py`

- [ ] **Step 1: Split 8C1 tests so only planning assertions run**

During implementation, run only:

```bash
./scripts/test-backend -q tests/test_phase8c_legacy_kill_architecture.py::test_8c1_conversation_has_no_active_mutationdecision_planning_routes
```

Expected before code:

```text
FAIL listing current MutationDecision / response_type branches.
```

- [ ] **Step 2: Make planning runtime the default route**

In `backend/src/fitmas/conversation_pipeline.py`, replace:

```python
def _planning_runtime_cutover_enabled() -> bool:
    return str(os.getenv("FITMAS_PLANNING_RUNTIME_CUTOVER") or "").strip() == "1"
```

with:

```python
def _planning_runtime_cutover_enabled() -> bool:
    return str(os.getenv("FITMAS_PLANNING_RUNTIME_CUTOVER") or "").strip() not in {"0", "false", "False", "off"}
```

This keeps a temporary emergency kill switch while making runtime the normal route.

- [ ] **Step 3: Remove active CoachDecision PlanPatch branches**

Delete these branches from `conversation_pipeline.py`:

```text
decision.response_type == "mutation_decision"
decision.response_type == "requires_confirmation" and decision.plan_patch is not None
decision.response_type == "plan_patch" and decision.plan_patch is not None
```

Do not replace them with local fallback text. Applicable planning artifacts must
already be handled by `_maybe_handle_planning_runtime_cutover`; if not, they
become `planning_runtime_unhandled`.

- [ ] **Step 4: Remove legacy pending acceptance fallthrough**

Delete the call site that assigns the old pending fallback:

```python
legacy_pending_outcome = _apply_matching_legacy_pending_acceptance(
    db=db,
    user=user,
    decision=decision,
    pending_confirmation=pending_confirmation,
)
```

Then delete the helper if no tests import it:

```python
def _apply_matching_legacy_pending_acceptance(
    *,
    db: Session,
    user,
    decision,
    pending_confirmation,
) -> ConversationTurnOutcome | None:
    pass
```

Structured `pending_resolution` stays. Only the old matching fallback goes.

- [ ] **Step 5: Remove legacy post-decide adaptation fallback**

Delete the call site:

```python
_should_try_legacy_plan_adaptation_after_decide(
    decision=decision,
    turn_plan=turn_plan,
    pending_confirmation=pending_confirmation,
)
```

Then delete:

```python
def _should_try_legacy_plan_adaptation_after_decide(*, decision: Any, turn_plan, pending_confirmation) -> bool:
    return False
```

The mixed CoachDecision branch may remain only until 8C2 if it no longer creates
planning mutations outside the runtime. If it still writes, remove it in this
task.

- [ ] **Step 6: Stop importing MutationDecision into conversation_pipeline**

Remove:

```python
from fitmas.llm import MutationDecision
```

For the no-change fallback, replace:

```python
legacy_no_change = MutationDecision(
    mutation_type="no_change",
    rationale=decision.rationale,
    fitmas_message=reply_text,
)
decision=legacy_no_change
```

with:

```python
decision=None
```

The visible reply and response mode are enough. Do not keep a fake mutation
object just for telemetry.

- [ ] **Step 7: Run 8C1 tests**

Run:

```bash
./scripts/test-backend -q \
  tests/test_phase8c_legacy_kill_architecture.py::test_8c1_conversation_has_no_active_mutationdecision_planning_routes \
  tests/test_phase8b_planning_cutover.py \
  tests/test_conversation_planning_runtime_adapter.py \
  tests/test_conversation_planning_runtime_reply_composer.py
```

Expected:

```text
all passed
```

- [ ] **Step 8: Run real cutover harness**

Run:

```bash
./scripts/smoke-decision-runtime-cutover
```

Expected:

```text
exit 0
```

If it fails, classify with the 8B mapping. Do not restore legacy fallthrough.

## Task 3 — 8C2 Conversation Reply Legacy Isolation

**Files:**

- Create: `backend/src/fitmas/legacy/conversation_reply_adapter.py`
- Modify: `backend/src/fitmas/conversation_pipeline.py`
- Modify: `tests/test_phase8c_legacy_kill_architecture.py`
- Modify tests that patch `conversation_pipeline.final_reply.*`

- [ ] **Step 1: Run 8C2 test red**

Run:

```bash
./scripts/test-backend -q tests/test_phase8c_legacy_kill_architecture.py::test_8c2_only_legacy_modules_import_final_reply
```

Expected:

```text
FAIL because conversation_pipeline.py imports final_reply directly.
```

- [ ] **Step 2: Create the legacy reply adapter**

Create `backend/src/fitmas/legacy/conversation_reply_adapter.py`:

```python
from __future__ import annotations

from fitmas import final_reply


FinalReplyContext = final_reply.FinalReplyContext
BlockedEvent = final_reply.BlockedEvent

compose_close_turn_reply = final_reply.compose_close_turn_reply
close_turn_outage_fallback_reply = final_reply.close_turn_outage_fallback_reply
compose_final_reply = final_reply.compose_final_reply
compose_plan_lookup_reply = final_reply.compose_plan_lookup_reply
compose_execution_report_reply = final_reply.compose_execution_report_reply
compose_no_change_reply = final_reply.compose_no_change_reply
compose_plan_adaptation_reply = final_reply.compose_plan_adaptation_reply
outage_fallback_reply = final_reply.outage_fallback_reply
build_plan_adaptation_reply_context = final_reply.build_plan_adaptation_reply_context
verify_factual_reply = final_reply.verify_factual_reply
verify_uncommitted_reply = final_reply.verify_uncommitted_reply
verify_post_event_reply = final_reply.verify_post_event_reply
request_text = final_reply.request_text
```

This is still legacy, but the import is now isolated under `legacy/`.

- [ ] **Step 3: Replace conversation import**

In `conversation_pipeline.py`, replace:

```python
from fitmas import final_reply, llm as llm_runtime, repository as repo
```

with:

```python
from fitmas import llm as llm_runtime, repository as repo
from fitmas.legacy import conversation_reply_adapter as final_reply
```

- [ ] **Step 4: Update tests that patch the old path**

Search:

```bash
rg -n "conversation_pipeline\\.final_reply|fitmas\\.conversation_pipeline\\.final_reply" tests
```

Replace patches with:

```text
fitmas.legacy.conversation_reply_adapter.<function>
```

Do not weaken assertions.

- [ ] **Step 5: Run 8C2 tests**

Run:

```bash
./scripts/test-backend -q \
  tests/test_phase8c_legacy_kill_architecture.py::test_8c2_only_legacy_modules_import_final_reply \
  tests/test_core_flows.py \
  tests/test_blocked_mutation_reply.py \
  tests/test_conversation_debug_endpoint.py
```

Expected:

```text
all passed
```

## Task 4 — 8C3 Heartbeat Runtime Default Path

**Files:**

- Modify: `backend/src/fitmas/app/telegram/scheduler.py`
- Modify: `backend/src/fitmas/telegram_commands.py`
- Modify: `backend/src/fitmas/api_debug.py`
- Modify: `backend/src/fitmas/api_ops.py`
- Modify: `tests/test_telegram_scheduler_runtime_adapter.py`
- Modify: `tests/test_telegram_commands.py`
- Modify: `tests/test_heartbeat_debug_endpoint.py`
- Modify: `tests/test_phase8b_heartbeat_cutover.py`

- [ ] **Step 1: Run 8C3 test red**

Run:

```bash
./scripts/test-backend -q tests/test_phase8c_legacy_kill_architecture.py::test_8c3_telegram_heartbeat_defaults_to_runtime_adapter
```

Expected:

```text
FAIL because scheduler still checks heartbeat_runtime_cutover_enabled().
```

- [ ] **Step 2: Make scheduler use runtime adapter by default**

In `backend/src/fitmas/app/telegram/scheduler.py`, delete:

```python
def _heartbeat_runtime_cutover_enabled() -> bool:
    from fitmas.legacy import heartbeat_runtime_adapter as adapter

    return adapter.heartbeat_runtime_cutover_enabled()
```

Change `_heartbeat_draft_factory` so it always calls
`adapter.run_heartbeat_trigger` with the same arguments Phase 8B already tested.

Keep only an emergency opt-out if needed:

```python
if str(os.getenv("FITMAS_HEARTBEAT_RUNTIME_CUTOVER") or "").strip().lower() in {"0", "false", "off"}:
    return legacy_factory
```

If the architecture test forbids this string, update the test to allow the
temporary opt-out only inside `app/telegram/scheduler.py` and document it in the
kill list. Remove the opt-out in 8D after dogfood.

- [ ] **Step 3: Route manual/debug/ops through adapter by default**

Update:

```text
backend/src/fitmas/telegram_commands.py
backend/src/fitmas/api_debug.py
backend/src/fitmas/api_ops.py
```

Use `run_heartbeat_endpoint(kind, legacy_factory, user_id=user.id, delivery_channel="debug")`
or the matching `"ops"` channel without checking the old cutover flag first.

- [ ] **Step 4: Update tests**

Change tests named like:

```text
test_heartbeat_draft_factory_uses_legacy_factory_when_cutover_off
```

to assert runtime default behavior instead.

- [ ] **Step 5: Verify heartbeat**

Run:

```bash
./scripts/test-backend -q \
  tests/test_heartbeat_runtime_adapter.py \
  tests/test_telegram_scheduler_runtime_adapter.py \
  tests/test_phase8b_heartbeat_cutover.py \
  tests/test_telegram_commands.py \
  tests/test_heartbeat_debug_endpoint.py \
  tests/test_phase8c_legacy_kill_architecture.py::test_8c3_telegram_heartbeat_defaults_to_runtime_adapter
```

Expected:

```text
all passed
```

## Task 5 — 8C4 Remove Legacy Planning Tools From Default Registry

**Files:**

- Create: `backend/src/fitmas/legacy/tools_compat.py`
- Modify: `backend/src/fitmas/tools/registry.py`
- Modify: `tests/test_tool_runtime.py`
- Modify: `tests/test_llm_tools.py`
- Modify: `tests/test_phase8c_legacy_kill_architecture.py`

- [ ] **Step 1: Run 8C4 test red**

Run:

```bash
./scripts/test-backend -q tests/test_phase8c_legacy_kill_architecture.py::test_8c4_tools_registry_does_not_offer_legacy_mutation_tools_by_default
```

Expected:

```text
FAIL because tools/registry.py still defines propose_replan and draft_* tools.
```

- [ ] **Step 2: Move legacy tool descriptors**

Create `backend/src/fitmas/legacy/tools_compat.py` and move the descriptors for:

```text
propose_replan
draft_move_session
draft_swap_sessions
draft_replace_session
draft_lighten_day
draft_create_session
```

Keep handlers reusable from existing modules. Do not delete `plan_patch_tools.py`
yet; it becomes legacy implementation detail.

- [ ] **Step 3: Remove from default registry**

In `tools/registry.py`, remove default registration of those tools.

Default registry should still expose:

```text
read tools
validate_plan_patch
validate_week_coherence if still needed by reviewer paths
suggest_replan_candidates only if it remains read-only/candidate and not a write authority
```

If `suggest_replan_candidates` remains, document it as candidate-only.

- [ ] **Step 4: Add optional legacy registry only for tests/debug**

Expose:

```python
from collections.abc import Sequence


def legacy_planning_tool_specs() -> Sequence[ToolSpec]:
    return (
        _legacy_draft_move_session_spec(),
        _legacy_draft_swap_sessions_spec(),
        _legacy_draft_replace_session_spec(),
        _legacy_draft_lighten_day_spec(),
        _legacy_draft_create_session_spec(),
        _legacy_propose_replan_spec(),
    )
```

Only tests or debug endpoints may import it.

- [ ] **Step 5: Update tests**

Update `tests/test_tool_runtime.py`:

```text
default registry does not include propose_replan or draft_*
legacy_planning_tool_specs includes them for compatibility tests
```

- [ ] **Step 6: Verify tools**

Run:

```bash
./scripts/test-backend -q \
  tests/test_tool_runtime.py \
  tests/test_llm_tools.py \
  tests/test_phase8c_legacy_kill_architecture.py::test_8c4_tools_registry_does_not_offer_legacy_mutation_tools_by_default
```

Expected:

```text
all passed
```

## Task 6 — 8C5 Isolate WeeklyPlan / DayPlan Runtime Reads

**Files:**

- Create: `backend/src/fitmas/legacy/weekly_plan_compat.py`
- Modify: `backend/src/fitmas/plan_mutation_service.py`
- Modify: `backend/src/fitmas/api_read.py`
- Modify: `backend/src/fitmas/repository.py`
- Modify: `tests/test_plan_mutation_service.py`
- Modify: `tests/test_app_endpoints.py`
- Modify: `tests/test_phase8c_legacy_kill_architecture.py`

- [ ] **Step 1: Run 8C5 test red**

Run:

```bash
./scripts/test-backend -q tests/test_phase8c_legacy_kill_architecture.py::test_8c5_runtime_files_do_not_read_weeklyplan_dayplan
```

Expected:

```text
FAIL because plan_mutation_service.py and api_read.py still touch WeeklyPlan/DayPlan helpers.
```

- [ ] **Step 2: Create weekly plan compat module**

Create `backend/src/fitmas/legacy/weekly_plan_compat.py`:

```python
from __future__ import annotations

from fitmas import repository as repo


get_active_plan_optional = repo.get_active_plan_optional
get_active_plan = repo.get_active_plan
get_day_plan = repo.get_day_plan
to_pydantic_plan = repo.to_pydantic_plan
replace_plan = repo.replace_plan
```

This does not solve runtime truth; it isolates remaining template/archive usage.

- [ ] **Step 3: Remove WeeklyPlan reads from PlanMutationService**

In `plan_mutation_service.py`, replace uses of:

```python
repo.get_active_plan_optional(db, user.id)
```

with scheduled-session-only logic.

If a plan id is only used for compatibility metadata, use:

```python
plan_id = None
```

Do not query `WeeklyPlan` from mutation runtime.

- [ ] **Step 4: Update API read model**

In `api_read.py`, keep the response schema if the frontend still expects
`WeeklyPlan`, but build it from `ScheduledSession` rows only.

Do not fallback to:

```python
repo.to_pydantic_plan(plan)
```

If no sessions exist, return an empty runtime week with status metadata, not a
legacy `DayPlan` projection.

- [ ] **Step 5: Move onboarding/template usage**

Update onboarding imports to use:

```python
from fitmas.legacy import weekly_plan_compat
```

Only onboarding/regenerate may call `replace_plan`.

- [ ] **Step 6: Verify runtime truth**

Run:

```bash
./scripts/test-backend -q \
  tests/test_plan_mutation_service.py \
  tests/test_app_endpoints.py \
  tests/test_decision_context_builder.py \
  tests/test_phase8c_legacy_kill_architecture.py::test_8c5_runtime_files_do_not_read_weeklyplan_dayplan
```

Expected:

```text
all passed
```

## Task 7 — 8C6 Archive MutationDecision Runtime Support

**Files:**

- Modify: `backend/src/fitmas/adaptation.py`
- Modify: `backend/src/fitmas/mutations.py`
- Modify: `backend/src/fitmas/mutation_hooks.py`
- Modify: `backend/src/fitmas/mutation_permissions.py`
- Modify: `backend/src/fitmas/plan_patch.py`
- Modify: `backend/src/fitmas/plan_mutation_service.py`
- Modify: `backend/src/fitmas/legacy/coach_understanding_adapter.py`
- Modify: `tests/test_phase8a_legacy_audit.py`
- Modify: `docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md`

- [ ] **Step 1: Add stricter audit test**

In `tests/test_phase8a_legacy_audit.py`, change the import audit:

```python
allowed_importers = {
    "legacy/coach_understanding_adapter.py",
    "llm/decision_legacy.py",
}
```

Assert all other importers of `CoachDecision` / `MutationDecision` are gone.

- [ ] **Step 2: Run and verify red**

Run:

```bash
./scripts/test-backend -q tests/test_phase8a_legacy_audit.py::test_phase8a_doc_lists_all_legacy_llm_contract_importers
```

Expected:

```text
FAIL listing current runtime importers.
```

- [ ] **Step 3: Move remaining runtime users behind legacy modules**

For each file still importing `MutationDecision`, either:

```text
delete the runtime path
or move it under legacy/
or rewrite it to RequestedPlanChange / PlanPatch internal backend types
```

Do not keep a runtime import just to satisfy old tests.

- [ ] **Step 4: Update tests to target new runtime types**

Tests that construct `MutationDecision` should either:

```text
move to legacy-specific tests
or build RequestedPlanChange / PlanPatch / PlanningDecisionResult
```

- [ ] **Step 5: Verify import audit**

Run:

```bash
./scripts/test-backend -q \
  tests/test_phase8a_legacy_audit.py \
  tests/test_phase8c_legacy_kill_architecture.py
```

Expected:

```text
all passed
```

## Task 8 — Final 8C Verification

**Files:**

- No code edits unless verification exposes a bug.

- [ ] **Step 1: Run targeted architecture gates**

Run:

```bash
./scripts/test-backend -q \
  tests/test_decision_runtime_architecture.py \
  tests/test_phase8a_legacy_audit.py \
  tests/test_phase8b_cutover_architecture.py \
  tests/test_phase8c_legacy_kill_architecture.py
```

Expected:

```text
all passed
```

- [ ] **Step 2: Run cutover harness**

Run:

```bash
./scripts/smoke-decision-runtime-cutover
```

Expected:

```text
exit 0
```

- [ ] **Step 3: Run full backend**

Run:

```bash
./scripts/test-backend -q
```

Expected:

```text
all tests pass
```

## Task 9 — Update Docs

**Files:**

- Modify: `docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md`
- Modify: `docs/DECISION-RUNTIME-REFACTOR.md`
- Modify: `docs/BUILD-ORDER.md`
- Modify: `docs/README.md` only if new canon docs are added

- [ ] **Step 1: Mark each 8C slice with evidence**

In `DECISION-RUNTIME-LEGACY-KILL-LIST.md`, add:

```text
Phase 8C result:
- 8C1 conversation planning legacy route removed
- 8C2 final_reply direct conversation import removed
- 8C3 heartbeat runtime adapter is default active path
- 8C4 propose_replan/draft_* removed from default registry
- 8C5 WeeklyPlan/DayPlan isolated from runtime reads
- 8C6 MutationDecision runtime importers archived
```

Only include completed bullets. Do not mark unfinished slices as done.

- [ ] **Step 2: Update Build Order**

Record exact command evidence:

```text
./scripts/smoke-decision-runtime-cutover -> exit 0
./scripts/test-backend -q -> N passed, M skipped
```

- [ ] **Step 3: Update refactor canon**

In `DECISION-RUNTIME-REFACTOR.md`, add a Phase 8C implementation block with:

```text
what was removed
what remains legacy
which tests enforce it
```

## Acceptance Criteria

8C is complete only when:

```text
1. conversation_pipeline.py no longer imports MutationDecision.
2. conversation_pipeline.py no longer owns direct CoachDecision PlanPatch commit/pending branches.
3. conversation_pipeline.py no longer imports fitmas.final_reply directly.
4. scheduler/manual/debug/ops heartbeat use runtime adapter by default.
5. tools registry no longer offers propose_replan or draft_* by default.
6. runtime mutation/read paths no longer read WeeklyPlan/DayPlan.
7. MutationDecision runtime importers are gone or isolated under legacy/.
8. smoke-decision-runtime-cutover exits 0.
9. full backend tests pass.
```

## 8C Execution Recommendation

Run 8C as separate implementation turns:

```text
Turn 1: 8C1 only
Turn 2: 8C2 only
Turn 3: 8C3 only
Turn 4: 8C4 only
Turn 5: 8C5 only
Turn 6: 8C6 + docs
```

The highest-risk slices are:

```text
8C1 conversation planning
8C5 WeeklyPlan/DayPlan runtime isolation
8C6 MutationDecision archive
```

Do not combine those three in one coding turn.
