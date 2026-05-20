---
summary: Phase 9U plan for physically shrinking the legacy Decision Runtime surface after zero-fallback dogfood census
read_when:
  - continuing Decision Runtime legacy cleanup after Phase 9T
  - removing fitmas.llm package alias or CoachDecision provider authority
  - deciding whether the refactor made the runtime smaller or only better organized
---

# Decision Runtime Phase 9U Legacy Runtime Shrink Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the runtime physically smaller by removing implicit legacy LLM authority, not by adding another compatibility layer.

**Architecture:** The canonical runtime remains the only product path: Understanding builds typed intent, planning/pending/readonly bridges decide, CommandServices write, ReplyComposer speaks. Legacy CoachDecision becomes explicit opt-in compatibility, never a silent fallback behind `fitmas.llm` package aliasing.

**Tech Stack:** Python, FastAPI, SQLAlchemy, Pydantic, pytest, existing `./scripts/test-backend` and smoke census scripts.

---

## Current Baseline

Measured before this plan:

- `backend/src/fitmas/conversation_pipeline.py`: 1928 lines.
- `backend/src/fitmas/legacy/`: 6015 lines.
- `backend/src/fitmas/llm/decision_legacy.py`: 565 lines.
- `backend/src/fitmas/llm/legacy_*.py` plus `decision_legacy.py`: 3419 lines.
- `backend/src/fitmas/llm/__init__.py` still aliases the package to `decision_legacy` via `sys.modules[__name__] = _decision_legacy`.
- Strict core + daily + extended smoke after 9Q/9R/9S: 62 scenarios, 0 fallback scenarios, 0 fallback turns.
- 9T reply-quality slice is implemented locally but not yet committed in the current workspace.

Hard precondition:

- Do not start deletion on a dirty baseline. Commit the current 9S/9T state first, or explicitly choose a stacked branch with a clean diff checkpoint.

## Non-Negotiables

- No deterministic parsing of free user text.
- No new prompt examples copied from smoke tests.
- No new broad prompt to compensate for runtime uncertainty.
- No new fallback in `conversation_pipeline.py`.
- No direct user-visible text outside `ReplyComposer` or an existing composer bridge.
- No write path outside CommandServices.
- No deletion without an import graph test.
- No "all legacy delete" in one pass. Delete by proven owner.

## File Map

Primary files:

- Modify: `backend/src/fitmas/llm/__init__.py`
  - Replace package aliasing with explicit, temporary compatibility exports.
- Modify: `backend/src/fitmas/legacy/decision_contracts.py`
  - Become the source for legacy CoachDecision/Pending/Mutation action models.
- Modify: `backend/src/fitmas/llm/legacy_models.py`
  - Re-export from `legacy/decision_contracts.py`; remove it in Phase 9V once no source callers remain.
- Modify: `backend/src/fitmas/legacy/coach_decision_provider.py`
  - Remove default dependency on broad `fitmas.llm`.
- Modify: `backend/src/fitmas/app/api/routes_messages.py`
  - Stop importing helper functions from broad `fitmas.llm`.
- Modify: `backend/src/fitmas/api_onboarding.py`
  - Import onboarding helpers from explicit legacy helper module.
- Modify: `backend/src/fitmas/adaptation.py`
  - Stop importing `_request_json` from broad `fitmas.llm`.
- Modify only if needed: `backend/src/fitmas/conversation_pipeline.py`
  - Make legacy CoachDecision provider default-off or explicitly opt-in.
- Create: `tests/test_phase9u_legacy_runtime_shrink_architecture.py`
  - Import graph and default-off gates.
- Update: `docs/DECISION-RUNTIME-REFACTOR.md`
- Update: `docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md`
- Update: `docs/BUILD-ORDER.md`

Secondary callers likely needing explicit imports:

- `backend/src/fitmas/memory_mutation_service.py`
- `backend/src/fitmas/execution_mutation_service.py`
- tests importing `from fitmas.llm import CoachDecision`, `MutationDecision`, or action models.

## Phase 9U-A: Freeze Baseline And Add Import Graph Tests

**Files:**

- Create: `tests/test_phase9u_legacy_runtime_shrink_architecture.py`
- No source behavior changes.

- [ ] **Step 1: Verify the baseline is clean enough to cut**

Run:

```bash
git status --short
```

Expected before implementation:

```text
no unrelated unstaged work, or an intentional committed 9S/9T checkpoint
```

If dirty:

```bash
./scripts/test-backend -q tests/test_coach_voice.py tests/test_final_reply.py tests/test_legacy_final_reply_backend.py tests/test_decision_reply_composer.py tests/test_conversation_readonly_reply_bridge.py tests/test_phase9s_legacy_provider_shrink_architecture.py
./scripts/smoke-decision-runtime-extended-census
git diff --check
```

Expected:

```text
reply and provider gates pass
strict extended census reports fallback_scenario_count=0
git diff --check has no output
```

- [ ] **Step 2: Write failing architecture tests**

Add this file:

```python
# tests/test_phase9u_legacy_runtime_shrink_architecture.py
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"


def _source(relative: str) -> str:
    return (SRC / relative).read_text()


def _python_files(*roots: str) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        files.extend((ROOT / root).rglob("*.py"))
    return sorted(files)


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(SRC))
    except ValueError:
        return str(path.relative_to(ROOT))


def test_9u_llm_package_no_longer_aliases_to_decision_legacy() -> None:
    source = _source("llm/__init__.py")
    assert "sys.modules[__name__]" not in source
    assert "_decision_legacy.__path__" not in source


def test_9u_runtime_modules_do_not_import_broad_fitmas_llm() -> None:
    allowed = {
        "llm/decision_legacy.py",
        "llm/legacy_tool_loop.py",
        "llm/legacy_provider.py",
        "llm/legacy_schema_repair.py",
        "llm/legacy_onboarding.py",
        "llm/legacy_fact_memory.py",
        "llm/legacy_summaries.py",
    }
    offenders: list[str] = []
    for path in _python_files("backend/src/fitmas"):
        relative = _relative(path)
        if relative in allowed or relative.startswith("llm/prompts/"):
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "fitmas.llm":
                offenders.append(f"{relative}:{node.lineno}")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "fitmas.llm":
                        offenders.append(f"{relative}:{node.lineno}")
    assert offenders == []


def test_9u_legacy_decision_contracts_do_not_import_fitmas_llm() -> None:
    source = _source("legacy/decision_contracts.py")
    assert "from fitmas.llm import" not in source
    assert "import fitmas.llm" not in source


def test_9u_legacy_provider_has_no_default_broad_llm_runtime_import() -> None:
    source = _source("legacy/coach_decision_provider.py")
    assert "from fitmas import llm" not in source
    assert "llm_runtime" not in source
```

- [ ] **Step 3: Run tests and confirm red**

Run:

```bash
./scripts/test-backend -q tests/test_phase9u_legacy_runtime_shrink_architecture.py
```

Expected:

```text
FAIL
```

Expected first failures:

- `llm/__init__.py` still uses `sys.modules[__name__]`.
- runtime files still import broad `fitmas.llm`.
- `legacy/decision_contracts.py` still imports from `fitmas.llm`.
- `legacy/coach_decision_provider.py` still imports `fitmas.llm`.

## Phase 9U-B: Move Legacy Contracts Out Of `fitmas.llm`

**Files:**

- Modify: `backend/src/fitmas/legacy/decision_contracts.py`
- Modify: `backend/src/fitmas/llm/legacy_models.py`
- Modify direct model callers found by the failing architecture test.

- [ ] **Step 1: Make `legacy/decision_contracts.py` own the Pydantic models**

Move the model definitions currently in `backend/src/fitmas/llm/legacy_models.py` into `backend/src/fitmas/legacy/decision_contracts.py`.

The file must define and export:

```python
MutationDecision
HealthSignalAction
AvailabilityConstraintAction
PreferenceSignalAction
ExecutionUpdateAction
AcceptPendingResolution
RejectPendingResolution
ModifyPendingResolution
IgnorePendingResolution
NeedsClarificationPendingResolution
MemoryAction
PendingResolution
CoachDecision
```

Do not import `fitmas.llm` in this file.

- [ ] **Step 2: Turn `llm/legacy_models.py` into a temporary re-export**

Replace its body with:

```python
from __future__ import annotations

from fitmas.legacy.decision_contracts import (
    AcceptPendingResolution,
    AvailabilityConstraintAction,
    CoachDecision,
    ExecutionUpdateAction,
    HealthSignalAction,
    IgnorePendingResolution,
    MemoryAction,
    ModifyPendingResolution,
    MutationDecision,
    NeedsClarificationPendingResolution,
    PendingResolution,
    PreferenceSignalAction,
    RejectPendingResolution,
)

__all__ = [
    "AcceptPendingResolution",
    "AvailabilityConstraintAction",
    "CoachDecision",
    "ExecutionUpdateAction",
    "HealthSignalAction",
    "IgnorePendingResolution",
    "MemoryAction",
    "ModifyPendingResolution",
    "MutationDecision",
    "NeedsClarificationPendingResolution",
    "PendingResolution",
    "PreferenceSignalAction",
    "RejectPendingResolution",
]
```

This keeps old tests alive while making `legacy/decision_contracts.py` the actual owner.

- [ ] **Step 3: Update source callers to explicit legacy contracts**

Change runtime imports like:

```python
from fitmas.llm import ExecutionUpdateAction
```

to:

```python
from fitmas.legacy.decision_contracts import ExecutionUpdateAction
```

Expected source files:

- `backend/src/fitmas/execution_mutation_service.py`
- `backend/src/fitmas/memory_mutation_service.py`
- `backend/src/fitmas/legacy/coach_understanding_adapter.py`
- `backend/src/fitmas/legacy/conversation_command_bridge.py`
- `backend/src/fitmas/legacy/coach_command_adapter.py`

- [ ] **Step 4: Run targeted model tests**

Run:

```bash
./scripts/test-backend -q tests/test_memory_mutation_service.py tests/test_plan_mutation_service.py tests/test_mutations.py tests/test_coach_command_adapter.py tests/test_coach_understanding_adapter.py tests/test_conversation_command_bridge.py tests/test_phase9u_legacy_runtime_shrink_architecture.py
```

Expected:

```text
model callers pass except broad fitmas.llm tests that are intentionally not migrated yet
```

## Phase 9U-C: Replace Broad `fitmas.llm` Runtime Helper Imports

**Files:**

- Modify: `backend/src/fitmas/app/api/routes_messages.py`
- Modify: `backend/src/fitmas/api_onboarding.py`
- Modify: `backend/src/fitmas/adaptation.py`
- Modify tests that monkeypatch the old broad package path.

- [ ] **Step 1: Move route message helper imports to explicit modules**

Replace:

```python
from fitmas.llm import decide, extract_facts, make_timeline_summary, select_prompt_facts
```

with:

```python
from fitmas.llm.decision_legacy import decide
from fitmas.llm.legacy_fact_memory import extract_facts, select_prompt_facts
from fitmas.llm.legacy_summaries import make_timeline_summary
```

This is still legacy where needed, but no longer hidden behind the package alias.

- [ ] **Step 2: Move onboarding helper imports to explicit modules**

Replace:

```python
from fitmas.llm import formulate_onboarding_recap, formulate_week_plan, preview_coach_voice
```

with:

```python
from fitmas.llm.legacy_onboarding import (
    formulate_onboarding_recap,
    formulate_week_plan,
    preview_coach_voice,
)
```

If the helper requires `request_json_fn`, pass `fitmas.llm.decision_legacy._request_json` explicitly for now. Do not import broad `fitmas.llm`.

- [ ] **Step 3: Stop importing `_request_json` from broad `fitmas.llm`**

In `backend/src/fitmas/adaptation.py`, replace:

```python
from fitmas.llm import _request_json
```

with:

```python
from fitmas.llm.decision_legacy import _request_json
```

This is not the final architecture, but it makes the dependency explicit and searchable.

- [ ] **Step 4: Run route/helper tests**

Run:

```bash
./scripts/test-backend -q tests/test_core_flows.py tests/test_integration_real.py tests/test_llm_prompt_builder.py tests/test_llm_legacy_fact_memory.py tests/test_llm_legacy_onboarding.py tests/test_llm_legacy_summaries.py tests/test_phase9u_legacy_runtime_shrink_architecture.py
```

Expected:

```text
tests pass or fail only on test monkeypatch paths that still import broad fitmas.llm
```

## Phase 9U-D: Remove The `fitmas.llm` Package Alias

**Files:**

- Modify: `backend/src/fitmas/llm/__init__.py`
- Modify: `tests/test_llm_package_compat.py`

- [ ] **Step 1: Replace package aliasing with explicit temporary exports**

Replace `backend/src/fitmas/llm/__init__.py` with a normal package initializer:

```python
from __future__ import annotations

from fitmas.legacy.decision_contracts import (
    AcceptPendingResolution,
    AvailabilityConstraintAction,
    CoachDecision,
    ExecutionUpdateAction,
    HealthSignalAction,
    IgnorePendingResolution,
    MemoryAction,
    ModifyPendingResolution,
    MutationDecision,
    NeedsClarificationPendingResolution,
    PendingResolution,
    PreferenceSignalAction,
    RejectPendingResolution,
)
from fitmas.llm.decision_legacy import (
    clear_last_decide_none,
    decide,
    get_last_decide_none,
    parse_coach_decision_payload,
)

__all__ = [
    "AcceptPendingResolution",
    "AvailabilityConstraintAction",
    "CoachDecision",
    "ExecutionUpdateAction",
    "HealthSignalAction",
    "IgnorePendingResolution",
    "MemoryAction",
    "ModifyPendingResolution",
    "MutationDecision",
    "NeedsClarificationPendingResolution",
    "PendingResolution",
    "PreferenceSignalAction",
    "RejectPendingResolution",
    "clear_last_decide_none",
    "decide",
    "get_last_decide_none",
    "parse_coach_decision_payload",
]
```

This keeps old imports working but removes the dangerous package identity swap.

- [ ] **Step 2: Update compatibility test expectations**

In `tests/test_llm_package_compat.py`, assert:

```python
def test_llm_package_is_normal_package() -> None:
    import fitmas.llm as llm

    assert llm.__name__ == "fitmas.llm"
    assert hasattr(llm, "CoachDecision")
    assert hasattr(llm, "decide")
```

Keep the existing checks that `from fitmas.llm import CoachDecision, decide, parse_coach_decision_payload` works for now.

- [ ] **Step 3: Run package compatibility tests**

Run:

```bash
./scripts/test-backend -q tests/test_llm_package_compat.py tests/test_phase9u_legacy_runtime_shrink_architecture.py
```

Expected:

```text
PASS
```

## Phase 9U-E: Make Legacy CoachDecision Provider Default-Off In Conversation Runtime

**Files:**

- Modify: `backend/src/fitmas/legacy/conversation_decide_bridge.py`
- Modify: `backend/src/fitmas/conversation_pipeline.py`
- Modify: `tests/test_conversation_decide_bridge.py`
- Modify: `tests/test_phase9s_legacy_provider_shrink_architecture.py`
- Extend: `tests/test_phase9u_legacy_runtime_shrink_architecture.py`

- [ ] **Step 1: Add a machine-only provider flag**

In `legacy/conversation_decide_bridge.py`, add:

```python
import os


def legacy_provider_enabled() -> bool:
    return os.getenv("FITMAS_ENABLE_LEGACY_COACH_DECISION_PROVIDER") == "1"
```

Then make `legacy_provider_skip_reason()` return `"legacy_provider_disabled"` when:

- no canonical path has explicitly allowed a measured fallback;
- `legacy_provider_enabled()` is false.

Do not inspect `user_text`.

- [ ] **Step 2: Keep opt-in compatibility for tests and ops**

Where existing tests expect `run_legacy_coach_decision()` to execute, pass through the bridge function directly or set:

```bash
FITMAS_ENABLE_LEGACY_COACH_DECISION_PROVIDER=1
```

Do not set this in dogfood smoke wrappers.

- [ ] **Step 3: Add architecture test for default-off**

Add to `tests/test_phase9u_legacy_runtime_shrink_architecture.py`:

```python
def test_9u_legacy_provider_env_flag_is_default_off() -> None:
    source = _source("legacy/conversation_decide_bridge.py")
    assert "FITMAS_ENABLE_LEGACY_COACH_DECISION_PROVIDER" in source
    assert "os.getenv(\"FITMAS_ENABLE_LEGACY_COACH_DECISION_PROVIDER\") == \"1\"" in source
```

- [ ] **Step 4: Run targeted provider tests**

Run:

```bash
./scripts/test-backend -q tests/test_conversation_decide_bridge.py tests/test_phase9s_legacy_provider_shrink_architecture.py tests/test_phase9u_legacy_runtime_shrink_architecture.py
```

Expected:

```text
PASS
```

## Phase 9U-F: Prove Dogfood Still Has Zero Fallback Without Legacy Provider

**Files:**

- No source changes unless tests expose a real regression.

- [ ] **Step 1: Run strict census**

Run:

```bash
./scripts/smoke-decision-runtime-extended-census
```

Expected:

```text
scenario_count=62
fallback_scenario_count=0
fallback_turn_count=0
```

- [ ] **Step 2: Run no-env check**

Run:

```bash
env | rg "FITMAS_ENABLE_LEGACY_COACH_DECISION_PROVIDER|FITMAS_CANONICAL|FITMAS_UNDERSTANDING" || true
```

Expected:

```text
No legacy provider enable flag is required for the strict smoke to pass.
```

- [ ] **Step 3: Run full backend**

Run:

```bash
./scripts/test-backend
```

Expected:

```text
all backend tests pass
```

## Phase 9U-G: Delete Or Shorten Now-Dead Compatibility Wrappers

**Files:**

- Modify: `backend/src/fitmas/llm/decision_legacy.py`
- Modify tests importing helpers from `fitmas.llm` when they can import explicit modules.

- [ ] **Step 1: Find remaining broad compatibility callers**

Run:

```bash
rg -n "from fitmas import llm|import fitmas\\.llm|from fitmas\\.llm import|llm\\." backend/src/fitmas tests scripts
```

Expected remaining source callers:

- `backend/src/fitmas/llm/*` internal package imports.
- `backend/src/fitmas/legacy/*` compatibility tests or bridges only.
- tests that explicitly verify compatibility.

- [ ] **Step 2: Remove public helper wrappers from `decision_legacy.py` when callers are gone**

Candidates to delete from `decision_legacy.py` after explicit caller migration:

```python
make_timeline_summary
preview_coach_voice
formulate_onboarding_recap
formulate_week_plan
extract_facts
select_prompt_facts
```

The replacement imports already exist:

```python
from fitmas.llm.legacy_summaries import make_timeline_summary
from fitmas.llm.legacy_onboarding import preview_coach_voice, formulate_onboarding_recap, formulate_week_plan
from fitmas.llm.legacy_fact_memory import extract_facts, select_prompt_facts
```

- [ ] **Step 3: Keep only provider/parser compatibility in `decision_legacy.py`**

After deletion, `decision_legacy.py` should still expose:

```python
decide
parse_coach_decision_payload
clear_last_decide_none
get_last_decide_none
_request_json
_request_message
_request_text
```

Everything else should live in explicit modules.

- [ ] **Step 4: Add line-count architecture test**

Add to `tests/test_phase9u_legacy_runtime_shrink_architecture.py`:

```python
def test_9u_decision_legacy_stays_under_provider_compat_budget() -> None:
    line_count = len(_source("llm/decision_legacy.py").splitlines())
    assert line_count <= 430
```

Start with `<= 430` only if the implementation actually gets there. If the safe cut lands higher, set the threshold to the measured new value and document why. Do not set it above the current 565 unless no shrink happened.

- [ ] **Step 5: Run targeted helper tests**

Run:

```bash
./scripts/test-backend -q tests/test_llm_package_compat.py tests/test_llm_legacy_fact_memory.py tests/test_llm_legacy_onboarding.py tests/test_llm_legacy_summaries.py tests/test_phase9u_legacy_runtime_shrink_architecture.py
```

Expected:

```text
PASS
```

## Phase 9U-H: Update Docs And Kill List

**Files:**

- Modify: `docs/DECISION-RUNTIME-REFACTOR.md`
- Modify: `docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md`
- Modify: `docs/BUILD-ORDER.md`

- [ ] **Step 1: Add Phase 9U status**

Add:

```markdown
## Statut Phase 9U

Legacy runtime shrink:

- `fitmas.llm` is no longer an alias to `llm/decision_legacy.py`;
- legacy CoachDecision contracts now live under `legacy/decision_contracts.py`;
- source runtime imports no longer use broad `from fitmas.llm import ...`;
- legacy CoachDecision provider is default-off in conversation runtime unless explicitly enabled for ops/tests;
- strict core + daily + extended census still reports 0 fallback turns;
- `decision_legacy.py` is reduced to provider/parser compatibility only.

Lecture:

- reliability was already improved by zero-fallback census;
- 9U is the first real physical shrink of the old runtime authority;
- if unsupported real turns now clarify instead of calling `CoachDecision`, that is intentional and safer for dogfood.
```

- [ ] **Step 2: Update kill list owner status**

Mark:

- `fitmas.llm` package alias: killed.
- broad runtime imports from `fitmas.llm`: killed for source runtime.
- `LegacyCoachDecisionProvider` conversation default: disabled.
- `decision_legacy.py`: still present, provider/parser compat only.
- `legacy/` folder: not fully deletable yet.

- [ ] **Step 3: Record before/after counts**

Run:

```bash
wc -l backend/src/fitmas/conversation_pipeline.py backend/src/fitmas/llm/decision_legacy.py backend/src/fitmas/llm/__init__.py
find backend/src/fitmas/legacy -maxdepth 1 -type f -name '*.py' -print | sort | xargs wc -l
find backend/src/fitmas/llm -maxdepth 1 -type f \\( -name 'legacy_*.py' -o -name 'decision_legacy.py' -o -name '__init__.py' \\) -print | sort | xargs wc -l
```

Document the delta honestly. If `conversation_pipeline.py` barely shrinks, say so.

## Phase 9U-I: Final Verification

- [ ] **Step 1: Architecture gates**

Run:

```bash
./scripts/test-backend -q tests/test_phase9u_legacy_runtime_shrink_architecture.py tests/test_phase9s_legacy_provider_shrink_architecture.py tests/test_phase8p_decision_legacy_support_split_architecture.py tests/test_phase8n_provider_tool_loop_architecture.py tests/test_phase8m_decision_legacy_split_architecture.py
```

Expected:

```text
PASS
```

- [ ] **Step 2: Full backend**

Run:

```bash
./scripts/test-backend
```

Expected:

```text
PASS
```

- [ ] **Step 3: Real smoke census**

Run:

```bash
./scripts/smoke-decision-runtime-extended-census
```

Expected:

```text
scenario_count=62
fallback_scenario_count=0
fallback_turn_count=0
```

- [ ] **Step 4: Diff hygiene**

Run:

```bash
git diff --check
```

Expected:

```text
no output
```

## Acceptance Criteria

9U is done only when all are true:

- `backend/src/fitmas/llm/__init__.py` no longer aliases the package to `decision_legacy`.
- Source runtime files do not import broad `fitmas.llm`.
- Legacy contracts are owned by `backend/src/fitmas/legacy/decision_contracts.py`.
- `LegacyCoachDecisionProvider` does not default to broad `fitmas.llm`.
- Conversation runtime does not call the legacy provider by default.
- Strict core + daily + extended census remains 0 fallback.
- `decision_legacy.py` is smaller and limited to provider/parser compatibility.
- Docs record before/after line counts and remaining legacy.

## What Remains After 9U

Still legacy, but now contained:

- `backend/src/fitmas/legacy/conversation_canonical_planning_bridge.py`
  - large bridge, still active canonical adapter.
- `backend/src/fitmas/legacy/conversation_pending_bridge.py`
  - pending adapter, still active.
- `backend/src/fitmas/legacy/conversation_command_bridge.py`
  - active command bridge until command services are wired more directly.
- `backend/src/fitmas/legacy/final_reply_backend.py`
  - old composer backend for some reply lanes.
- `backend/src/fitmas/llm/decision_legacy.py`
  - provider/parser compat only after 9U.
- `backend/src/fitmas/llm/legacy_*`
  - explicit legacy helper modules, no longer package identity.

Next likely slice after 9U:

- Phase 9V: delete or move the default-off `LegacyCoachDecisionProvider` path after one more zero-fallback extended census.
- Phase 9W: shrink `conversation_pipeline.py` by moving the canonical planning/pending/read-only bridge orchestration into `decision/runtime.py` or a small `conversation_adapter.py`.
- Phase 9X: replace `legacy/final_reply_backend.py` with direct `decision/reply_composer.py` handlers where the outcome already has enough evidence.

## Verdict Gate For Thursday

Use this cold rule:

```text
If 9U removes hidden legacy authority but the line counts barely move, the refactor made FitMAS safer but not yet smaller.
If 9U also removes the package alias, broad runtime imports, default legacy provider authority, and at least 20% of decision_legacy.py, then the runtime is genuinely shrinking.
```

Do not judge by file organization. Judge by:

- fewer active decision paths;
- fewer implicit imports;
- fewer compatibility shims;
- fewer places allowed to speak or write;
- zero fallback on real smoke census.
