---
summary: implementation plan for Decision Runtime Phase 8N legacy provider and tool-loop extraction
read_when:
  - implementing Decision Runtime Phase 8N
  - extracting provider or tool-loop logic from fitmas.llm.decision_legacy
  - preserving fitmas.llm monkeypatch compatibility while shrinking CoachDecision legacy
---

# Decision Runtime Phase 8N Provider Tool-Loop Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Extract provider requests, schema repair and tool-loop orchestration out of `backend/src/fitmas/llm/decision_legacy.py` without changing runtime behavior.

**Architecture:** 8N is a large shrink slice, not the moment to delete `CoachDecision` or default-enable canonical planning. `decision_legacy.py` should remain the compatibility facade and high-level legacy `decide()` orchestrator; provider calls, schema repair and tool loop mechanics move into focused `fitmas.llm.legacy_*` modules with explicit dependency injection so existing `fitmas.llm._request_*`, `fitmas.llm.execute_tool_calls` and `fitmas.llm.log_tool_trace` monkeypatch tests keep working.

**Tech Stack:** Python, pytest, existing FitMAS LLM gateway, existing `fitmas.tools` runtime, existing Decision Runtime Phase 8 architecture tests.

---

## Non-Negotiables

```text
1. No visible coach behavior change.
2. No default-enable of canonical planning cutover.
3. No new deterministic parsing of free user text.
4. No new write path.
5. Public `fitmas.llm` compatibility remains intact.
6. Existing monkeypatches on `fitmas.llm._request_message`, `_request_json`,
   `_request_structured_json`, `_request_json_with_tools`,
   `execute_tool_calls` and `log_tool_trace` keep working.
7. New modules must not import `fitmas.conversation_pipeline`.
8. New modules must not import app/API layers.
9. Tool-loop modules may execute tools through injected dependencies only.
10. `decision_legacy.py` may keep small compatibility shims, but not own
    provider/tool-loop/schema-repair implementation bodies.
```

## Target Shape

Create:

- `backend/src/fitmas/llm/legacy_provider.py`
  Owns low-level provider request wrappers around `fitmas.llm.gateway`.
- `backend/src/fitmas/llm/legacy_schema_repair.py`
  Owns invalid payload repair, Claude schema fallback, prose-to-json repair,
  provider markup guards and tool result summaries.
- `backend/src/fitmas/llm/legacy_tool_loop.py`
  Owns tool-use round trips, tool-result follow-up messages, tool compiler,
  retry JSON formatting and tool trace assembly.
- `tests/test_phase8n_provider_tool_loop_architecture.py`
  Static boundaries and compatibility guards.
- `tests/test_llm_legacy_provider.py`
  Direct provider wrapper tests.
- `tests/test_llm_legacy_schema_repair.py`
  Direct schema repair tests.
- `tests/test_llm_legacy_tool_loop.py`
  Direct tool-loop tests with injected fakes.
- `scripts/smoke-decision-runtime-provider-tool-loop`
  Local wrapper for 8N gates plus 8M/8L regression gates.

Modify:

- `backend/src/fitmas/llm/decision_legacy.py`
  Convert provider/tool-loop/schema-repair bodies into compatibility shims and
  high-level orchestration calls.
- `docs/DECISION-RUNTIME-REFACTOR.md`
- `docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md`
- `docs/BUILD-ORDER.md`
- `docs/README.md`
- This plan file after implementation with evidence.

## Current Hotspot To Extract

As of 8M, `decision_legacy.py` still owns these responsibilities:

```text
provider requests:
- _client
- _request_text
- _request_message
- _request_json
- _request_structured_json
- _use_deepseek_openai_structured_output
- _classify_llm_exception
- _deepseek_tool_thinking_kwargs

schema repair:
- _repair_invalid_decision_payload
- _request_claude_decision_fallback
- _repair_decision_json_from_text
- _repair_tool_result_summary
- _looks_like_provider_tool_markup

tool loop:
- _request_json_with_tools
- _compile_tool_decision_json
- _retry_tool_followup_json_format
- _tool_result_blocks
- _tool_followup_content
- _tool_execution_names
- _any_tool_called
- _all_executed_tools_ok
- _all_tool_results_ok
- _sum_tool_latency
- _tool_errors
- _sum_optional_ints
- _tool_use_blocks
- _log_tool_session_trace
```

8N extracts those without changing the `decide()` contract.

## Task 1 - Architecture Gates Red

**Files:**

- Create: `tests/test_phase8n_provider_tool_loop_architecture.py`

- [x] Add a test that asserts the three new modules exist:

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_8n_modules_exist() -> None:
    for relative in (
        "backend/src/fitmas/llm/legacy_provider.py",
        "backend/src/fitmas/llm/legacy_schema_repair.py",
        "backend/src/fitmas/llm/legacy_tool_loop.py",
    ):
        assert (ROOT / relative).exists(), relative
```

- [x] Add AST helpers and assert `decision_legacy.py` imports the new modules.
- [x] Assert `decision_legacy.py` no longer defines large implementation bodies:

```python
EXTRACTED_FUNCTIONS = {
    "_compile_tool_decision_json",
    "_retry_tool_followup_json_format",
    "_tool_result_blocks",
    "_tool_followup_content",
    "_tool_execution_names",
    "_any_tool_called",
    "_all_executed_tools_ok",
    "_all_tool_results_ok",
    "_sum_tool_latency",
    "_tool_errors",
    "_sum_optional_ints",
    "_tool_use_blocks",
    "_log_tool_session_trace",
}
```

- [x] Allow small compatibility shims for:

```text
_request_json_with_tools
_repair_invalid_decision_payload
_request_claude_decision_fallback
_repair_decision_json_from_text
```

Reason: tests and existing callers monkeypatch those names on `fitmas.llm`.

- [x] Assert the compatibility shims contain no long prompt literals by checking
  no string constant in those shim functions exceeds 500 characters.
- [x] Assert none of the new modules imports `fitmas.conversation_pipeline`.
- [x] Assert none of the new modules imports `fitmas.api`, `fitmas.api_messages`
  or `fitmas.skills.heartbeat`.
- [x] Assert planning cutover remains default-off.
- [x] Run the architecture test and verify it fails before implementation:

```bash
./scripts/test-backend -q tests/test_phase8n_provider_tool_loop_architecture.py
```

Expected first failure: missing modules.

## Task 2 - Extract Legacy Provider

**Files:**

- Create: `backend/src/fitmas/llm/legacy_provider.py`
- Modify: `backend/src/fitmas/llm/decision_legacy.py`
- Test: `tests/test_llm_legacy_provider.py`

- [x] Create `legacy_provider.py` with provider-only helpers:

```python
from __future__ import annotations

import os
from typing import Any

from fitmas.llm import gateway as gw


def client():
    return gw.client()


def use_deepseek_openai_structured_output() -> bool:
    raw = os.getenv("FITMAS_USE_DEEPSEEK_OPENAI_STRUCTURED")
    if raw is None:
        return True
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def deepseek_tool_thinking_kwargs() -> dict[str, dict[str, str]]:
    if not os.getenv("DEEPSEEK_API_KEY"):
        return {}
    raw_enabled = str(os.getenv("FITMAS_DEEPSEEK_TOOL_THINKING") or "").strip().lower()
    if raw_enabled not in {"1", "true", "yes", "on", "enabled"}:
        return {}
    effort = str(os.getenv("FITMAS_DEEPSEEK_TOOL_THINKING_EFFORT") or "high").strip().lower()
    if effort not in {"high", "max"}:
        effort = "high"
    return {
        "thinking": {"type": "enabled"},
        "output_config": {"effort": effort},
    }


def classify_llm_exception(exc: BaseException) -> str:
    return gw.classify_llm_exception(exc)
```

- [x] Move low-level `request_message`, `request_text`, `request_json` and
  `request_structured_json` into this module.
- [x] Keep `decision_legacy.py` shims named `_client`, `_request_message`,
  `_request_text`, `_request_json`, `_request_structured_json`.
- [x] Important compatibility rule: `decision_legacy._request_structured_json`
  must still detect monkeypatches of `gw.request_structured_json`,
  `decision_legacy._request_json` and `decision_legacy._request_message`.
  Pass the current functions into `legacy_provider.request_structured_json`
  instead of letting the provider module close over stale globals.
- [x] Add direct provider tests:

```python
def test_legacy_provider_deepseek_structured_default_enabled(monkeypatch):
    monkeypatch.delenv("FITMAS_USE_DEEPSEEK_OPENAI_STRUCTURED", raising=False)
    assert legacy_provider.use_deepseek_openai_structured_output() is True


def test_legacy_provider_deepseek_structured_can_disable(monkeypatch):
    monkeypatch.setenv("FITMAS_USE_DEEPSEEK_OPENAI_STRUCTURED", "false")
    assert legacy_provider.use_deepseek_openai_structured_output() is False
```

- [x] Run:

```bash
./scripts/test-backend -q tests/test_llm_legacy_provider.py tests/test_llm_package_compat.py tests/test_llm_json.py
```

Expected: pass.

## Task 3 - Extract Schema Repair

**Files:**

- Create: `backend/src/fitmas/llm/legacy_schema_repair.py`
- Modify: `backend/src/fitmas/llm/decision_legacy.py`
- Test: `tests/test_llm_legacy_schema_repair.py`

- [x] Move these bodies into `legacy_schema_repair.py`:

```text
repair_invalid_decision_payload
request_claude_decision_fallback
repair_decision_json_from_text
repair_tool_result_summary
looks_like_provider_tool_markup
```

- [x] All request calls must be injected:

```python
def repair_invalid_decision_payload(
    *,
    data: dict[str, Any] | None,
    system: str,
    prompt: str,
    request_structured_json_fn: Callable[..., dict | None],
    downgrade_free_confirmation_fn: Callable[[dict | None], dict | None],
) -> dict | None:
    ...
```

- [x] `request_claude_decision_fallback` must receive `gateway_request_structured_json_fn`
  and `downgrade_free_confirmation_fn`.
- [x] `repair_decision_json_from_text` must receive `request_structured_json_fn`
  and `downgrade_free_confirmation_fn`.
- [x] `decision_legacy.py` keeps small shims:

```python
def _repair_invalid_decision_payload(...):
    return legacy_schema_repair.repair_invalid_decision_payload(
        ...,
        request_structured_json_fn=_request_structured_json,
        downgrade_free_confirmation_fn=_downgrade_free_confirmation_payload,
    )
```

- [x] Add direct tests that prove:

```text
- repair_invalid_decision_payload downgrades requires_confirmation without patch
- repair_decision_json_from_text downgrades free confirmation without patch
- provider tool markup refuses prose repair
- repair_tool_result_summary includes payload, not only summary
```

- [x] Run:

```bash
./scripts/test-backend -q tests/test_llm_legacy_schema_repair.py tests/test_llm_tools.py -k "repair_decision_json_from_text or repair_invalid_decision_payload or tool_repair_context"
```

Expected: pass.

## Task 4 - Extract Legacy Tool Loop

**Files:**

- Create: `backend/src/fitmas/llm/legacy_tool_loop.py`
- Modify: `backend/src/fitmas/llm/decision_legacy.py`
- Test: `tests/test_llm_legacy_tool_loop.py`

- [x] Create a dependency object so tool-loop behavior remains testable:

```python
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class LegacyToolLoopDependencies:
    request_message_fn: Callable[..., Any | None]
    request_structured_json_fn: Callable[..., dict | None]
    execute_tool_calls_fn: Callable[..., list[Any]]
    log_tool_trace_fn: Callable[..., None]
    tool_thinking_kwargs_fn: Callable[[], dict[str, Any]]
```

- [x] Move `request_json_with_tools` into `legacy_tool_loop.py` with this
  dependency object.
- [x] Move helper functions into `legacy_tool_loop.py`:

```text
compile_tool_decision_json
retry_tool_followup_json_format
tool_result_blocks
tool_followup_content
tool_execution_names
any_tool_called
all_executed_tools_ok
all_tool_results_ok
sum_tool_latency
tool_errors
sum_optional_ints
tool_use_blocks
log_tool_session_trace
```

- [x] Keep `decision_legacy._request_json_with_tools` as a small compatibility
  shim that calls `legacy_tool_loop.request_json_with_tools` with current
  dependencies:

```python
def _request_json_with_tools(...):
    return legacy_tool_loop.request_json_with_tools(
        ...,
        dependencies=legacy_tool_loop.LegacyToolLoopDependencies(
            request_message_fn=_request_message,
            request_structured_json_fn=_request_structured_json,
            execute_tool_calls_fn=execute_tool_calls,
            log_tool_trace_fn=log_tool_trace,
            tool_thinking_kwargs_fn=_deepseek_tool_thinking_kwargs,
        ),
    )
```

- [x] `decide()` must keep calling `decision_legacy._request_json_with_tools`.
  This preserves tests that monkeypatch that private name.
- [x] Add direct tool-loop tests:

```text
- single tool round trip returns JSON
- tool phase prose is compiled before direct parse
- compiler failure falls back to tool phase JSON
- every tool_use block gets a tool_result block
- no tool use still logs offered/not requested
- exhausted/failed follow-up logs fallback
```

- [x] Run:

```bash
./scripts/test-backend -q tests/test_llm_legacy_tool_loop.py tests/test_llm_tools.py -k "tool"
```

Expected: pass.

## Task 5 - Shrink Imports And Re-Exports

**Files:**

- Modify: `backend/src/fitmas/llm/decision_legacy.py`
- Test: `tests/test_phase8n_provider_tool_loop_architecture.py`

- [x] Remove direct imports from `decision_legacy.py` that should now live only
  in `legacy_tool_loop.py`:

```text
ToolCall
count_budgeted_tool_executions
list_tools_for_pipeline
build_tool_trace
```

- [x] Keep these names exported from `decision_legacy.py` if tests still
  monkeypatch them:

```text
execute_tool_calls
log_tool_trace
```

- [x] Remove direct long prompt bodies for schema/tool repair from
  `decision_legacy.py`.
- [x] Run:

```bash
./scripts/test-backend -q tests/test_phase8n_provider_tool_loop_architecture.py
```

Expected: pass.

## Task 6 - Decide Regression Gates

**Files:**

- Modify only if a regression reveals a real boundary issue.

- [x] Run the prompt observability tests that monkeypatch `_request_json_with_tools`:

```bash
./scripts/test-backend -q tests/test_prompt_observability.py
```

- [x] Run the package compatibility tests:

```bash
./scripts/test-backend -q tests/test_llm_package_compat.py
```

- [x] Run the existing decision/tool tests:

```bash
./scripts/test-backend -q tests/test_llm_tools.py tests/test_decide_error_typing.py tests/test_coach_decision_actions.py
```

- [x] Run the Phase 8 architecture pack:

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
  tests/test_phase8k_canonical_default_lanes_architecture.py \
  tests/test_phase8l_decide_authority_architecture.py \
  tests/test_phase8m_decision_legacy_split_architecture.py \
  tests/test_phase8n_provider_tool_loop_architecture.py
```

Expected: pass.

## Task 7 - Smoke Wrapper

**Files:**

- Create: `scripts/smoke-decision-runtime-provider-tool-loop`

- [x] Add wrapper:

```bash
#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

./scripts/test-backend -q \
  tests/test_phase8n_provider_tool_loop_architecture.py \
  tests/test_llm_legacy_provider.py \
  tests/test_llm_legacy_schema_repair.py \
  tests/test_llm_legacy_tool_loop.py \
  tests/test_llm_package_compat.py \
  tests/test_prompt_observability.py \
  tests/test_llm_tools.py \
  tests/test_decide_error_typing.py \
  tests/test_coach_decision_actions.py

./scripts/smoke-decision-runtime-decision-legacy-split

echo "RESULT: OK"
```

- [x] Make executable:

```bash
chmod +x scripts/smoke-decision-runtime-provider-tool-loop
```

- [x] Run:

```bash
./scripts/smoke-decision-runtime-provider-tool-loop
```

Expected: `RESULT: OK`.

## Task 8 - Docs And Final Verification

**Files:**

- Modify: `docs/DECISION-RUNTIME-REFACTOR.md`
- Modify: `docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md`
- Modify: `docs/BUILD-ORDER.md`
- Modify: `docs/README.md`
- Modify: this plan file

- [x] Document delivered modules, boundaries and test evidence.
- [x] Update remaining debt:

```text
- CoachDecision still exists as provider contract.
- decision_legacy.py should now mostly orchestrate decide/onboarding/facts.
- next slice can target CoachDecision output contract or onboarding/facts split.
- canonical planning cutover remains opt-in until dogfood gates say otherwise.
```

- [x] Run:

```bash
./scripts/docs:list
```

- [x] Run full backend:

```bash
./scripts/test-backend -q
```

Expected: pass.

## Acceptance Criteria

```text
1. decision_legacy.py no longer owns provider, schema repair or tool-loop
   implementation bodies.
2. Public `fitmas.llm` private compatibility shims remain patchable.
3. Tool-loop behavior is directly tested in `legacy_tool_loop.py`.
4. Schema repair behavior is directly tested in `legacy_schema_repair.py`.
5. Provider request behavior is directly tested in `legacy_provider.py`.
6. Existing tool-use and prompt observability regressions pass.
7. Commands/pending canonical defaults remain unchanged.
8. Planning cutover remains opt-in.
9. Full backend suite passes.
```

## Expected End State

After 8N, `decision_legacy.py` should be roughly:

```text
imports / public re-exports
provider compatibility shims
decide() high-level orchestration
legacy onboarding voice/week-plan helpers
legacy fact extraction helpers
```

It should no longer be the owner of:

```text
gateway request mechanics
DeepSeek structured-output branching
tool-use loop state machine
tool trace construction
tool follow-up prompt bodies
schema repair prompt bodies
Claude schema fallback mechanics
```

That gives Phase 8O two clean options:

```text
Option A: reduce the CoachDecision provider contract itself.
Option B: split onboarding/fact legacy away from decision_legacy.py.
```

The CTO recommendation is Option A if 8N is stable, because the real product
risk is still `CoachDecision` as provider artifact. Option B is cleanup.

## Implementation Result

Delivered locally on 2026-05-17.

Key results:

- `decision_legacy.py` went from 1467 lines after 8M to 941 lines after 8N.
- `legacy_provider.py` owns provider request wrappers, DeepSeek structured
  branching, tool thinking kwargs and exception classification.
- `legacy_schema_repair.py` owns invalid payload repair, Claude schema
  fallback, prose-to-json repair and tool-result summaries.
- `legacy_tool_loop.py` owns the conversation tool-use loop, JSON compiler,
  retry formatting, tool follow-up content and tool trace construction.
- Public `fitmas.llm` private compatibility shims remain patchable.
- Commands/pending canonical lanes remain default-on.
- Planning cutover remains opt-in.

Verification evidence:

```bash
./scripts/test-backend -q tests/test_llm_package_compat.py tests/test_llm_legacy_provider.py tests/test_llm_legacy_schema_repair.py tests/test_llm_legacy_tool_loop.py tests/test_phase8n_provider_tool_loop_architecture.py
```

Result:

```text
23 passed
```

```bash
./scripts/test-backend -q tests/test_prompt_observability.py
```

Result:

```text
8 passed
```

```bash
./scripts/test-backend -q tests/test_llm_tools.py tests/test_decide_error_typing.py tests/test_coach_decision_actions.py
```

Result:

```text
87 passed
```

```bash
./scripts/test-backend -q tests/test_llm_legacy_tool_loop.py tests/test_llm_tools.py -k "tool"
```

Result:

```text
70 passed
```

```bash
./scripts/smoke-decision-runtime-provider-tool-loop
```

Result:

```text
RESULT: OK
```

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
  tests/test_phase8k_canonical_default_lanes_architecture.py \
  tests/test_phase8l_decide_authority_architecture.py \
  tests/test_phase8m_decision_legacy_split_architecture.py \
  tests/test_phase8n_provider_tool_loop_architecture.py
```

Result:

```text
83 passed
```

```bash
./scripts/test-backend -q
```

Result:

```text
1266 passed, 11 skipped, 11 subtests passed
```
