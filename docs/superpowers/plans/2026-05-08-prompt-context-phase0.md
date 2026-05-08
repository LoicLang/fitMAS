---
summary: implementation plan for Prompt Context Phase 0 observability
read_when:
  - continuing prompt context observability work
  - modifying prompt trace metadata
  - debugging decide None observability
  - adding prompt snapshots
---

# Prompt Context Phase 0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add prompt/context observability before changing prompt behavior.

**Architecture:** Phase 0 is read-only instrumentation. It introduces prompt trace metadata and snapshot helpers without changing LLM decisions, prompt content, tool budgets, validation, or final replies.

**Tech Stack:** Python 3.13, dataclasses, pytest, existing FitMAS prompt builders.

---

## Files

- Create: `backend/src/fitmas/prompt_observability.py`
  - Owns prompt trace dataclasses, prompt size calculation, normalized `decide()` failure reasons.
- Modify: `backend/src/fitmas/llm_prompt_builder.py`
  - Adds optional metadata to `ConversationPromptBundle`.
- Modify: `backend/src/fitmas/llm.py`
  - Populates trace metadata and logs normalized `decide()` None reasons.
- Create: `tests/test_prompt_observability.py`
  - Unit tests for trace data and reason normalization.
- Modify: `tests/test_llm_tools.py`
  - One targeted test proving `decide()` records a normalized reason when no data is returned.
- Create: `tests/snapshots/prompts/conversation_plan_lookup.txt`
  - First golden snapshot for the stable `plan_lookup` prompt route.

## Task 1: Prompt Observability Primitives

**Files:**
- Create: `backend/src/fitmas/prompt_observability.py`
- Test: `tests/test_prompt_observability.py`

- [ ] **Step 1: Write failing tests**

```python
from fitmas.prompt_observability import (
    DecideFailureReason,
    PromptTrace,
    build_prompt_trace,
    normalize_decide_failure_reason,
)


def test_build_prompt_trace_counts_system_and_user_chars() -> None:
    trace = build_prompt_trace(
        route="conversation_decide",
        provider="deepseek",
        model="deepseek-chat",
        prompt_policy="plan_lookup_compact",
        prompt_contract=None,
        intent="plan_lookup",
        system=[{"type": "text", "text": "system A"}, {"type": "text", "text": "system B"}],
        user_prompt="hello user",
        tool_names=("get_plan_window",),
        history_messages_used=2,
    )

    assert trace.route == "conversation_decide"
    assert trace.system_chars == len("system A") + len("system B")
    assert trace.user_chars == len("hello user")
    assert trace.tool_names == ("get_plan_window",)
    assert trace.history_messages_used == 2


def test_normalize_decide_failure_reason_accepts_known_values_only() -> None:
    assert normalize_decide_failure_reason("empty_output") == DecideFailureReason.EMPTY_OUTPUT
    assert normalize_decide_failure_reason("not-a-real-reason") == DecideFailureReason.UNKNOWN
```

- [ ] **Step 2: Verify red**

Run:

```bash
.venv/bin/python -m pytest tests/test_prompt_observability.py -q
```

Expected: FAIL because `fitmas.prompt_observability` does not exist.

- [ ] **Step 3: Implement primitives**

Create:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any, Sequence


class DecideFailureReason(StrEnum):
    NO_CLIENT = "no_client"
    PROVIDER_ERROR = "provider_error"
    TIMEOUT = "timeout"
    EMPTY_OUTPUT = "empty_output"
    TOOL_LOOP_FAILED = "tool_loop_failed"
    TOOL_RESULT_MISSING = "tool_result_missing"
    INVALID_JSON = "invalid_json"
    SCHEMA_INVALID = "schema_invalid"
    REPAIR_FAILED = "repair_failed"
    FALLBACK_FAILED = "fallback_failed"
    VOICE_GUARD_INVALID = "voice_guard_invalid"
    FACTUAL_VERIFIER_BLOCKED = "factual_verifier_blocked"
    PROMPT_TOO_LONG = "prompt_too_long"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class PromptTrace:
    route: str
    provider: str | None
    model: str | None
    prompt_policy: str | None
    prompt_contract: str | None
    intent: str | None
    system_chars: int
    user_chars: int
    total_chars: int
    tool_names: tuple[str, ...]
    history_messages_used: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_decide_failure_reason(raw: str | None) -> DecideFailureReason:
    if raw:
        try:
            return DecideFailureReason(str(raw).strip())
        except ValueError:
            return DecideFailureReason.UNKNOWN
    return DecideFailureReason.UNKNOWN


def build_prompt_trace(
    *,
    route: str,
    provider: str | None,
    model: str | None,
    prompt_policy: str | None,
    prompt_contract: str | None,
    intent: str | None,
    system: Sequence[dict[str, Any]] | str,
    user_prompt: str,
    tool_names: Sequence[str],
    history_messages_used: int,
) -> PromptTrace:
    if isinstance(system, str):
        system_chars = len(system)
    else:
        system_chars = sum(len(str(part.get("text") or "")) for part in system)
    user_chars = len(user_prompt or "")
    return PromptTrace(
        route=route,
        provider=provider,
        model=model,
        prompt_policy=prompt_policy,
        prompt_contract=prompt_contract,
        intent=intent,
        system_chars=system_chars,
        user_chars=user_chars,
        total_chars=system_chars + user_chars,
        tool_names=tuple(str(name) for name in tool_names),
        history_messages_used=int(history_messages_used or 0),
    )
```

- [ ] **Step 4: Verify green**

Run:

```bash
.venv/bin/python -m pytest tests/test_prompt_observability.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/fitmas/prompt_observability.py tests/test_prompt_observability.py
git commit -m "Add prompt observability primitives"
```

## Task 2: Attach Prompt Trace To Conversation Bundles

**Files:**
- Modify: `backend/src/fitmas/llm_prompt_builder.py`
- Test: `tests/test_prompt_observability.py`

- [ ] **Step 1: Write failing test**

```python
from fitmas.conversation_prompting import select_conversation_prompt_policy
from fitmas.llm_prompt_builder import build_layered_conversation_prompt
from fitmas.tools.routing import IntentCategory


def test_layered_prompt_bundle_exposes_trace_metadata() -> None:
    policy = select_conversation_prompt_policy(intent=IntentCategory.PLAN_LOOKUP)
    bundle = build_layered_conversation_prompt(
        user_text="J'ai quoi demain ?",
        prompt_policy=policy,
        time_block="Aujourd'hui: vendredi",
        timeline_summary="- Vendredi: Footing 40 min",
        execution_summary=None,
        temporal_summary=None,
        activity_claim_summary=None,
        signal_summary=None,
        conversation_history=[],
        coach_context={"turn_primary_intent": "plan_lookup"},
        selected_facts=[],
    )

    assert bundle.trace is not None
    assert bundle.trace.prompt_policy == "plan_lookup_compact"
    assert bundle.trace.intent == "plan_lookup"
    assert bundle.trace.total_chars > 0
```

- [ ] **Step 2: Verify red**

Run:

```bash
.venv/bin/python -m pytest tests/test_prompt_observability.py::test_layered_prompt_bundle_exposes_trace_metadata -q
```

Expected: FAIL because `ConversationPromptBundle.trace` does not exist.

- [ ] **Step 3: Implement minimal trace field**

Add `trace: PromptTrace | None = None` to `ConversationPromptBundle`, then pass
`build_prompt_trace(...)` from both `build_conversation_prompt_bundle()` and
`build_layered_conversation_prompt()`.

- [ ] **Step 4: Verify green**

Run:

```bash
.venv/bin/python -m pytest tests/test_prompt_observability.py tests/test_llm_prompt_builder.py tests/test_prompt_truth_gates.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/fitmas/llm_prompt_builder.py tests/test_prompt_observability.py
git commit -m "Trace conversation prompt bundles"
```

## Task 3: Normalize `decide()` None Reasons

**Files:**
- Modify: `backend/src/fitmas/llm.py`
- Test: `tests/test_llm_tools.py`

- [ ] **Step 1: Write failing test**

```python
def test_decide_logs_empty_output_reason_when_provider_returns_no_data(self) -> None:
    captured = []
    original_client = llm._client
    original_request = llm._request_structured_json
    try:
        llm._client = lambda: object()
        llm._request_structured_json = lambda *args, **kwargs: None
        decision = llm.decide("J'ai quoi demain ?", "Repere", coach_context={"turn_primary_intent": "plan_lookup"})
    finally:
        llm._client = original_client
        llm._request_structured_json = original_request

    assert decision is None
```

Use the existing `unittest.TestCase.assertLogs("fitmas.llm", level="INFO")`
pattern and assert `llm.decide_none reason=empty_output` appears.

- [ ] **Step 2: Verify red**

Run:

```bash
.venv/bin/python -m pytest tests/test_llm_tools.py::TestLLMTools::test_decide_logs_empty_output_reason_when_provider_returns_no_data -q
```

Expected: FAIL because the normalized log does not exist.

- [ ] **Step 3: Implement minimal logging helper**

Add a private helper in `llm.py`:

```python
def _log_decide_none(reason: DecideFailureReason, *, prompt_trace=None) -> None:
    logger.info(
        "llm.decide_none reason=%s prompt_trace=%s",
        reason.value,
        prompt_trace.as_dict() if prompt_trace else None,
    )
```

Call it before each current `return None` path in `decide()` where the reason is
known:

- no client -> `NO_CLIENT`
- no data -> `EMPTY_OUTPUT`
- parsed still none after repair/fallback -> `FALLBACK_FAILED`
- exception -> `PROVIDER_ERROR`

- [ ] **Step 4: Verify green**

Run:

```bash
.venv/bin/python -m pytest tests/test_llm_tools.py::TestLLMTools::test_decide_logs_empty_output_reason_when_provider_returns_no_data -q
```

Expected: PASS.

- [ ] **Step 5: Broader check**

Run:

```bash
.venv/bin/python -m pytest tests/test_llm_tools.py tests/test_prompt_observability.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/fitmas/llm.py tests/test_llm_tools.py
git commit -m "Log normalized decide none reasons"
```

## Task 4: Snapshot Harness Skeleton

**Files:**
- Create: `tests/test_prompt_snapshots.py`
- Create: `tests/snapshots/prompts/conversation_plan_lookup.txt`

- [ ] **Step 1: Write failing snapshot test**

Create a helper that renders one stable `plan_lookup` prompt and compares it to
`tests/snapshots/prompts/conversation_plan_lookup.txt`.

- [ ] **Step 2: Verify red**

Run:

```bash
.venv/bin/python -m pytest tests/test_prompt_snapshots.py -q
```

Expected: FAIL because snapshot file is missing.

- [ ] **Step 3: Add initial snapshot**

Write the current rendered prompt metadata and text to
`tests/snapshots/prompts/conversation_plan_lookup.txt`.

- [ ] **Step 4: Verify green**

Run:

```bash
.venv/bin/python -m pytest tests/test_prompt_snapshots.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_prompt_snapshots.py tests/snapshots/prompts/conversation_plan_lookup.txt
git commit -m "Add prompt snapshot harness"
```

## Final Verification For Phase 0 Slice

Run:

```bash
.venv/bin/python -m compileall backend/src/fitmas
git diff --check
.venv/bin/python -m pytest tests/test_prompt_observability.py tests/test_prompt_snapshots.py tests/test_llm_prompt_builder.py tests/test_prompt_truth_gates.py tests/test_llm_tools.py -q
./scripts/test-backend -q
```

Expected:

```text
compileall OK
git diff --check no output
targeted tests PASS
backend PASS
```
