---
summary: implementation plan for Decision Runtime Phase 8P decision_legacy support extraction
read_when:
  - implementing Decision Runtime Phase 8P
  - shrinking fitmas.llm.decision_legacy after the CoachDecision artifact boundary
  - extracting onboarding, week-plan enrichment, timeline summaries or fact memory helpers from legacy decide
  - preparing the canonical CoachUnderstanding provider pivot without changing runtime behavior
---

# Decision Runtime Phase 8P Decision Legacy Support Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** shrink `fitmas.llm.decision_legacy` by extracting non-decision support helpers while preserving public imports, monkeypatch compatibility and runtime behavior.

**Architecture:** 8P is a no-behavior-change cleanup slice. `decision_legacy.py` should become closer to a legacy CoachDecision orchestrator: provider request shims, prompt build, tool loop, schema repair, action compile and `decide()`. Onboarding copy, week-plan enrichment, timeline summaries and fact extraction move into focused legacy modules.

**Tech Stack:** Python 3.13, pytest, existing `fitmas.llm` package compatibility shim, legacy LLM provider wrappers.

---

## CTO Decision

Choose **Option A** from 8O before the canonical provider pivot.

Reason:

```text
8O made runtime consume LegacyCoachDecisionArtifact.
The next risk is not reply behavior; it is that decision_legacy.py still mixes:
- conversation decide orchestration
- onboarding coach copy
- week plan enrichment
- fact memory extraction
- timeline summary formatting
```

Do not default-enable canonical planning in 8P.
Do not change prompts.
Do not change provider behavior.
Do not run live API/LLM smokes inside the 8P wrapper.

## Files

Create:

- `backend/src/fitmas/llm/legacy_summaries.py`
  - owns `make_plan_summary`, `make_timeline_summary`, `_timeline_slot_kind`.
- `backend/src/fitmas/llm/legacy_onboarding.py`
  - owns coach voice preview, onboarding recap, week-plan enrichment and fallbacks.
- `backend/src/fitmas/llm/legacy_fact_memory.py`
  - owns fact extraction prompt, fact normalization, selected prompt facts and slugging.
- `tests/test_phase8p_decision_legacy_support_split_architecture.py`
  - static architecture gates for the split.
- `tests/test_llm_legacy_summaries.py`
  - behavior tests for summaries.
- `tests/test_llm_legacy_onboarding.py`
  - request injection and fallback tests for onboarding helpers.
- `tests/test_llm_legacy_fact_memory.py`
  - request injection, normalization and selection tests for facts.
- `scripts/smoke-decision-runtime-decision-legacy-support-split`
  - deterministic local wrapper.

Modify:

- `backend/src/fitmas/llm/decision_legacy.py`
  - delete moved function bodies.
  - keep public wrapper functions so existing imports from `fitmas.llm` still work.
  - pass `_request_json` / `_request_text` into extracted helpers to preserve test patchability.
- `docs/DECISION-RUNTIME-REFACTOR.md`
  - add Phase 8P status after implementation.
- `docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md`
  - update remaining legacy surface.
- `docs/BUILD-ORDER.md`
  - update current status and evidence.

Do not modify:

- `conversation_pipeline.py`
- `legacy/coach_decision_artifact.py`
- `legacy/conversation_*_bridge.py`
- canonical `decision/`
- canonical `domain/planning/`
- prompt files, except if a moved helper imports the same constant text unchanged.

## Invariants

```text
1. No behavior change.
2. No prompt text rewrite.
3. No free-text deterministic parsing.
4. No new write path.
5. No new runtime flag.
6. No live HTTP/LLM smoke in the 8P wrapper.
7. Existing imports from fitmas.llm remain compatible.
8. Tests that monkeypatch fitmas.llm._request_json / _request_text still work through wrappers.
9. decision_legacy.py no longer imports onboarding_contract, knowledge, fact_memory or time_context directly.
10. decision_legacy.py keeps decide(), request shims, decide-none observability and provider/tool-loop orchestration.
```

## Task 1 - Architecture Red Gates

**Files:**

- Create: `tests/test_phase8p_decision_legacy_support_split_architecture.py`

- [ ] Add static tests:

```python
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"
LLM = SRC / "llm"
SCRIPTS = ROOT / "scripts"


def _source(relative: str) -> str:
    return (SRC / relative).read_text(encoding="utf-8")


def _imports(relative: str) -> set[str]:
    tree = ast.parse(_source(relative), filename=relative)
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def test_8p_support_modules_exist() -> None:
    assert (LLM / "legacy_summaries.py").exists()
    assert (LLM / "legacy_onboarding.py").exists()
    assert (LLM / "legacy_fact_memory.py").exists()


def test_8p_decision_legacy_no_longer_imports_support_domains_directly() -> None:
    imports = _imports("llm/decision_legacy.py")
    forbidden = {
        "fitmas.fact_memory",
        "fitmas.knowledge",
        "fitmas.onboarding_contract",
        "fitmas.time_context",
    }
    assert not forbidden.intersection(imports)


def test_8p_public_compat_wrappers_remain_in_decision_legacy() -> None:
    source = _source("llm/decision_legacy.py")
    for name in (
        "def make_plan_summary(",
        "def make_timeline_summary(",
        "def preview_coach_voice(",
        "def formulate_onboarding_recap(",
        "def formulate_week_plan(",
        "def extract_facts(",
        "def select_prompt_facts(",
    ):
        assert name in source


def test_8p_decision_legacy_keeps_decide_but_not_large_support_prompts() -> None:
    source = _source("llm/decision_legacy.py")
    assert "def decide(" in source
    assert "Tu dois enrichir un squelette de semaine multisport" not in source
    assert "Analyse cet echange et decide s'il faut memoriser" not in source
    assert source.count("\n") < 760


def test_8p_smoke_wrapper_is_deterministic_only() -> None:
    source = (SCRIPTS / "smoke-decision-runtime-decision-legacy-support-split").read_text(encoding="utf-8")
    assert "tests/test_phase8p_decision_legacy_support_split_architecture.py" in source
    assert "tests/test_llm_legacy_summaries.py" in source
    assert "tests/test_llm_legacy_onboarding.py" in source
    assert "tests/test_llm_legacy_fact_memory.py" in source
    assert "smoke-decision-runtime-coachdecision-artifact" in source
    assert "smoke-a-plus-api" not in source
    assert "smoke-real-conversations" not in source
```

- [ ] Run red:

```bash
./scripts/test-backend -q tests/test_phase8p_decision_legacy_support_split_architecture.py
```

Expected: fails because modules and wrapper do not exist yet.

## Task 2 - Extract Summary Helpers

**Files:**

- Create: `backend/src/fitmas/llm/legacy_summaries.py`
- Create: `tests/test_llm_legacy_summaries.py`
- Modify: `backend/src/fitmas/llm/decision_legacy.py`

- [ ] Move unchanged logic for:

```text
make_plan_summary
make_timeline_summary
_timeline_slot_kind
```

- [ ] Keep wrappers in `decision_legacy.py`:

```python
def make_plan_summary(days: list) -> str:
    return legacy_summaries.make_plan_summary(days)


def make_timeline_summary(sessions: list) -> str:
    return legacy_summaries.make_timeline_summary(sessions)
```

- [ ] Add tests covering:

```text
- done/skipped/canceled sessions render slot=closed
- rest/recovery sessions render slot=free_flexible and movable_target=true
- active training sessions render can_swap_with_training=true
- plan summary keeps sport, title, goal, priority and flexibility
```

- [ ] Run:

```bash
./scripts/test-backend -q tests/test_llm_legacy_summaries.py tests/test_llm_prompt_builder.py
```

Expected: pass.

## Task 3 - Extract Onboarding And Week Enrichment

**Files:**

- Create: `backend/src/fitmas/llm/legacy_onboarding.py`
- Create: `tests/test_llm_legacy_onboarding.py`
- Modify: `backend/src/fitmas/llm/decision_legacy.py`

- [ ] Move unchanged logic for:

```text
_COACH_SOUL
preview_coach_voice
formulate_onboarding_recap
formulate_week_plan
_sanitize_coach_text
_merge_week_enrichment
_fallback_voice_preview
_fallback_recap
_fallback_week_plan
_fallback_day_note
_fallback_summary
```

- [ ] Do not move `_SOUL` unless no remaining code uses it.

- [ ] In the new module, accept request functions explicitly:

```python
def preview_coach_voice(
    context: dict,
    *,
    time_context: dict | None = None,
    request_json_fn: Callable[..., dict | None],
) -> list[str]:
    ...
```

Use the same pattern for:

```text
formulate_onboarding_recap -> request_text_fn
formulate_week_plan -> request_json_fn
```

- [ ] Keep wrappers in `decision_legacy.py`:

```python
def preview_coach_voice(context: dict, *, time_context: dict | None = None) -> list[str]:
    return legacy_onboarding.preview_coach_voice(
        context,
        time_context=time_context,
        request_json_fn=_request_json,
    )
```

Repeat for recap and week plan.

- [ ] Add tests proving:

```text
- request_json_fn is called for preview and week plan
- request_text_fn is called for recap
- prompt leak markers fall back to safe text
- week enrichment never changes sport_type, duration_min, intensity, load_score, priority or flexibility
- fallback week plan still returns intention, summary and 7 days
```

- [ ] Run:

```bash
./scripts/test-backend -q tests/test_llm_legacy_onboarding.py tests/test_onboarding_contract.py tests/test_onboarding_planner_flow.py
```

Expected: pass.

## Task 4 - Extract Fact Memory Helpers

**Files:**

- Create: `backend/src/fitmas/llm/legacy_fact_memory.py`
- Create: `tests/test_llm_legacy_fact_memory.py`
- Modify: `backend/src/fitmas/llm/decision_legacy.py`

- [ ] Move unchanged logic for:

```text
extract_facts
select_prompt_facts
_normalize_fact_payload
_slugify
```

- [ ] In the new module, accept request JSON explicitly:

```python
def extract_facts(
    user_text: str,
    assistant_text: str,
    existing_facts: list[dict],
    *,
    request_json_fn: Callable[..., dict | None],
) -> list[dict]:
    ...
```

- [ ] Keep wrappers in `decision_legacy.py`:

```python
def extract_facts(user_text: str, assistant_text: str, existing_facts: list[dict]) -> list[dict]:
    return legacy_fact_memory.extract_facts(
        user_text,
        assistant_text,
        existing_facts,
        request_json_fn=_request_json,
    )


def select_prompt_facts(facts: list[dict]) -> list[str]:
    return legacy_fact_memory.select_prompt_facts(facts)
```

- [ ] Add tests proving:

```text
- invalid/no facts output returns []
- fact payloads are normalized through fact_memory.normalize_fact_payload
- archive actions produce active=false
- select_prompt_facts returns a bounded relevant list
- slug fallback is stable for empty/missing keys
```

- [ ] Run:

```bash
./scripts/test-backend -q tests/test_llm_legacy_fact_memory.py tests/test_memory_mutation_service.py tests/test_llm_first_conversation_contract.py
```

Expected: pass.

## Task 5 - Clean decision_legacy Imports And Compatibility

**Files:**

- Modify: `backend/src/fitmas/llm/decision_legacy.py`
- Modify if needed: `tests/test_llm_package_compat.py`

- [ ] Remove direct imports no longer needed from `decision_legacy.py`:

```text
json
re
unicodedata
fitmas.coach_voice
fitmas.fact_memory
fitmas.knowledge
fitmas.onboarding_contract
fitmas.time_context
```

- [ ] Import the new modules:

```python
from fitmas.llm import legacy_fact_memory, legacy_onboarding, legacy_summaries
```

- [ ] Keep old public symbols available through `fitmas.llm`, because `fitmas.llm.__init__` still aliases to `decision_legacy`.

- [ ] Run:

```bash
./scripts/test-backend -q tests/test_llm_package_compat.py tests/test_llm_json.py tests/test_llm_legacy_provider.py tests/test_llm_legacy_tool_loop.py
```

Expected: pass.

## Task 6 - Smoke Wrapper And Docs

**Files:**

- Create: `scripts/smoke-decision-runtime-decision-legacy-support-split`
- Modify: `docs/DECISION-RUNTIME-REFACTOR.md`
- Modify: `docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md`
- Modify: `docs/BUILD-ORDER.md`

- [ ] Add wrapper:

```bash
#!/usr/bin/env bash
set -euo pipefail

./scripts/test-backend -q \
  tests/test_phase8p_decision_legacy_support_split_architecture.py \
  tests/test_llm_legacy_summaries.py \
  tests/test_llm_legacy_onboarding.py \
  tests/test_llm_legacy_fact_memory.py \
  tests/test_llm_package_compat.py

./scripts/smoke-decision-runtime-coachdecision-artifact

echo "RESULT: OK"
```

- [ ] Make it executable:

```bash
chmod +x scripts/smoke-decision-runtime-decision-legacy-support-split
```

- [ ] Update docs with:

```text
Phase 8P delivered locally:
- decision_legacy.py no longer owns onboarding/week/fact support bodies
- public fitmas.llm imports preserved
- no behavior change
- 8P wrapper deterministic-only
```

## Verification

Run these in order:

```bash
./scripts/test-backend -q tests/test_phase8p_decision_legacy_support_split_architecture.py
./scripts/test-backend -q tests/test_llm_legacy_summaries.py tests/test_llm_legacy_onboarding.py tests/test_llm_legacy_fact_memory.py
./scripts/smoke-decision-runtime-decision-legacy-support-split
./scripts/test-backend -q tests/test_decision_runtime_architecture.py tests/test_phase8a_legacy_audit.py tests/test_phase8b_cutover_architecture.py tests/test_phase8c_legacy_kill_architecture.py tests/test_phase8d_bridge_shrink_architecture.py tests/test_phase8e_understanding_cutover_architecture.py tests/test_phase8f_command_extraction_architecture.py tests/test_phase8g_pending_resolution_architecture.py tests/test_phase8h_pending_reply_architecture.py tests/test_phase8i_canonical_flag_dogfood_architecture.py tests/test_phase8j_canonical_planning_cutover_architecture.py tests/test_phase8k_canonical_default_lanes_architecture.py tests/test_phase8l_decide_authority_architecture.py tests/test_phase8m_decision_legacy_split_architecture.py tests/test_phase8n_provider_tool_loop_architecture.py tests/test_phase8o_coachdecision_artifact_architecture.py tests/test_phase8p_decision_legacy_support_split_architecture.py
./scripts/test-backend
```

Do not claim completion if any command fails.

## Acceptance Criteria

```text
decision_legacy.py still exports the same public helper names.
conversation runtime behavior is unchanged.
onboarding API behavior is unchanged.
fact extraction behavior is unchanged.
timeline prompt summaries are unchanged.
decision_legacy.py line count is materially lower than 8O.
decision_legacy.py no longer imports support-domain modules directly.
8P wrapper is deterministic-only.
full backend test suite passes.
```

## What 8P Enables Next

After 8P, `decision_legacy.py` should be narrow enough for a real 8Q pivot:

```text
8Q candidate:
Canonical provider pivot for non-planning lanes.

Goal:
provider returns CoachUnderstanding first for non-planning lanes;
LegacyCoachDecisionArtifact remains fallback and planning compatibility.
```

Only consider 8Q after 8P passes deterministic gates and one explicit real dogfood smoke outside the wrapper.

## Implementation Evidence - 2026-05-17

Delivered:

```text
legacy_summaries.py owns plan/timeline summaries.
legacy_onboarding.py owns coach preview, onboarding recap and week-plan enrichment.
legacy_fact_memory.py owns fact extraction, normalization and selected prompt facts.
decision_legacy.py keeps public compatibility wrappers and request injection.
decision_legacy.py no longer imports fact_memory, knowledge, onboarding_contract or time_context directly.
decision_legacy.py line count: 556.
8P wrapper is deterministic-only and delegates only to the deterministic 8O wrapper.
```

Verification:

```bash
./scripts/test-backend -q tests/test_phase8p_decision_legacy_support_split_architecture.py
# 5 passed

./scripts/test-backend -q tests/test_llm_legacy_summaries.py tests/test_llm_legacy_onboarding.py tests/test_llm_legacy_fact_memory.py
# 14 passed

./scripts/test-backend -q tests/test_llm_package_compat.py tests/test_llm_json.py tests/test_llm_legacy_provider.py tests/test_llm_legacy_tool_loop.py tests/test_llm_legacy_summaries.py tests/test_llm_legacy_onboarding.py tests/test_llm_legacy_fact_memory.py
# 28 passed

./scripts/smoke-decision-runtime-decision-legacy-support-split
# 21 passed
# nested 8O wrapper: 52 passed + 118 passed
# RESULT: OK

./scripts/test-backend -q tests/test_decision_runtime_architecture.py tests/test_phase8a_legacy_audit.py tests/test_phase8b_cutover_architecture.py tests/test_phase8c_legacy_kill_architecture.py tests/test_phase8d_bridge_shrink_architecture.py tests/test_phase8e_understanding_cutover_architecture.py tests/test_phase8f_command_extraction_architecture.py tests/test_phase8g_pending_resolution_architecture.py tests/test_phase8h_pending_reply_architecture.py tests/test_phase8i_canonical_flag_dogfood_architecture.py tests/test_phase8j_canonical_planning_cutover_architecture.py tests/test_phase8k_canonical_default_lanes_architecture.py tests/test_phase8l_decide_authority_architecture.py tests/test_phase8m_decision_legacy_split_architecture.py tests/test_phase8n_provider_tool_loop_architecture.py tests/test_phase8o_coachdecision_artifact_architecture.py tests/test_phase8p_decision_legacy_support_split_architecture.py
# 98 passed

./scripts/test-backend
# 1300 passed, 11 skipped
```
