---
summary: implementation plan for Decision Runtime Phase 6 canonical LLM prompts
read_when:
  - implementing Decision Runtime Phase 6
  - creating backend/src/fitmas/llm/prompts
  - simplifying Understanding, Reviewer or Reply prompts
  - moving fitmas.llm.py or llm_gateway.py toward the target repo organization
  - isolating legacy CoachDecision prompt contracts
---

# Decision Runtime Phase 6 Prompts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the canonical `fitmas.llm.prompts` package with three prompt families, while keeping dogfood behavior stable and isolating old `CoachDecision` prompt machinery as legacy compatibility.

**Architecture:** Phase 6 is not a new mega-prompt. It creates the target LLM package shape, extracts reusable prompt builders behind compatibility wrappers, and introduces the `Understanding / Reviewer / Reply` contract split. Runtime cutover stays conservative: reviewer and reply can route through the new builders because they already consume backend facts; Understanding starts as tested/shadow infrastructure before replacing the old `CoachDecision` path.

**Tech Stack:** Python 3.13, dataclasses, existing `llm_gateway`, existing prompt snapshot tests, pytest architecture tests, no DB or writer imports in prompt modules.

---

**Status 2026-05-14:** implemented locally. `fitmas.llm` is now a compatible
package, `fitmas.llm.gateway` owns the gateway implementation, canonical prompt
builders exist under `fitmas.llm.prompts`, reviewer/reply route through them,
and Understanding remains shadow-only. Full backend verification:
`./scripts/test-backend -q` -> 1070 passed, 11 skipped, 11 subtests passed.

## Phase 6 Boundary

Allowed:

- convert `backend/src/fitmas/llm.py` into the target package `backend/src/fitmas/llm/` with compatibility exports;
- move `llm_gateway.py` implementation to `backend/src/fitmas/llm/gateway.py` while keeping a root wrapper during migration;
- create `backend/src/fitmas/llm/prompts/base.py`;
- create `backend/src/fitmas/llm/prompts/contracts.py`;
- create `backend/src/fitmas/llm/prompts/understanding.py`;
- create `backend/src/fitmas/llm/prompts/reviewer.py`;
- create `backend/src/fitmas/llm/prompts/reply.py`;
- keep old `conversation_prompt_modules.py`, `prompt_contracts.py`, and `llm_prompt_builder.py` as legacy conversation prompt infrastructure for now;
- make existing reviewer/reply prompt builders delegate to the new prompt package;
- add architecture tests that prevent the new prompt package from importing runtime writers, DB, `conversation_pipeline`, legacy adapters or free-text parsers.

Forbidden:

- no default runtime switch from `CoachDecision` to `CoachUnderstanding`;
- no new deterministic parser on user text;
- no new `PlanPatch` output in Understanding;
- no final user-visible reply from Understanding;
- no DB imports, SQLAlchemy imports or write services in `fitmas.llm.prompts`;
- no heartbeat migration in this phase;
- no deletion of old prompt files until Phase 8;
- no broad rewrite of `conversation_pipeline.py`.

## Key Constraint

There is currently a file:

```text
backend/src/fitmas/llm.py
```

The target repo wants:

```text
backend/src/fitmas/llm/
  gateway.py
  prompts/
```

A Python package and a same-name file cannot coexist. Phase 6 must first turn
`fitmas.llm` into a package with compatibility exports. This is mechanical but
sensitive; do it before adding `fitmas.llm.prompts`.

## Target File Map

Create or move:

```text
backend/src/fitmas/llm/
  __init__.py                  compat exports for existing `from fitmas.llm import ...`
  decision_legacy.py           current `llm.py` contents, unchanged initially
  gateway.py                   current `llm_gateway.py` implementation
  prompts/
    __init__.py
    base.py                    pure prompt render helpers
    contracts.py               canonical three prompt contracts
    understanding.py           user intent/signals prompt, no reply, no patch
    reviewer.py                candidate review prompt, candidate_id only
    reply.py                   final reply prompt from backend facts only

backend/src/fitmas/llm_gateway.py
  temporary wrapper importing from `fitmas.llm.gateway`

backend/src/fitmas/plan_patch_candidate_reviewer.py
  convert candidate objects to reviewer prompt payloads

backend/src/fitmas/final_reply.py
  map FinalReplyContext to reply prompt input
```

Tests:

```text
tests/test_llm_package_compat.py
tests/test_llm_prompt_contracts.py
tests/test_llm_prompts_understanding.py
tests/test_llm_prompts_reviewer.py
tests/test_llm_prompts_reply.py
tests/test_phase6_prompt_architecture.py
```

Docs:

```text
docs/DECISION-RUNTIME-REFACTOR.md
docs/BUILD-ORDER.md
```

## Invariants

```text
INVARIANTS FITMAS DECISION RUNTIME - PHASE 6

1. Understanding prompt understands user language only.
2. Understanding prompt does not produce final text.
3. Understanding prompt does not produce PlanPatch, MutationDecision or DB commands.
4. Reviewer prompt chooses only among provided candidate IDs.
5. Reviewer prompt does not create patches, operations or user-visible text.
6. Reply prompt speaks only from backend facts, events and DecisionOutcome-derived context.
7. New prompt modules import no DB, no writers, no conversation_pipeline and no legacy adapters.
8. Legacy CoachDecision prompt stack remains compatibility until explicit cutover.
9. `fitmas.llm` package migration preserves existing imports.
10. Full backend tests must stay green before any Phase 7 work starts.
```

## Task 1: Convert `fitmas.llm` Into A Package Without Behavior Change

**Files:**
- Move: `backend/src/fitmas/llm.py` -> `backend/src/fitmas/llm/decision_legacy.py`
- Move: `backend/src/fitmas/llm_gateway.py` -> `backend/src/fitmas/llm/gateway.py`
- Create: `backend/src/fitmas/llm/__init__.py`
- Create: `backend/src/fitmas/llm_gateway.py`
- Create: `tests/test_llm_package_compat.py`

- [ ] **Step 1: Write compatibility tests first**

Create `tests/test_llm_package_compat.py`:

```python
from __future__ import annotations


def test_fitmas_llm_package_reexports_legacy_decision_contracts() -> None:
    from fitmas.llm import CoachDecision, decide, parse_coach_decision_payload
    from fitmas.llm.decision_legacy import CoachDecision as LegacyCoachDecision

    assert CoachDecision is LegacyCoachDecision
    assert callable(decide)
    assert callable(parse_coach_decision_payload)


def test_llm_gateway_wrapper_reexports_new_gateway_module() -> None:
    from fitmas import llm_gateway
    from fitmas.llm import gateway

    assert llm_gateway.request_json is gateway.request_json
    assert llm_gateway.request_text is gateway.request_text
```

- [ ] **Step 2: Run tests to verify current package shape fails**

Run:

```bash
./scripts/test-backend tests/test_llm_package_compat.py -q
```

Expected: fails because `fitmas.llm.decision_legacy` and `fitmas.llm.gateway` do not exist yet.

- [ ] **Step 3: Move the files mechanically**

Use shell moves, then edit with `apply_patch`:

```bash
tmp_llm=/tmp/fitmas_llm_decision_legacy.py
mv backend/src/fitmas/llm.py "$tmp_llm"
mkdir -p backend/src/fitmas/llm
mv "$tmp_llm" backend/src/fitmas/llm/decision_legacy.py
mv backend/src/fitmas/llm_gateway.py backend/src/fitmas/llm/gateway.py
```

Create `backend/src/fitmas/llm/__init__.py`:

```python
from __future__ import annotations

from .decision_legacy import *  # noqa: F401,F403
```

Create temporary wrapper `backend/src/fitmas/llm_gateway.py`:

```python
from __future__ import annotations

from fitmas.llm.gateway import *  # noqa: F401,F403
```

- [ ] **Step 4: Fix imports only if tests expose a real import cycle**

Allowed mechanical import change:

```python
from fitmas.llm_gateway import request_json, request_text
```

can become:

```python
from fitmas.llm.gateway import request_json, request_text
```

Do not rewrite decision logic in this task.

- [ ] **Step 5: Verify package compatibility**

Run:

```bash
./scripts/test-backend tests/test_llm_package_compat.py tests/test_llm_gateway_json.py tests/test_coach_decision_actions.py -q
```

Expected: pass.

## Task 2: Add Canonical Prompt Contracts

**Files:**
- Create: `backend/src/fitmas/llm/prompts/__init__.py`
- Create: `backend/src/fitmas/llm/prompts/contracts.py`
- Create: `tests/test_llm_prompt_contracts.py`

- [ ] **Step 1: Write contract tests**

Create `tests/test_llm_prompt_contracts.py`:

```python
from __future__ import annotations

from fitmas.llm.prompts.contracts import (
    REPLY_PROMPT_CONTRACT,
    REVIEWER_PROMPT_CONTRACT,
    UNDERSTANDING_PROMPT_CONTRACT,
    list_canonical_prompt_contracts,
)


def test_phase6_has_exactly_three_canonical_prompt_families() -> None:
    contracts = list_canonical_prompt_contracts()

    assert tuple(contract.family for contract in contracts) == ("understanding", "reviewer", "reply")


def test_understanding_contract_cannot_write_or_speak() -> None:
    contract = UNDERSTANDING_PROMPT_CONTRACT

    assert contract.family == "understanding"
    assert contract.output_schema == "CoachUnderstanding"
    assert contract.can_write is False
    assert contract.can_speak_to_user is False
    assert contract.allowed_outputs == ("intent", "signals", "requested_change", "pending_resolution", "clarification_need")
    assert "PlanPatch" in contract.forbidden_outputs
    assert "final_reply" in contract.forbidden_outputs


def test_reviewer_contract_only_selects_candidates() -> None:
    contract = REVIEWER_PROMPT_CONTRACT

    assert contract.family == "reviewer"
    assert contract.output_schema == "CandidateReviewDecision"
    assert contract.can_write is False
    assert contract.can_speak_to_user is False
    assert contract.allowed_outputs == ("preferred_candidate_id", "confidence", "rationale")


def test_reply_contract_can_speak_but_not_write() -> None:
    contract = REPLY_PROMPT_CONTRACT

    assert contract.family == "reply"
    assert contract.output_schema == "final_text"
    assert contract.can_write is False
    assert contract.can_speak_to_user is True
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
./scripts/test-backend tests/test_llm_prompt_contracts.py -q
```

Expected: fails because `fitmas.llm.prompts.contracts` does not exist.

- [ ] **Step 3: Implement contracts**

Create `backend/src/fitmas/llm/prompts/contracts.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


PromptFamily = Literal["understanding", "reviewer", "reply"]


@dataclass(frozen=True, slots=True)
class CanonicalPromptContract:
    name: str
    family: PromptFamily
    output_schema: str
    allowed_outputs: tuple[str, ...]
    forbidden_outputs: tuple[str, ...]
    can_write: bool
    can_speak_to_user: bool


UNDERSTANDING_PROMPT_CONTRACT = CanonicalPromptContract(
    name="decision_understanding",
    family="understanding",
    output_schema="CoachUnderstanding",
    allowed_outputs=("intent", "signals", "requested_change", "pending_resolution", "clarification_need"),
    forbidden_outputs=("final_reply", "reply_text", "fitmas_message", "PlanPatch", "MutationDecision", "commands"),
    can_write=False,
    can_speak_to_user=False,
)

REVIEWER_PROMPT_CONTRACT = CanonicalPromptContract(
    name="planning_candidate_reviewer",
    family="reviewer",
    output_schema="CandidateReviewDecision",
    allowed_outputs=("preferred_candidate_id", "confidence", "rationale"),
    forbidden_outputs=("PlanPatch", "operations", "final_reply", "reply_text", "commands"),
    can_write=False,
    can_speak_to_user=False,
)

REPLY_PROMPT_CONTRACT = CanonicalPromptContract(
    name="decision_reply",
    family="reply",
    output_schema="final_text",
    allowed_outputs=("final_text",),
    forbidden_outputs=("commands", "PlanPatch", "MutationDecision"),
    can_write=False,
    can_speak_to_user=True,
)


def list_canonical_prompt_contracts() -> tuple[CanonicalPromptContract, ...]:
    return (UNDERSTANDING_PROMPT_CONTRACT, REVIEWER_PROMPT_CONTRACT, REPLY_PROMPT_CONTRACT)
```

Create `backend/src/fitmas/llm/prompts/__init__.py`:

```python
from __future__ import annotations

from .contracts import (
    CanonicalPromptContract,
    REPLY_PROMPT_CONTRACT,
    REVIEWER_PROMPT_CONTRACT,
    UNDERSTANDING_PROMPT_CONTRACT,
    list_canonical_prompt_contracts,
)

__all__ = [
    "CanonicalPromptContract",
    "UNDERSTANDING_PROMPT_CONTRACT",
    "REVIEWER_PROMPT_CONTRACT",
    "REPLY_PROMPT_CONTRACT",
    "list_canonical_prompt_contracts",
]
```

- [ ] **Step 4: Verify contracts**

Run:

```bash
./scripts/test-backend tests/test_llm_prompt_contracts.py -q
```

Expected: pass.

## Task 3: Add Pure Prompt Rendering Helpers

**Files:**
- Create: `backend/src/fitmas/llm/prompts/base.py`
- Modify: `backend/src/fitmas/llm/prompts/__init__.py`
- Create: `tests/test_llm_prompts_base.py`

- [ ] **Step 1: Write helper tests**

Create `tests/test_llm_prompts_base.py`:

```python
from __future__ import annotations

from fitmas.llm.prompts.base import PromptRender, join_sections, render_json_block


def test_join_sections_drops_empty_sections() -> None:
    assert join_sections("A", "", None, "B") == "A\n\nB"


def test_render_json_block_is_stable_and_french_safe() -> None:
    rendered = render_json_block({"reason": "douleur épaule", "duration": 35})

    assert '"reason": "douleur épaule"' in rendered
    assert '"duration": 35' in rendered


def test_prompt_render_exposes_system_and_prompt() -> None:
    render = PromptRender(system="system", prompt="prompt", max_tokens=300)

    assert render.system == "system"
    assert render.prompt == "prompt"
    assert render.max_tokens == 300
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
./scripts/test-backend tests/test_llm_prompts_base.py -q
```

Expected: fails because `base.py` does not exist.

- [ ] **Step 3: Implement helpers**

Create `backend/src/fitmas/llm/prompts/base.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any


@dataclass(frozen=True, slots=True)
class PromptRender:
    system: str
    prompt: str
    max_tokens: int


def join_sections(*sections: str | None) -> str:
    return "\n\n".join(str(section).strip() for section in sections if str(section or "").strip())


def render_json_block(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str)
```

- [ ] **Step 4: Verify helpers**

Run:

```bash
./scripts/test-backend tests/test_llm_prompts_base.py -q
```

Expected: pass.

## Task 4: Add Canonical Understanding Prompt In Shadow

**Files:**
- Create: `backend/src/fitmas/llm/prompts/understanding.py`
- Create: `tests/test_llm_prompts_understanding.py`
- Modify: `tests/test_phase6_prompt_architecture.py`

- [ ] **Step 1: Write Understanding prompt tests**

Create `tests/test_llm_prompts_understanding.py`:

```python
from __future__ import annotations

from fitmas.llm.prompts.understanding import UnderstandingPromptInput, build_understanding_prompt


def test_understanding_prompt_outputs_coach_understanding_only() -> None:
    rendered = build_understanding_prompt(
        UnderstandingPromptInput(
            event_summary="telegram user_message: j'ai mal dormi, je peux alléger ce soir ?",
            context_blocks=("today: 2026-05-14", "plan: séance intense ce soir"),
        )
    )

    text = f"{rendered.system}\n{rendered.prompt}"
    assert "CoachUnderstanding" in text
    assert "fitmas_message" not in text
    assert "PlanPatch" not in text
    assert "MutationDecision" not in text
    assert "ne parles pas au user" in text


def test_understanding_prompt_contains_requested_change_shape() -> None:
    rendered = build_understanding_prompt(
        UnderstandingPromptInput(
            event_summary="telegram user_message: décale la séance à vendredi",
            context_blocks=("plan: jeudi tempo id=12",),
        )
    )

    assert '"intent"' in rendered.prompt
    assert '"requested_change"' in rendered.prompt
    assert '"pending_resolution"' in rendered.prompt
    assert '"clarification_need"' in rendered.prompt
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
./scripts/test-backend tests/test_llm_prompts_understanding.py -q
```

Expected: fails because `understanding.py` does not exist.

- [ ] **Step 3: Implement Understanding prompt**

Create `backend/src/fitmas/llm/prompts/understanding.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from .base import PromptRender, join_sections, render_json_block


@dataclass(frozen=True, slots=True)
class UnderstandingPromptInput:
    event_summary: str
    context_blocks: tuple[str, ...]


def build_understanding_prompt(data: UnderstandingPromptInput) -> PromptRender:
    system = join_sections(
        "Tu es FitMAS Understanding LLM.",
        "Tu comprends le message utilisateur et le contexte compact.",
        "Tu ne parles pas au user.",
        "Tu ne composes aucun message visible.",
        "Tu ne produis pas de patch planning, ancienne mutation, commande DB ou write.",
        "Tu retournes uniquement un JSON CoachUnderstanding valide.",
    )
    schema = {
        "intent": "close | general_answer | plan_lookup | execution_report | health_signal | availability_signal | plan_change | pending_response | clarification",
        "confidence": "0..1",
        "user_summary": "short factual summary of the user message",
        "extracted_signals": [
            {
                "type": "fatigue | pain | availability | preference | execution | other",
                "status": "new | update | correction",
                "severity": "low | medium | high | unknown",
                "evidence": "user-provided evidence only",
            }
        ],
        "requested_change": {
            "kind": "move | swap | lighten | replace | create | remove_optional | unknown",
            "source_ref": "typed reference or null",
            "target_ref": "typed reference or null",
            "desired_sport": "sport or null",
            "desired_duration_min": "integer or null",
            "desired_intensity": "string or null",
            "reason": "why the change is requested",
            "risk_signals": ["fatigue | pain | load | availability"],
        },
        "pending_resolution": {
            "type": "accept | reject | modify | ignore | needs_clarification",
            "reason": "why this pending interpretation fits",
        },
        "clarification_need": {
            "question": "only if essential information is missing",
            "missing_fields": ["field names"],
        },
    }
    prompt = join_sections(
        f"InputEvent:\n{data.event_summary}",
        "CoachContext compact:",
        *data.context_blocks,
        "Output JSON schema:",
        render_json_block(schema),
    )
    return PromptRender(system=system, prompt=prompt, max_tokens=900)
```

- [ ] **Step 4: Verify Understanding prompt**

Run:

```bash
./scripts/test-backend tests/test_llm_prompts_understanding.py -q
```

Expected: pass.

## Task 5: Extract Reviewer Prompt Builder

**Files:**
- Create: `backend/src/fitmas/llm/prompts/reviewer.py`
- Modify: `backend/src/fitmas/plan_patch_candidate_reviewer.py`
- Create: `tests/test_llm_prompts_reviewer.py`
- Run existing: `tests/test_plan_patch_candidate_reviewer.py` if present, otherwise reviewer-related planning tests

- [ ] **Step 1: Write reviewer prompt tests**

Create `tests/test_llm_prompts_reviewer.py`:

```python
from __future__ import annotations

from fitmas.llm.prompts.reviewer import ReviewerPromptCandidate, build_reviewer_prompt


def test_reviewer_prompt_only_allows_candidate_id_selection() -> None:
    rendered = build_reviewer_prompt(
        (
            ReviewerPromptCandidate(
                candidate_id="candidate_a",
                rationale="préserve la séance clé",
                expected_tradeoff="moins de charge ce soir",
                score_total=0.82,
                score_delta=0.2,
                policy_hint="commit",
                findings=("charge stable",),
                operations=("replace_session target_session_id=12",),
            ),
            ReviewerPromptCandidate(
                candidate_id="candidate_b",
                rationale="force l'intensité",
                expected_tradeoff="risque fatigue",
                score_total=0.41,
                score_delta=-0.1,
                policy_hint="pending",
                findings=("fatigue proche",),
                operations=("move_session target_session_id=12 target_date=2026-05-16",),
            ),
        )
    )

    text = f"{rendered.system}\n{rendered.prompt}"
    assert "preferred_candidate_id" in text
    assert "candidate_a" in text
    assert "candidate_b" in text
    assert "Ne produis aucun patch" in text
    assert "user-facing" not in text
    assert "fitmas_message" not in text
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
./scripts/test-backend tests/test_llm_prompts_reviewer.py -q
```

Expected: fails because `reviewer.py` does not exist.

- [ ] **Step 3: Implement reviewer prompt module**

Create `backend/src/fitmas/llm/prompts/reviewer.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from .base import PromptRender, render_json_block


@dataclass(frozen=True, slots=True)
class ReviewerPromptCandidate:
    candidate_id: str
    rationale: str
    expected_tradeoff: str | None
    score_total: float | None
    score_delta: float | None
    policy_hint: str | None
    findings: tuple[str, ...]
    operations: tuple[str, ...]


def build_reviewer_prompt(candidates: tuple[ReviewerPromptCandidate, ...]) -> PromptRender:
    system = (
        "Tu es FitMAS SportReviewer LLM. "
        "Tu choisis uniquement parmi les candidate_id fournis. "
        "Ne produis aucun patch, aucune operation, aucune commande et aucun texte visible utilisateur."
    )
    payload = {
        "candidates": [
            {
                "candidate_id": candidate.candidate_id,
                "rationale": candidate.rationale,
                "expected_tradeoff": candidate.expected_tradeoff,
                "score_total": candidate.score_total,
                "score_delta": candidate.score_delta,
                "policy_hint": candidate.policy_hint,
                "findings": list(candidate.findings),
                "operations": list(candidate.operations),
            }
            for candidate in candidates
        ],
        "output_contract": {
            "preferred_candidate_id": "one of candidates[].candidate_id",
            "confidence": "0..1",
            "rationale": ["short reasons based only on candidate facts"],
        },
    }
    return PromptRender(
        system=system,
        prompt="Choisis le meilleur compromis sportif parmi ces candidates deja construites.\n\n"
        f"Contexte JSON:\n{render_json_block(payload)}",
        max_tokens=600,
    )
```

- [ ] **Step 4: Route existing reviewer through new prompt builder**

In `backend/src/fitmas/plan_patch_candidate_reviewer.py`:

```python
from fitmas.llm.prompts.reviewer import ReviewerPromptCandidate, build_reviewer_prompt
```

Replace `_reviewer_system()` and `_reviewer_prompt(...)` call site with:

```python
rendered = build_reviewer_prompt(tuple(_reviewer_candidate_payload(candidate) for candidate in reviewable))
payload = request_json_fn(
    system=rendered.system,
    prompt=rendered.prompt,
    max_tokens=rendered.max_tokens,
)
```

Add adapter:

```python
def _reviewer_candidate_payload(candidate: EvaluatedPlanPatchCandidate) -> ReviewerPromptCandidate:
    return ReviewerPromptCandidate(
        candidate_id=candidate.candidate.id,
        rationale=candidate.candidate.rationale,
        expected_tradeoff=candidate.candidate.expected_tradeoff,
        score_total=candidate.score.total if candidate.score is not None else None,
        score_delta=candidate.score_delta,
        policy_hint=candidate.policy_hint,
        findings=tuple(f"{finding.code}: {finding.severity}: {finding.message}" for finding in candidate.findings),
        operations=tuple(
            " | ".join(
                str(part)
                for part in (
                    operation.operation_type,
                    f"target_session_id={operation.target_session_id}" if operation.target_session_id is not None else "",
                    f"second_session_id={operation.second_session_id}" if operation.second_session_id is not None else "",
                    f"target_date={operation.target_date}" if operation.target_date else "",
                    f"new_sport_type={operation.new_sport_type}" if operation.new_sport_type else "",
                    f"new_session_type={operation.new_session_type}" if operation.new_session_type else "",
                    f"new_duration_min={operation.new_duration_min}" if operation.new_duration_min is not None else "",
                    f"new_intensity={operation.new_intensity}" if operation.new_intensity else "",
                )
                if part
            )
            for operation in (candidate.patch.operations if candidate.patch is not None else ())
        ),
    )
```

Keep old private helpers only if existing tests import them. If no tests import them, remove them after reviewer tests pass.

- [ ] **Step 5: Verify reviewer behavior**

Run:

```bash
./scripts/test-backend tests/test_llm_prompts_reviewer.py tests/test_domain_planning_evaluator_policy.py tests/test_domain_planning_decision_service.py -q
```

Expected: pass.

## Task 6: Extract Reply Prompt Builder

**Files:**
- Create: `backend/src/fitmas/llm/prompts/reply.py`
- Modify: `backend/src/fitmas/final_reply.py`
- Create: `tests/test_llm_prompts_reply.py`
- Run existing: `tests/test_final_reply.py`, `tests/test_legacy_final_reply_backend.py`

- [ ] **Step 1: Write reply prompt tests**

Create `tests/test_llm_prompts_reply.py`:

```python
from __future__ import annotations

from fitmas.llm.prompts.reply import ReplyPromptInput, build_reply_prompt


def test_reply_prompt_uses_backend_facts_and_forbids_invention() -> None:
    rendered = build_reply_prompt(
        ReplyPromptInput(
            pipeline="conversation",
            capability="plan_committed",
            user_text="décale à vendredi",
            original_llm_reply="Je le décale.",
            committed_events=("Footing déplacé vendredi.",),
            blocked_events=(),
            pending_summary=None,
            memory_actions_applied=(),
            execution_actions_applied=(),
            allowed_to_claim_mutation=True,
            extra_facts=("before=jeudi", "after=vendredi"),
        )
    )

    assert "Evenements commits:" in rendered.prompt
    assert "Footing déplacé vendredi." in rendered.prompt
    assert "Tu ne dois jamais inventer un commit" in rendered.system
    assert "Reponds uniquement avec le texte final" in rendered.system


def test_reply_prompt_marks_no_commit_as_uncommitted() -> None:
    rendered = build_reply_prompt(
        ReplyPromptInput(
            pipeline="conversation",
            capability="plan_pending",
            user_text="allège ce soir",
            original_llm_reply="",
            committed_events=(),
            blocked_events=(),
            pending_summary="Allègement à confirmer.",
            memory_actions_applied=(),
            execution_actions_applied=(),
            allowed_to_claim_mutation=False,
            extra_facts=(),
        )
    )

    assert "Aucun changement planning n'a ete commit." in rendered.prompt
    assert "Confirmation en attente: Allègement à confirmer." in rendered.prompt
    assert "ne claim pas une action appliquee" in rendered.prompt
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
./scripts/test-backend tests/test_llm_prompts_reply.py -q
```

Expected: fails because `reply.py` does not exist.

- [ ] **Step 3: Implement reply prompt module**

Create `backend/src/fitmas/llm/prompts/reply.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from fitmas import coach_voice

from .base import PromptRender


@dataclass(frozen=True, slots=True)
class ReplyPromptBlockedEvent:
    command: str
    reason: str | None = None
    suggested_fix: str | None = None
    warning: str | None = None


@dataclass(frozen=True, slots=True)
class ReplyPromptInput:
    pipeline: str
    capability: str
    user_text: str
    original_llm_reply: str
    committed_events: tuple[str, ...]
    blocked_events: tuple[ReplyPromptBlockedEvent, ...]
    pending_summary: str | None
    memory_actions_applied: tuple[str, ...]
    execution_actions_applied: tuple[str, ...]
    allowed_to_claim_mutation: bool
    extra_facts: tuple[str, ...]


def build_reply_prompt(context: ReplyPromptInput) -> PromptRender:
    system = (
        f"{coach_voice.COACH_VOICE_RULES}\n\n"
        "Tu composes la reponse finale visible au user a partir de faits backend.\n"
        "Le backend a deja valide, bloque, commit ou cree une confirmation.\n"
        "Tu ne dois jamais inventer un commit. Tu ne dois jamais exposer les noms techniques "
        "(reviewer, patch, runtime, fallback, commit, JSON, tool, offplan).\n"
        "Reponds uniquement avec le texte final, sans JSON ni markdown."
    )
    lines = [
        f"Pipeline: {context.pipeline}",
        f"Capacite pipeline: {context.capability}",
        f"Message user: {context.user_text or '(non fourni)'}",
    ]
    if context.original_llm_reply:
        lines.append(f"Brouillon LLM initial: {context.original_llm_reply}")
    if context.committed_events:
        lines.append("Evenements commits:")
        lines.extend(f"- {event}" for event in context.committed_events)
        lines.append("Contrainte: l'action est deja commit; ne demande pas confirmation.")
    else:
        lines.append("Aucun changement planning n'a ete commit.")
    if context.blocked_events:
        lines.append("Evenements bloques:")
        for event in context.blocked_events:
            bits = [event.command]
            if event.reason:
                bits.append(f"reason={event.reason}")
            if event.suggested_fix:
                bits.append(f"suggested_fix={event.suggested_fix}")
            if event.warning:
                bits.append(f"warning={event.warning}")
            lines.append("- " + " | ".join(bits))
    if context.pending_summary:
        lines.append(f"Confirmation en attente: {context.pending_summary}")
        lines.append("Contrainte: la reponse doit presenter le changement comme une proposition et demander confirmation explicitement.")
    if context.execution_actions_applied:
        lines.append("Execution appliquee:")
        lines.extend(f"- {item}" for item in context.execution_actions_applied)
    if context.memory_actions_applied:
        lines.append("Memoire appliquee:")
        lines.extend(f"- {item}" for item in context.memory_actions_applied)
    if context.extra_facts:
        lines.append("Faits utiles:")
        lines.extend(f"- {item}" for item in context.extra_facts)
    if not context.allowed_to_claim_mutation:
        lines.append("Contrainte: ne claim pas une action appliquee, deplacee, posee, calee ou enregistree.")
    lines.append("Ecris 1-2 phrases. Si c'est bloque, donne la raison concrete et une alternative simple.")
    return PromptRender(system=system, prompt="\n".join(lines), max_tokens=300)
```

- [ ] **Step 4: Make `final_reply.build_final_reply_prompt()` delegate**

In `backend/src/fitmas/final_reply.py`, import:

```python
from fitmas.llm.prompts.reply import ReplyPromptBlockedEvent, ReplyPromptInput, build_reply_prompt
```

Replace the body of `build_final_reply_prompt(context)` with:

```python
def build_final_reply_prompt(context: FinalReplyContext) -> tuple[str, str]:
    rendered = build_reply_prompt(
        ReplyPromptInput(
            pipeline=context.pipeline,
            capability=context.pipeline_capability,
            user_text=context.user_text,
            original_llm_reply=context.original_llm_reply,
            committed_events=context.committed_events,
            blocked_events=tuple(
                ReplyPromptBlockedEvent(
                    command=event.command,
                    reason=event.reason,
                    suggested_fix=event.suggested_fix,
                    warning=event.warning,
                )
                for event in context.blocked_events
            ),
            pending_summary=context.pending_summary,
            memory_actions_applied=context.memory_actions_applied,
            execution_actions_applied=context.execution_actions_applied,
            allowed_to_claim_mutation=context.allowed_to_claim_mutation,
            extra_facts=context.extra_facts,
        )
    )
    return rendered.system, rendered.prompt
```

- [ ] **Step 5: Verify reply parity**

Run:

```bash
./scripts/test-backend tests/test_llm_prompts_reply.py tests/test_final_reply.py tests/test_legacy_final_reply_backend.py tests/test_decision_reply_composer.py -q
```

Expected: pass.

## Task 7: Add Phase 6 Architecture Gates

**Files:**
- Create: `tests/test_phase6_prompt_architecture.py`
- Modify: `tests/test_decision_runtime_architecture.py` only if import rules need the new `llm` package path

- [ ] **Step 1: Add architecture tests**

Create `tests/test_phase6_prompt_architecture.py`:

```python
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROMPTS = ROOT / "backend" / "src" / "fitmas" / "llm" / "prompts"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_prompt_package_has_only_three_canonical_prompt_modules() -> None:
    modules = {path.name for path in PROMPTS.glob("*.py")}

    assert {"base.py", "contracts.py", "understanding.py", "reviewer.py", "reply.py", "__init__.py"}.issubset(modules)


def test_new_prompt_modules_do_not_import_runtime_or_writers() -> None:
    forbidden_exact = {
        "fitmas.conversation_pipeline",
        "fitmas.db",
        "fitmas.models",
        "fitmas.plan_mutation_service",
        "fitmas.memory_mutation_service",
        "fitmas.execution_mutation_service",
        "fitmas.legacy",
    }
    offenders: list[str] = []
    for path in sorted(PROMPTS.glob("*.py")):
        if path.name == "__init__.py":
            continue
        for module in _imports(path):
            if module in forbidden_exact or module.startswith("sqlalchemy"):
                offenders.append(f"{path.name}: {module}")

    assert offenders == []


def test_understanding_prompt_source_has_no_legacy_output_tokens() -> None:
    source = (PROMPTS / "understanding.py").read_text(encoding="utf-8")
    forbidden = ("fitmas_message", "MutationDecision", "PlanPatch", "reply_text", "final_reply")

    assert [token for token in forbidden if token in source] == []


def test_reviewer_prompt_source_does_not_create_patch_or_user_text() -> None:
    source = (PROMPTS / "reviewer.py").read_text(encoding="utf-8")
    forbidden = ("fitmas_message", "coach_message", "reply_text", "commands")

    assert [token for token in forbidden if token in source] == []
```

- [ ] **Step 2: Run architecture tests**

Run:

```bash
./scripts/test-backend tests/test_phase6_prompt_architecture.py tests/test_decision_runtime_architecture.py -q
```

Expected: pass.

## Task 8: Document Legacy Prompt Boundaries

**Files:**
- Modify: `docs/DECISION-RUNTIME-REFACTOR.md`
- Modify: `docs/BUILD-ORDER.md`

- [ ] **Step 1: Update canonical refactor doc**

In `docs/DECISION-RUNTIME-REFACTOR.md`, add under implementation state:

```markdown
Phase 6 initiale cible :

- `fitmas.llm` devient progressivement un package cible ;
- les prompts canoniques vivent sous `fitmas.llm.prompts` ;
- les familles canoniques sont `Understanding`, `Reviewer`, `Reply` ;
- l'ancien stack `CoachDecision` / `conversation_prompt_modules.py` reste legacy compat jusqu'au cutover ;
- aucun changement runtime par defaut tant que les snapshots et dogfood ne prouvent pas la parite.
```

- [ ] **Step 2: Update build order**

In `docs/BUILD-ORDER.md`, mark:

```markdown
- Phase 6 planifiee :
  - convertir `fitmas.llm` en package compatible ;
  - ajouter `fitmas.llm.prompts.{understanding,reviewer,reply}` ;
  - router reviewer/reply vers les nouveaux builders ;
  - garder Understanding en shadow avant cutover.
```

- [ ] **Step 3: Verify docs front matter remains valid**

Run:

```bash
./scripts/docs:list
```

Expected: includes this Phase 6 plan and does not error.

## Task 9: Full Verification

**Files:**
- No new files.

- [ ] **Step 1: Run focused Phase 6 tests**

Run:

```bash
./scripts/test-backend \
  tests/test_llm_package_compat.py \
  tests/test_llm_prompt_contracts.py \
  tests/test_llm_prompts_base.py \
  tests/test_llm_prompts_understanding.py \
  tests/test_llm_prompts_reviewer.py \
  tests/test_llm_prompts_reply.py \
  tests/test_phase6_prompt_architecture.py \
  tests/test_final_reply.py \
  tests/test_legacy_final_reply_backend.py \
  tests/test_domain_planning_decision_service.py \
  -q
```

Expected: pass.

- [ ] **Step 2: Run full backend**

Run:

```bash
./scripts/test-backend -q
```

Expected: full backend passes.

- [ ] **Step 3: Run whitespace diff check**

Run:

```bash
git diff --check
```

Expected: no output.

## Acceptance Criteria

- `backend/src/fitmas/llm/` exists as a package.
- Existing `from fitmas.llm import CoachDecision, decide` imports still work.
- Existing `fitmas.llm_gateway` imports still work through a wrapper.
- `backend/src/fitmas/llm/prompts/` contains exactly the canonical prompt infrastructure for Understanding, Reviewer and Reply.
- Reviewer prompt runtime uses the new prompt builder.
- Final reply prompt runtime uses the new prompt builder.
- Understanding prompt is built and tested but not the default runtime decision path.
- `decision/` remains independent of `llm/`.
- New prompt modules do not import DB, writers, `conversation_pipeline` or `legacy`.
- Full backend tests pass.

## What Remains After Phase 6

- Phase 7: route heartbeat through `InputEvent -> DecisionRuntime -> ReplyComposer`.
- Phase 8: remove legacy prompt contracts, `CoachDecision` runtime paths, root wrappers and obsolete prompt modules once cutover is safe.
- Target repo organization continues toward:

```text
backend/src/fitmas/
  llm/
    gateway.py
    prompts/
      base.py
      contracts.py
      understanding.py
      reply.py
      reviewer.py
```
