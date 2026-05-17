---
summary: implementation plan for Decision Runtime Phase 8H pending reply cleanup
read_when:
  - implementing Decision Runtime Phase 8H
  - routing pending confirmation replies through DecisionOutcome and ReplyComposer
  - removing legacy fitmas_message speech from conversation_pending_bridge
  - tightening user-visible output boundaries after Phase 8G
---

# Decision Runtime Phase 8H Pending Reply Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route all non-committing pending confirmation replies through `DecisionOutcome -> DecisionReplyComposer`, so `conversation_pending_bridge.py` applies pending state but no longer speaks from `CoachDecision.fitmas_message` or local canned strings.

**Architecture:** Keep `conversation_pending_bridge.py` as the application boundary for pending state. Add a focused `legacy/pending_reply_adapter.py` that converts pending states into `DecisionOutcome` objects and composes text via `DecisionReplyComposer`. Keep provider behavior stable: `CoachDecision.pending_resolution` remains default, canonical `CoachUnderstanding.pending_resolution` remains behind `FITMAS_PENDING_FROM_UNDERSTANDING`.

**Tech Stack:** Python 3.13, dataclasses, existing `DecisionOutcome`, `DecisionReplyComposer`, `DecisionOutputVerifier`, pytest/unittest, SQLAlchemy test fixtures.

---

## CTO Decision

8H is not a provider cutover.

Do **not** remove `CoachDecision`, `llm/decision_legacy.py`, or `conversation_prompt_modules.py`.

The useful cut is:

```text
pending bridge decides pending state
  -> pending_reply_adapter builds DecisionOutcome
  -> DecisionReplyComposer composes / verifies
  -> ConversationTurnOutcome carries final text
```

This finishes the boundary opened in 8G: the pending bridge can still apply or keep pending, but visible speech must come from the common reply path.

## Scope

8H includes:

```text
1. Add `legacy/pending_reply_adapter.py`.
2. Convert pending reject / ignore / modify / needs_clarification replies to `DecisionOutcome`.
3. Convert pending recheck mismatch replies to `DecisionOutcome`.
4. Convert expired / not active / accept error replies to `DecisionOutcome`.
5. Convert plan_patch_choice missing/invalid selection replies to `DecisionOutcome`.
6. Remove direct use of `decision.fitmas_message` from `conversation_pending_bridge.py`.
7. Preserve plan_patch accepted / blocked replies already routed through the planning composer.
8. Add architecture tests proving pending speech is no longer local to the bridge.
9. Keep all existing pending behavior and response modes stable.
```

8H does **not** include:

```text
1. Enabling `FITMAS_PENDING_FROM_UNDERSTANDING` by default.
2. Removing `CoachDecision.pending_resolution`.
3. Removing `final_reply.py`.
4. Rewriting the full Reply prompt backend.
5. Moving planning writes from candidate flow into `PlanningCommandService`.
6. Shrinking all of `conversation_pipeline.py`.
```

## Non-Negotiables

```text
1. No deterministic parsing of free user text.
2. No new visible reply strings in `conversation_pending_bridge.py`.
3. No direct `decision.fitmas_message` in pending application.
4. Non-committing pending replies must be composed from `DecisionOutcome`.
5. Applied pending plan patches still need event-backed replies.
6. `decision/` stays pure.
7. `legacy/pending_reply_adapter.py` must not import `conversation_pipeline.py`.
8. `legacy/pending_reply_adapter.py` must not import `fitmas.final_reply` directly.
9. Response modes remain stable for compatibility with existing tests and debug surfaces.
10. Existing dogfood behavior remains stable with all canonical flags off.
```

## File Map

Create:

```text
backend/src/fitmas/legacy/pending_reply_adapter.py
tests/test_phase8h_pending_reply_architecture.py
tests/test_pending_reply_adapter.py
```

Modify:

```text
backend/src/fitmas/legacy/conversation_pending_bridge.py
backend/src/fitmas/decision/reply_composer.py
tests/test_conversation_pending_bridge.py
tests/test_decision_reply_composer.py
docs/DECISION-RUNTIME-REFACTOR.md
docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md
docs/BUILD-ORDER.md
docs/README.md
```

Do not modify unless a failing test proves it necessary:

```text
backend/src/fitmas/llm/decision_legacy.py
backend/src/fitmas/conversation_prompt_modules.py
backend/src/fitmas/final_reply.py
backend/src/fitmas/conversation_pipeline.py
backend/src/fitmas/tools/registry.py
```

## Target Flow

```text
conversation_pending_bridge.apply_pending_resolution(...)
  -> pending state / repo writes
  -> pending_reply_adapter.compose_pending_reply(...)
      -> pending_reply_outcome(...)
      -> DecisionReplyComposer.compose(...)
      -> DecisionOutputVerifier.verify(...)
  -> ConversationTurnOutcome(reply_text=reply_result.text)
```

Accepted pending plan patches stay as-is:

```text
deserialize PlanPatch
-> apply_patch_for_user(...)
-> applied_plan_patch_reply(...)
-> plan_patch_service_result_to_outcome(...)
-> DecisionReplyComposer
```

## Pending Reply Modes

`pending_reply_adapter.py` should expose one enum-like literal:

```python
PendingReplyMode = Literal[
    "rejected",
    "kept",
    "modify_pending",
    "needs_clarification",
    "expired",
    "not_active",
    "choice_needs_selection",
    "choice_invalid_selection",
    "accept_error",
]
```

Mode mapping:

```text
rejected                  -> DecisionOutcome(kind="answer")
kept                      -> DecisionOutcome(kind="plan_pending")
modify_pending            -> DecisionOutcome(kind="plan_pending")
needs_clarification       -> DecisionOutcome(kind="plan_pending")
expired                   -> DecisionOutcome(kind="plan_blocked")
not_active                -> DecisionOutcome(kind="plan_blocked")
choice_needs_selection    -> DecisionOutcome(kind="plan_choice_pending")
choice_invalid_selection  -> DecisionOutcome(kind="plan_choice_pending")
accept_error              -> DecisionOutcome(kind="plan_blocked")
```

Every mode must include:

```text
forbidden_claims=("plan_committed",)
applied_commands=()
candidates from pending summary when available
evidence from pending id, mutation_type, reason, summary
```

---

## Task 1 — Add 8H Architecture Gates

**Files:**

- Create: `tests/test_phase8h_pending_reply_architecture.py`

- [x] **Step 1: Write failing architecture tests**

Create `tests/test_phase8h_pending_reply_architecture.py`:

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


def test_8h_pending_bridge_no_longer_uses_legacy_decision_message_for_visible_reply() -> None:
    source = _source("legacy/conversation_pending_bridge.py")

    assert "pending_reply_adapter" in source
    assert "_decision_reply(" not in source
    assert "fitmas_message" not in source
    assert "La proposition reste en attente" not in source
    assert "Je ne l'applique pas" not in source


def test_8h_pending_reply_adapter_owns_pending_decision_outcomes() -> None:
    source = _source("legacy/pending_reply_adapter.py")
    imports = _imports("legacy/pending_reply_adapter.py")

    assert "PendingReplyMode" in source
    assert "def pending_reply_outcome" in source
    assert "def compose_pending_reply" in source
    assert "DecisionOutcome" in source
    assert "DecisionReplyComposer" in source
    assert "fitmas.conversation_pipeline" not in imports
    assert "fitmas.final_reply" not in imports
    assert "fitmas.llm" not in imports


def test_8h_decision_package_stays_pure() -> None:
    forbidden = {
        "fitmas.legacy",
        "fitmas.llm",
        "fitmas.final_reply",
        "fitmas.conversation_pipeline",
    }
    for path in (SRC / "decision").glob("*.py"):
        imports = _imports(f"decision/{path.name}")
        assert not forbidden.intersection(imports), f"{path.name}: {forbidden.intersection(imports)}"
```

- [x] **Step 2: Run test to verify it fails**

Run:

```bash
./scripts/test-backend -q tests/test_phase8h_pending_reply_architecture.py
```

Expected:

```text
FAIL because `legacy/pending_reply_adapter.py` does not exist and `conversation_pending_bridge.py` still uses `_decision_reply` / `fitmas_message`.
```

---

## Task 2 — Make ReplyComposer Pending Fallback Respect `next_step`

**Files:**

- Modify: `tests/test_decision_reply_composer.py`
- Modify: `backend/src/fitmas/decision/reply_composer.py`

- [x] **Step 1: Write failing fallback tests**

Append to `tests/test_decision_reply_composer.py`:

```python
def test_composer_plan_pending_fallback_uses_next_step() -> None:
    backend = FakeReplyBackend(None)
    composer = DecisionReplyComposer(reply_backend=backend, verifier=DecisionOutputVerifier())
    outcome = _outcome("plan_pending")
    outcome = DecisionOutcome(
        kind=outcome.kind,
        commands=outcome.commands,
        applied_commands=outcome.applied_commands,
        candidates=outcome.candidates,
        selected_candidate_id=outcome.selected_candidate_id,
        explanation=DecisionExplanation(
            decision_label="Proposition gardee",
            reason_summary="La proposition reste en attente.",
            evidence=("pending_id=1",),
            tradeoff=None,
            impact={},
            protected=("coherence semaine",),
            next_step="Dis-moi si tu veux l'appliquer ou la modifier.",
        ),
        reply_contract=outcome.reply_contract,
    )

    result = composer.compose(outcome, context=None, user_text="j'attends")

    assert result.fallback_used is True
    assert result.text == "La proposition reste en attente. Dis-moi si tu veux l'appliquer ou la modifier."


def test_composer_plan_choice_pending_fallback_uses_next_step() -> None:
    backend = FakeReplyBackend(None)
    composer = DecisionReplyComposer(reply_backend=backend, verifier=DecisionOutputVerifier())
    outcome = _outcome("plan_choice_pending")
    outcome = DecisionOutcome(
        kind=outcome.kind,
        commands=outcome.commands,
        applied_commands=outcome.applied_commands,
        candidates=outcome.candidates,
        selected_candidate_id=None,
        explanation=DecisionExplanation(
            decision_label="Choix requis",
            reason_summary="Je ne retrouve pas cette option.",
            evidence=("pending_id=1",),
            tradeoff=None,
            impact={},
            protected=("coherence semaine",),
            next_step="Rechoisis parmi les options proposees.",
        ),
        reply_contract=ReplyContract(
            mode="pending_choice_invalid_selection",
            audience="telegram",
            allowed_claims=("pending_kept",),
            forbidden_claims=("plan_committed",),
        ),
    )

    result = composer.compose(outcome, context=None, user_text="l'autre")

    assert result.fallback_used is True
    assert result.text == "Je ne retrouve pas cette option. Rechoisis parmi les options proposees."
```

- [x] **Step 2: Run test to verify it fails**

Run:

```bash
./scripts/test-backend -q tests/test_decision_reply_composer.py::test_composer_plan_pending_fallback_uses_next_step tests/test_decision_reply_composer.py::test_composer_plan_choice_pending_fallback_uses_next_step
```

Expected:

```text
FAIL because `_fallback_reply()` currently appends generic pending prompts instead of using `next_step`.
```

- [x] **Step 3: Implement minimal fallback change**

Modify `backend/src/fitmas/decision/reply_composer.py`:

```python
    def _fallback_reply(self, request: ReplyRequest) -> str:
        if request.kind == "plan_pending":
            if request.explanation.next_step:
                return f"{request.explanation.reason_summary} {request.explanation.next_step}".strip()
            return f"{request.explanation.reason_summary} Tu confirmes ?"
        if request.kind == "plan_choice_pending":
            if request.explanation.next_step:
                return f"{request.explanation.reason_summary} {request.explanation.next_step}".strip()
            return f"{request.explanation.reason_summary} Tu choisis l'option que tu veux garder ?"
        ...
```

- [x] **Step 4: Run test to verify it passes**

Run:

```bash
./scripts/test-backend -q tests/test_decision_reply_composer.py
```

Expected:

```text
PASS.
```

---

## Task 3 — Add Pending Reply Adapter

**Files:**

- Create: `backend/src/fitmas/legacy/pending_reply_adapter.py`
- Create: `tests/test_pending_reply_adapter.py`

- [x] **Step 1: Write failing adapter tests**

Create `tests/test_pending_reply_adapter.py`:

```python
from __future__ import annotations

from types import SimpleNamespace

from fitmas.decision.reply_request import ReplyResult
from fitmas.legacy.pending_reply_adapter import compose_pending_reply, pending_reply_outcome


class SpyComposer:
    def __init__(self, text: str):
        self.text = text
        self.calls = []

    def compose(self, outcome, context, *, user_text: str = "", grounding_facts: tuple[str, ...] = ()):
        self.calls.append(
            {
                "outcome": outcome,
                "context": context,
                "user_text": user_text,
                "grounding_facts": grounding_facts,
            }
        )
        return ReplyResult(text=self.text, verified=True, fallback_used=False, reason=None)


def _pending():
    return SimpleNamespace(
        id=42,
        mutation_type="plan_patch",
        reason="week_coherence_requires_confirmation",
        summary="deplacer la seance",
        source_text="deplace vendredi",
    )


def test_pending_rejected_outcome_forbids_plan_commit_claims() -> None:
    outcome = pending_reply_outcome(mode="rejected", pending_confirmation=_pending())

    assert outcome.kind == "answer"
    assert outcome.applied_commands == ()
    assert "plan_committed" in outcome.reply_contract.forbidden_claims
    assert "pending_id=42" in outcome.explanation.evidence


def test_pending_kept_outcome_is_plan_pending_with_next_step() -> None:
    outcome = pending_reply_outcome(mode="kept", pending_confirmation=_pending())

    assert outcome.kind == "plan_pending"
    assert outcome.explanation.next_step == "Dis-moi si tu veux l'appliquer ou la modifier."
    assert outcome.reply_contract.mode == "pending_kept"


def test_pending_choice_invalid_outcome_is_plan_choice_pending() -> None:
    outcome = pending_reply_outcome(mode="choice_invalid_selection", pending_confirmation=_pending())

    assert outcome.kind == "plan_choice_pending"
    assert outcome.explanation.next_step == "Rechoisis parmi les options proposees."
    assert outcome.reply_contract.mode == "pending_choice_invalid_selection"


def test_compose_pending_reply_uses_decision_reply_composer() -> None:
    composer = SpyComposer("Composer garde la proposition ouverte.")

    text = compose_pending_reply(
        mode="kept",
        pending_confirmation=_pending(),
        user_text="j'attends",
        decision_reply_composer=composer,
    )

    assert text == "Composer garde la proposition ouverte."
    assert composer.calls[0]["outcome"].kind == "plan_pending"
    assert composer.calls[0]["user_text"] == "j'attends"
```

- [x] **Step 2: Run test to verify it fails**

Run:

```bash
./scripts/test-backend -q tests/test_pending_reply_adapter.py
```

Expected:

```text
FAIL because `fitmas.legacy.pending_reply_adapter` does not exist.
```

- [x] **Step 3: Implement adapter**

Create `backend/src/fitmas/legacy/pending_reply_adapter.py`:

```python
from __future__ import annotations

from typing import Any, Literal, Protocol

from fitmas.decision import DecisionExplanation, DecisionOutcome, DecisionReplyComposer, ReplyContract
from fitmas.decision.reply_request import ReplyResult


PendingReplyMode = Literal[
    "rejected",
    "kept",
    "modify_pending",
    "needs_clarification",
    "expired",
    "not_active",
    "choice_needs_selection",
    "choice_invalid_selection",
    "accept_error",
]


class _ReplyComposerLike(Protocol):
    def compose(
        self,
        outcome: DecisionOutcome,
        context: Any,
        *,
        user_text: str = "",
        grounding_facts: tuple[str, ...] = (),
    ) -> ReplyResult:
        ...


class _NoDraftReplyBackend:
    def compose(self, request) -> str | None:
        return None


def compose_pending_reply(
    *,
    mode: PendingReplyMode,
    pending_confirmation,
    pending_resolution: Any | None = None,
    user_text: str | None = None,
    decision_reply_composer: _ReplyComposerLike | None = None,
) -> str:
    outcome = pending_reply_outcome(
        mode=mode,
        pending_confirmation=pending_confirmation,
        pending_resolution=pending_resolution,
    )
    composer = decision_reply_composer or DecisionReplyComposer(reply_backend=_NoDraftReplyBackend())
    result = composer.compose(outcome, context=None, user_text=str(user_text or ""))
    return result.text or outcome.explanation.reason_summary


def pending_reply_outcome(
    *,
    mode: PendingReplyMode,
    pending_confirmation,
    pending_resolution: Any | None = None,
) -> DecisionOutcome:
    spec = _mode_spec(mode)
    return DecisionOutcome(
        kind=spec["kind"],
        commands=(),
        applied_commands=(),
        candidates=_candidate_summaries(pending_confirmation),
        selected_candidate_id=_selected_candidate_id(pending_resolution),
        explanation=DecisionExplanation(
            decision_label=spec["label"],
            reason_summary=spec["reason"],
            evidence=_evidence(pending_confirmation, pending_resolution),
            tradeoff=None,
            impact={},
            protected=("coherence semaine",),
            next_step=spec["next_step"],
        ),
        reply_contract=ReplyContract(
            mode=f"pending_{mode}",
            audience="telegram",
            allowed_claims=spec["allowed_claims"],
            forbidden_claims=("plan_committed",),
        ),
    )
```

Then add helpers:

```python
def _mode_spec(mode: PendingReplyMode) -> dict[str, Any]:
    return {
        "rejected": {
            "kind": "answer",
            "label": "Proposition refusee",
            "reason": "Je ne l'applique pas. Le planning reste inchangé.",
            "next_step": None,
            "allowed_claims": ("pending_rejected",),
        },
        "kept": {
            "kind": "plan_pending",
            "label": "Proposition gardee",
            "reason": "La proposition reste en attente.",
            "next_step": "Dis-moi si tu veux l'appliquer ou la modifier.",
            "allowed_claims": ("pending_kept",),
        },
        "modify_pending": {
            "kind": "plan_pending",
            "label": "Modification demandee",
            "reason": "La proposition reste en attente.",
            "next_step": "Donne-moi le changement concret et je reprends.",
            "allowed_claims": ("pending_kept",),
        },
        "needs_clarification": {
            "kind": "plan_pending",
            "label": "Clarification requise",
            "reason": "La proposition reste en attente.",
            "next_step": "Dis-moi si tu veux l'appliquer ou la modifier.",
            "allowed_claims": ("pending_kept",),
        },
        "expired": {
            "kind": "plan_blocked",
            "label": "Confirmation expiree",
            "reason": "Cette confirmation n'est plus active. Je ne l'applique pas.",
            "next_step": None,
            "allowed_claims": ("pending_blocked",),
        },
        "not_active": {
            "kind": "plan_blocked",
            "label": "Confirmation inactive",
            "reason": "Cette confirmation n'est plus active. Je ne l'applique pas.",
            "next_step": None,
            "allowed_claims": ("pending_blocked",),
        },
        "choice_needs_selection": {
            "kind": "plan_choice_pending",
            "label": "Choix requis",
            "reason": "Une option doit etre choisie.",
            "next_step": "Choisis une des options proposees.",
            "allowed_claims": ("pending_kept",),
        },
        "choice_invalid_selection": {
            "kind": "plan_choice_pending",
            "label": "Choix introuvable",
            "reason": "Je ne retrouve pas cette option.",
            "next_step": "Rechoisis parmi les options proposees.",
            "allowed_claims": ("pending_kept",),
        },
        "accept_error": {
            "kind": "plan_blocked",
            "label": "Confirmation invalide",
            "reason": "La confirmation en attente n'est plus valide. Je ne l'applique pas.",
            "next_step": None,
            "allowed_claims": ("pending_blocked",),
        },
    }[mode]
```

And helper functions:

```python
def _candidate_summaries(pending_confirmation) -> tuple[str, ...]:
    summary = str(getattr(pending_confirmation, "summary", "") or "").strip()
    return (summary,) if summary else ()


def _selected_candidate_id(pending_resolution: Any | None) -> str | None:
    selected = str(getattr(pending_resolution, "selected_candidate_id", "") or "").strip()
    return selected or None


def _evidence(pending_confirmation, pending_resolution: Any | None) -> tuple[str, ...]:
    evidence: list[str] = []
    pending_id = getattr(pending_confirmation, "id", None)
    if pending_id is not None:
        evidence.append(f"pending_id={pending_id}")
    mutation_type = str(getattr(pending_confirmation, "mutation_type", "") or "").strip()
    if mutation_type:
        evidence.append(f"mutation_type={mutation_type}")
    reason = str(getattr(pending_confirmation, "reason", "") or "").strip()
    if reason:
        evidence.append(f"reason={reason}")
    resolution_type = str(getattr(pending_resolution, "type", "") or "").strip()
    if resolution_type:
        evidence.append(f"resolution={resolution_type}")
    return tuple(evidence)
```

- [x] **Step 4: Run tests to verify adapter passes**

Run:

```bash
./scripts/test-backend -q tests/test_pending_reply_adapter.py
```

Expected:

```text
PASS.
```

---

## Task 4 — Wire Pending Bridge to Adapter

**Files:**

- Modify: `backend/src/fitmas/legacy/conversation_pending_bridge.py`
- Modify: `tests/test_conversation_pending_bridge.py`

- [x] **Step 1: Write failing bridge behavior tests**

Add tests to `tests/test_conversation_pending_bridge.py`:

```python
from fitmas.decision.reply_request import ReplyResult


class _SpyPendingComposer:
    def __init__(self, text: str):
        self.text = text
        self.outcomes = []

    def compose(self, outcome, context, *, user_text: str = "", grounding_facts: tuple[str, ...] = ()):
        self.outcomes.append(outcome)
        return ReplyResult(text=self.text, verified=True, fallback_used=False, reason=None)
```

Then add:

```python
def test_ignore_pending_reply_comes_from_composer_not_legacy_message(self) -> None:
    session = self._scheduled_session()
    pending = self._pending_plan_patch(
        PlanPatch(
            coach_message="Je deplace la seance.",
            operations=(
                PlanPatchOperation(
                    operation_type="move_session",
                    target_session_id=session.id,
                    target_date=(session.scheduled_date.date() + timedelta(days=2)).isoformat(),
                    rationale="Demande a confirmer.",
                ),
            ),
        )
    )
    decision = CoachDecision(
        response_type="reply",
        rationale="ignore pending",
        fitmas_message="LEGACY MESSAGE MUST NOT LEAK",
        pending_resolution=llm.IgnorePendingResolution(type="ignore"),
    )
    composer = _SpyPendingComposer("Composer garde la proposition ouverte.")

    outcome = conversation_pending_bridge.apply_pending_resolution(
        db=self.db,
        user=self.user,
        decision=decision,
        canonical_understanding=None,
        pending_confirmation=pending,
        user_text="j'attends",
        decision_reply_composer=composer,
    )

    assert outcome is not None
    self.assertEqual(outcome.reply_text, "Composer garde la proposition ouverte.")
    self.assertEqual(composer.outcomes[0].kind, "plan_pending")
    self.assertNotIn("LEGACY", outcome.reply_text)
```

Add reject:

```python
def test_reject_pending_reply_comes_from_composer_not_legacy_message(self) -> None:
    session = self._scheduled_session()
    pending = self._pending_plan_patch(
        PlanPatch(
            coach_message="Je reduis la seance.",
            operations=(
                PlanPatchOperation(
                    operation_type="update_session",
                    target_session_id=session.id,
                    new_duration_min=25,
                    rationale="Demande a refuser.",
                ),
            ),
        )
    )
    decision = CoachDecision(
        response_type="reply",
        rationale="reject pending",
        fitmas_message="LEGACY MESSAGE MUST NOT LEAK",
        pending_resolution=llm.RejectPendingResolution(type="reject_pending"),
    )
    composer = _SpyPendingComposer("Composer refuse sans mutation.")

    outcome = conversation_pending_bridge.apply_pending_resolution(
        db=self.db,
        user=self.user,
        decision=decision,
        canonical_understanding=None,
        pending_confirmation=pending,
        user_text="non",
        verify_pending_accept_resolution_fn=lambda **kwargs: "reject_pending",
        decision_reply_composer=composer,
    )

    assert outcome is not None
    self.assertEqual(outcome.response_mode, "pending_rejected")
    self.assertEqual(outcome.reply_text, "Composer refuse sans mutation.")
    self.assertEqual(composer.outcomes[0].kind, "answer")
```

- [x] **Step 2: Run tests to verify they fail**

Run:

```bash
./scripts/test-backend -q tests/test_conversation_pending_bridge.py::ConversationPendingBridgeTest::test_ignore_pending_reply_comes_from_composer_not_legacy_message tests/test_conversation_pending_bridge.py::ConversationPendingBridgeTest::test_reject_pending_reply_comes_from_composer_not_legacy_message
```

Expected:

```text
FAIL because `apply_pending_resolution()` does not accept `decision_reply_composer` and still uses `decision.fitmas_message`.
```

- [x] **Step 3: Modify bridge signatures**

In `backend/src/fitmas/legacy/conversation_pending_bridge.py`, add:

```python
from fitmas.legacy import pending_reply_adapter
```

Change `apply_pending_resolution`:

```python
def apply_pending_resolution(
    *,
    db: Session,
    user: s.User,
    decision: Any,
    canonical_understanding: CoachUnderstanding | None,
    pending_confirmation,
    user_text: str | None = None,
    turn_plan=None,
    verify_pending_accept_resolution_fn: PendingRecheckFn | None = None,
    decision_reply_composer=None,
) -> ConversationTurnOutcome | None:
```

Pass `decision_reply_composer` into all helper calls that create visible pending replies.

- [x] **Step 4: Replace reject / keep / modify / clarification replies**

Use:

```python
reply_text=pending_reply_adapter.compose_pending_reply(
    mode="rejected",
    pending_confirmation=pending_confirmation,
    pending_resolution=resolution,
    user_text=user_text,
    decision_reply_composer=decision_reply_composer,
)
```

For modes:

```text
reject_pending -> "rejected"
ignore -> "kept"
modify_pending -> "modify_pending"
needs_clarification -> "needs_clarification"
```

- [x] **Step 5: Replace recheck mismatch replies**

Change `pending_accept_recheck_blocked_outcome` signature:

```python
def pending_accept_recheck_blocked_outcome(
    *,
    db: Session,
    pending_confirmation,
    verified_resolution_type: str,
    pending_resolution: Any | None = None,
    user_text: str | None = None,
    decision_reply_composer=None,
) -> ConversationTurnOutcome:
```

Map:

```text
verified reject_pending       -> rejected, status rejected
verified modify_pending       -> modify_pending, pending kept
verified needs_clarification  -> needs_clarification, pending kept
verified ignore               -> kept, pending kept
```

- [x] **Step 6: Replace unavailable / choice / error replies**

Change `pending_confirmation_unavailable_outcome`:

```python
def pending_confirmation_unavailable_outcome(
    *,
    db: Session,
    pending_confirmation,
    user_text: str | None = None,
    decision_reply_composer=None,
) -> ConversationTurnOutcome | None:
```

Use:

```text
expired    -> mode="expired"
not active -> mode="not_active"
```

In `accept_pending_plan_patch_choice`:

```text
missing selected_candidate_id -> mode="choice_needs_selection"
invalid selected_candidate_id -> mode="choice_invalid_selection"
```

In exception handler:

```text
mode="accept_error"
```

- [x] **Step 7: Remove `_decision_reply`**

Delete:

```python
def _decision_reply(decision: Any, *, fallback: str) -> str:
    return str(getattr(decision, "fitmas_message", "") or fallback)
```

- [x] **Step 8: Run bridge tests**

Run:

```bash
./scripts/test-backend -q tests/test_conversation_pending_bridge.py
```

Expected:

```text
PASS.
```

---

## Task 5 — Preserve Existing Pending Parity

**Files:**

- Existing: `tests/test_core_flows.py`

- [x] **Step 1: Run pending parity suite**

Run:

```bash
./scripts/test-backend -q tests/test_core_flows.py -k "pending or confirmation"
```

Expected:

```text
All selected tests pass. Response modes remain stable.
```

- [x] **Step 2: Fix only bridge/adapter regressions**

If any test fails:

```text
Fix `legacy/pending_reply_adapter.py` or `legacy/conversation_pending_bridge.py`.
Do not reintroduce direct pending replies in `conversation_pipeline.py`.
Do not modify `llm/decision_legacy.py`.
```

---

## Task 6 — Update Docs

**Files:**

- Modify: `docs/DECISION-RUNTIME-REFACTOR.md`
- Modify: `docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md`
- Modify: `docs/BUILD-ORDER.md`
- Modify: `docs/README.md`

- [x] **Step 1: Add Phase 8H status**

Document:

```text
Phase 8H routes pending reject/ignore/modify/clarification/expired/choice-error replies through DecisionOutcome -> DecisionReplyComposer.
conversation_pending_bridge no longer reads `decision.fitmas_message`.
Accepted/blocked PlanPatch pending replies already used the planning composer and remain unchanged.
```

- [x] **Step 2: Update remaining debt**

Document:

```text
CoachDecision remains provider default.
FITMAS_PENDING_FROM_UNDERSTANDING remains off.
The next work is canonical flag dogfood or further conversation_pipeline shrink.
```

- [x] **Step 3: Run docs list**

Run:

```bash
./scripts/docs:list | rg "8h|DECISION-RUNTIME|BUILD-ORDER|README"
```

Expected:

```text
The 8H plan appears and core docs still list correctly.
```

---

## Task 7 — Verification

Run:

```bash
./scripts/test-backend -q tests/test_phase8h_pending_reply_architecture.py tests/test_pending_reply_adapter.py tests/test_conversation_pending_bridge.py tests/test_decision_reply_composer.py
```

Expected:

```text
PASS.
```

Run:

```bash
./scripts/test-backend -q tests/test_core_flows.py -k "pending or confirmation"
```

Expected:

```text
PASS.
```

Run Phase 8 architecture pack:

```bash
./scripts/test-backend -q tests/test_decision_runtime_architecture.py tests/test_phase8a_legacy_audit.py tests/test_phase8b_cutover_architecture.py tests/test_phase8c_legacy_kill_architecture.py tests/test_phase8d_bridge_shrink_architecture.py tests/test_phase8e_understanding_cutover_architecture.py tests/test_phase8f_command_extraction_architecture.py tests/test_phase8g_pending_resolution_architecture.py tests/test_phase8h_pending_reply_architecture.py
```

Expected:

```text
PASS.
```

Run full backend:

```bash
./scripts/test-backend -q
```

Expected:

```text
PASS.
```

Run smokes:

```bash
./scripts/smoke-a-plus-api --scenario move_easy_then_confirm --timeout 60
./scripts/smoke-a-plus-api --scenario confirm_without_pending --timeout 60
```

Expected:

```text
RESULT: OK for both.
```

## Acceptance

```text
1. `conversation_pending_bridge.py` no longer uses `decision.fitmas_message`.
2. `conversation_pending_bridge.py` no longer owns direct visible pending reply strings.
3. `legacy/pending_reply_adapter.py` converts pending modes to `DecisionOutcome`.
4. Non-committing pending replies pass through `DecisionReplyComposer`.
5. Accepted pending PlanPatch replies remain event-backed.
6. Response modes remain stable.
7. Full backend passes.
8. Pending smokes pass.
```

## Remaining Debt After 8H

```text
1. `CoachDecision` remains provider default.
2. `FITMAS_PENDING_FROM_UNDERSTANDING` remains off by default.
3. `FITMAS_COMMANDS_FROM_UNDERSTANDING` remains off by default.
4. `final_reply.py` remains backend legacy for some composed replies.
5. `conversation_pipeline.py` remains too large and needs the next shrink slice.
6. Services root memory/execution/planning still need final domain relocation.
```

## Recommended Next Slice

After 8H, choose between:

```text
8I — Canonical flag dogfood:
  enable shadow + commands_from_understanding + pending_from_understanding in targeted smokes.

8J — Conversation pipeline shrink:
  extract turn persistence / output guard / adaptation candidate orchestration.
```

Recommendation:

```text
Do 8I before a large shrink. First prove canonical Understanding can carry commands and pending safely under flags.
```
