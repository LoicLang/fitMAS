---
summary: implementation plan for Decision Runtime Phase 5 unique ReplyComposer and OutputVerifier
read_when:
  - implementing Decision Runtime Phase 5
  - routing visible conversation replies through DecisionOutcome
  - replacing direct final_reply calls in conversation_pipeline
  - composing planning runtime replies from committed, pending or blocked outcomes
  - enforcing that ReplyComposer is the only user-visible speech entrypoint
---

# Decision Runtime Phase 5 ReplyComposer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make user-visible conversation text flow through `DecisionOutcome -> ReplyComposer -> OutputVerifier`, starting with planning outcomes and then the existing plan-patch wrappers.

**Architecture:** Keep `fitmas.decision` pure: it defines reply requests, the concrete composer, and verifier, but it does not import `fitmas.final_reply`, DB, legacy contracts, or `PlanPatch`. Existing `final_reply.py` stays as a legacy LLM backend behind `fitmas.legacy.final_reply_backend`. Conversation code may keep wrapper function names temporarily, but wrappers must delegate to the new composer instead of composing text directly.

**Tech Stack:** Python 3.13, dataclasses, Protocols, existing `DecisionOutcome`, existing `final_reply.py` as backend adapter, pytest architecture tests, existing core flow tests.

---

**Status 2026-05-14:** implemented locally. The Phase 5 reply path is in place
for planning runtime and legacy PlanPatch helpers. `FITMAS_PLANNING_RUNTIME_CUTOVER`
remains off by default; unit-level flag-on mapper tests pass. Full backend
verification: `./scripts/test-backend -q` -> 1052 passed, 11 skipped,
11 subtests passed.

## Phase 5 Boundary

Allowed:

- add pure decision reply models and concrete composer/verifier;
- add legacy adapters that convert existing planning/service results into `DecisionOutcome`;
- use existing `final_reply.py` only behind `backend/src/fitmas/legacy/final_reply_backend.py`;
- keep old `conversation_pipeline.py` branch structure while redirecting visible text creation;
- keep `FITMAS_PLANNING_RUNTIME_CUTOVER=1` opt-in until semantic parity is proven.

Forbidden:

- no prompt rewrite beyond legacy backend wiring;
- no new user-text parser;
- no new local guard in `conversation_pipeline.py`;
- no DB writes in composer or verifier;
- no `fitmas.final_reply` import from `fitmas.decision`;
- no visible text composed from `decision.reason`, `PlanPatch.coach_message`, or `CoachDecision.fitmas_message` without going through `ReplyComposer`;
- no enabling the Phase 4 planning cutover by default in this phase.

## Why Phase 5 Is Sensitive

The Phase 4 cutover was correctly guarded because direct routing produced visible and semantic regressions:

- pending replies became bare policy reasons;
- some confirmation paths lost the explicit "Tu confirmes ?" shape;
- blocked planning runtime replies became too generic;
- direct plan-patch legacy behavior still has many local reply helpers.

Phase 5 fixes the visible-output half of that problem. It does **not** delete all legacy planning branches yet. It builds the single reply path, proves it on planning outcomes, then makes old wrappers delegate to it.

## Target File Map

Create or modify:

```text
backend/src/fitmas/decision/
  reply_request.py              pure reply request/result models
  reply_composer.py             protocol + concrete DecisionReplyComposer
  output_verifier.py            protocol + concrete DecisionOutputVerifier

backend/src/fitmas/legacy/
  final_reply_backend.py        only adapter allowed to import final_reply.py
  planning_outcome_adapter.py   PlanningDecisionResult -> DecisionOutcome
  plan_patch_reply_adapter.py   PlanPatchServiceResult -> DecisionOutcome

backend/src/fitmas/conversation_pipeline.py
  keep existing branch shape
  replace visible reply helper internals with ReplyComposer calls

tests/
  test_decision_reply_composer.py
  test_decision_output_verifier.py
  test_legacy_final_reply_backend.py
  test_planning_outcome_adapter.py
  test_plan_patch_reply_adapter.py
  test_conversation_planning_runtime_reply_composer.py
  test_phase5_reply_architecture.py
```

Do not move `backend/src/fitmas/final_reply.py` in this phase. It becomes a backend adapter dependency, then can be simplified in Phase 6.

## Invariants

```text
INVARIANTS FITMAS DECISION RUNTIME - PHASE 5

1. ReplyComposer is the only new entrypoint that produces visible user text.
2. OutputVerifier is the only new entrypoint that validates visible user text.
3. decision/ stays free of final_reply, DB, legacy, PlanPatch and MutationDecision imports.
4. legacy/final_reply_backend.py is the only new file allowed to call final_reply.compose_*.
5. conversation_pipeline.py may keep wrapper names, but wrapper internals must call ReplyComposer.
6. Planning outcomes must include applied event evidence before any action claim is allowed.
7. Pending outcomes must ask for confirmation or choice without claiming commit.
8. Blocked outcomes must explain the block without claiming action.
9. No heartbeat migration in this phase; heartbeat comes in Phase 7.
10. Phase 4 planning cutover remains opt-in until all existing core flows pass with the flag.
```

## Task 1: Reply Request Models

**Files:**
- Create: `backend/src/fitmas/decision/reply_request.py`
- Modify: `backend/src/fitmas/decision/__init__.py`
- Modify: `tests/test_decision_runtime_architecture.py`
- Create: `tests/test_decision_reply_composer.py`

- [ ] **Step 1: Write failing model tests**

Create `tests/test_decision_reply_composer.py`:

```python
from __future__ import annotations

from fitmas.decision import DecisionExplanation, ReplyContract
from fitmas.decision.reply_request import ReplyRequest, ReplyResult


def test_reply_request_carries_machine_truth_not_legacy_objects() -> None:
    request = ReplyRequest(
        kind="plan_pending",
        user_text="deplace demain",
        committed_events=(),
        blocked_reasons=(),
        pending_summary="Deplacer la seance a vendredi.",
        memory_updates=(),
        execution_updates=(),
        candidate_summaries=("move_friday: seance vendredi",),
        explanation=DecisionExplanation(
            decision_label="Changement a confirmer",
            reason_summary="La semaine change sensiblement.",
            evidence=("seance cible resolue",),
            tradeoff="moins de friction",
            impact={"risk": "medium"},
            protected=("coherence semaine",),
            next_step="attendre confirmation",
        ),
        contract=ReplyContract(
            mode="plan_pending",
            audience="telegram",
            allowed_claims=("pending_created",),
            forbidden_claims=("plan_committed",),
        ),
    )

    assert request.kind == "plan_pending"
    assert request.pending_summary == "Deplacer la seance a vendredi."
    assert "PlanPatch" not in repr(request)
    assert "CoachDecision" not in repr(request)


def test_reply_result_knows_if_output_is_verified() -> None:
    result = ReplyResult(text="Tu confirmes ?", verified=True, fallback_used=False, reason=None)

    assert result.text == "Tu confirmes ?"
    assert result.verified is True
```

- [ ] **Step 2: Run and verify failure**

Run:

```bash
./scripts/test-backend tests/test_decision_reply_composer.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'fitmas.decision.reply_request'
```

- [ ] **Step 3: Implement pure models**

Create `backend/src/fitmas/decision/reply_request.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping

from .explanation import DecisionExplanation
from .outcome import ReplyContract


ReplyRequestKind = Literal[
    "answer",
    "clarification",
    "memory_updated",
    "execution_updated",
    "plan_committed",
    "plan_pending",
    "plan_choice_pending",
    "plan_blocked",
    "no_send",
]


@dataclass(frozen=True, slots=True)
class ReplyRequest:
    kind: ReplyRequestKind
    user_text: str
    committed_events: tuple[str, ...]
    blocked_reasons: tuple[str, ...]
    pending_summary: str | None
    memory_updates: tuple[str, ...]
    execution_updates: tuple[str, ...]
    candidate_summaries: tuple[str, ...]
    explanation: DecisionExplanation
    contract: ReplyContract
    grounding_facts: tuple[str, ...] = ()
    metadata: Mapping[str, object] | None = None


@dataclass(frozen=True, slots=True)
class ReplyResult:
    text: str | None
    verified: bool
    fallback_used: bool
    reason: str | None
```

- [ ] **Step 4: Export models**

Modify `backend/src/fitmas/decision/__init__.py`:

```python
from .reply_request import ReplyRequest, ReplyResult
```

Add to `__all__`:

```python
"ReplyRequest",
"ReplyResult",
```

- [ ] **Step 5: Update architecture expectation**

Modify `tests/test_decision_runtime_architecture.py` in `test_decision_runtime_phase1_modules_exist`:

```python
expected = {
    "__init__.py",
    "input_event.py",
    "context.py",
    "understanding.py",
    "explanation.py",
    "outcome.py",
    "command_bus.py",
    "runtime.py",
    "reply_composer.py",
    "reply_request.py",
    "output_verifier.py",
    "context_builder.py",
}
```

Do not add `reply_request.py` to any allowlist that permits legacy imports. It must stay pure.

- [ ] **Step 6: Run tests**

Run:

```bash
./scripts/test-backend tests/test_decision_reply_composer.py tests/test_decision_runtime_architecture.py -q
```

Expected:

```text
all selected tests pass
```

## Task 2: Concrete OutputVerifier

**Files:**
- Modify: `backend/src/fitmas/decision/output_verifier.py`
- Create: `tests/test_decision_output_verifier.py`

- [ ] **Step 1: Write failing verifier tests**

Create `tests/test_decision_output_verifier.py`:

```python
from __future__ import annotations

from fitmas.decision import CommandResult, DecisionExplanation, DecisionOutcome, ReplyContract
from fitmas.decision.output_verifier import DecisionOutputVerifier


def _outcome(kind: str, *, applied: bool) -> DecisionOutcome:
    return DecisionOutcome(
        kind=kind,  # type: ignore[arg-type]
        commands=(),
        applied_commands=(
            CommandResult(
                command_id="cmd_1",
                domain="planning",
                name="move_session",
                status="applied",
                event_id="evt_1",
                payload={"summary": "Footing deplace vendredi."},
            ),
        )
        if applied
        else (),
        candidates=(),
        selected_candidate_id=None,
        explanation=DecisionExplanation(
            decision_label="label",
            reason_summary="reason",
            evidence=(),
            tradeoff=None,
            impact={},
            protected=(),
            next_step=None,
        ),
        reply_contract=ReplyContract(
            mode=kind,
            audience="telegram",
            allowed_claims=("plan_committed",) if applied else (),
            forbidden_claims=() if applied else ("plan_committed",),
        ),
    )


def test_verifier_blocks_action_claim_without_applied_event() -> None:
    result = DecisionOutputVerifier().verify("J'ai deplace la seance a vendredi.", _outcome("plan_pending", applied=False), None)

    assert result.allowed is False
    assert result.reason == "uncommitted_action_claim"


def test_verifier_allows_action_claim_with_applied_event() -> None:
    result = DecisionOutputVerifier().verify("C'est cale vendredi.", _outcome("plan_committed", applied=True), None)

    assert result.allowed is True
    assert result.text == "C'est cale vendredi."


def test_verifier_blocks_internal_jargon() -> None:
    result = DecisionOutputVerifier().verify("Le runtime a cree un patch.", _outcome("plan_blocked", applied=False), None)

    assert result.allowed is False
    assert result.reason == "internal_jargon"
```

- [ ] **Step 2: Run and verify failure**

Run:

```bash
./scripts/test-backend tests/test_decision_output_verifier.py -q
```

Expected:

```text
ImportError: cannot import name 'DecisionOutputVerifier'
```

- [ ] **Step 3: Implement concrete verifier**

Modify `backend/src/fitmas/decision/output_verifier.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from fitmas import coach_voice
from fitmas.claim_guard import looks_like_action_claim

from .context import CoachContext
from .outcome import DecisionOutcome
```

Keep the existing protocol, then add:

```python
class DecisionOutputVerifier:
    def verify(
        self,
        reply: str,
        outcome: DecisionOutcome,
        context: CoachContext | None,
    ) -> VerificationResult:
        text = str(reply or "").strip()
        if not text:
            return VerificationResult(allowed=False, text="", reason="empty_reply")
        if coach_voice.message_has_user_facing_internal_jargon(text):
            return VerificationResult(allowed=False, text=text, reason="internal_jargon")
        if coach_voice.message_violates_coach_voice(text) or coach_voice.message_looks_receipt_style(text):
            return VerificationResult(allowed=False, text=text, reason="voice")
        if _claims_action_without_event(text, outcome):
            return VerificationResult(allowed=False, text=text, reason="uncommitted_action_claim")
        if outcome.kind in {"plan_pending", "plan_choice_pending"} and _claims_done(text):
            return VerificationResult(allowed=False, text=text, reason="pending_claims_done")
        return VerificationResult(allowed=True, text=text, reason=None)


def _claims_action_without_event(text: str, outcome: DecisionOutcome) -> bool:
    if _has_applied_event(outcome):
        return False
    return looks_like_action_claim(text)


def _has_applied_event(outcome: DecisionOutcome) -> bool:
    return any(result.status == "applied" and bool(result.event_id) for result in outcome.applied_commands)


def _claims_done(text: str) -> bool:
    normalized = coach_voice.normalize_for_voice_guard(text)
    return any(fragment in normalized for fragment in ("c est fait", "c'est fait", "c est cale", "c'est cale"))
```

- [ ] **Step 4: Export verifier**

Modify `backend/src/fitmas/decision/__init__.py`:

```python
from .output_verifier import DecisionOutputVerifier, OutputVerifier, VerificationResult
```

Add to `__all__`:

```python
"DecisionOutputVerifier",
```

- [ ] **Step 5: Run tests**

Run:

```bash
./scripts/test-backend tests/test_decision_output_verifier.py tests/test_decision_runtime_architecture.py -q
```

Expected:

```text
all selected tests pass
```

## Task 3: Concrete ReplyComposer With Backend Injection

**Files:**
- Modify: `backend/src/fitmas/decision/reply_composer.py`
- Modify: `tests/test_decision_reply_composer.py`

- [ ] **Step 1: Extend composer tests**

Append to `tests/test_decision_reply_composer.py`:

```python
from fitmas.decision import CommandResult, DecisionOutcome
from fitmas.decision.output_verifier import DecisionOutputVerifier
from fitmas.decision.reply_composer import DecisionReplyComposer


class FakeReplyBackend:
    def __init__(self, text: str | None):
        self.text = text
        self.requests = []

    def compose(self, request):
        self.requests.append(request)
        return self.text


def _outcome(kind: str, *, applied: bool = False) -> DecisionOutcome:
    return DecisionOutcome(
        kind=kind,  # type: ignore[arg-type]
        commands=(),
        applied_commands=(
            CommandResult(
                command_id="cmd_1",
                domain="planning",
                name="move_session",
                status="applied",
                event_id="evt_1",
                payload={"summary": "Footing deplace vendredi."},
            ),
        )
        if applied
        else (),
        candidates=("move_friday: deplacer vendredi",),
        selected_candidate_id="move_friday",
        explanation=DecisionExplanation(
            decision_label="Adaptation planning",
            reason_summary="On protege la coherence.",
            evidence=("session cible resolue",),
            tradeoff="moins de charge demain",
            impact={"weekly_load_delta": "-8%"},
            protected=("recuperation",),
            next_step="confirmer",
        ),
        reply_contract=ReplyContract(
            mode=kind,
            audience="telegram",
            allowed_claims=("plan_committed",) if applied else ("pending_created",),
            forbidden_claims=() if applied else ("plan_committed",),
        ),
    )


def test_composer_builds_pending_request_from_outcome() -> None:
    backend = FakeReplyBackend("Je te propose vendredi. Tu confirmes ?")
    composer = DecisionReplyComposer(reply_backend=backend, verifier=DecisionOutputVerifier())

    result = composer.compose(_outcome("plan_pending"), context=None, user_text="deplace demain")

    assert result.text == "Je te propose vendredi. Tu confirmes ?"
    assert result.verified is True
    assert backend.requests[0].kind == "plan_pending"
    assert backend.requests[0].pending_summary == "On protege la coherence."
    assert backend.requests[0].candidate_summaries == ("move_friday: deplacer vendredi",)


def test_composer_falls_back_to_outcome_explanation_when_backend_fails() -> None:
    backend = FakeReplyBackend(None)
    composer = DecisionReplyComposer(reply_backend=backend, verifier=DecisionOutputVerifier())

    result = composer.compose(_outcome("plan_blocked"), context=None, user_text="force la seance dure")

    assert result.fallback_used is True
    assert result.verified is True
    assert "On protege la coherence" in result.text


def test_composer_rejects_backend_uncommitted_action_claim() -> None:
    backend = FakeReplyBackend("J'ai deplace la seance a vendredi.")
    composer = DecisionReplyComposer(reply_backend=backend, verifier=DecisionOutputVerifier())

    result = composer.compose(_outcome("plan_pending"), context=None, user_text="deplace demain")

    assert result.verified is True
    assert result.fallback_used is True
    assert result.text != "J'ai deplace la seance a vendredi."
```

- [ ] **Step 2: Run and verify failure**

Run:

```bash
./scripts/test-backend tests/test_decision_reply_composer.py -q
```

Expected:

```text
ImportError: cannot import name 'DecisionReplyComposer'
```

- [ ] **Step 3: Implement backend protocol and composer**

Modify `backend/src/fitmas/decision/reply_composer.py`:

```python
from __future__ import annotations

from typing import Protocol

from .context import CoachContext
from .outcome import DecisionOutcome
from .output_verifier import DecisionOutputVerifier, OutputVerifier
from .reply_request import ReplyRequest, ReplyResult
```

Keep the existing `ReplyComposer` protocol, then add:

```python
class ReplyBackend(Protocol):
    def compose(self, request: ReplyRequest) -> str | None:
        ...


class DecisionReplyComposer:
    def __init__(self, *, reply_backend: ReplyBackend, verifier: OutputVerifier | None = None):
        self._reply_backend = reply_backend
        self._verifier = verifier or DecisionOutputVerifier()

    def compose(
        self,
        outcome: DecisionOutcome,
        context: CoachContext | None,
        *,
        user_text: str = "",
        grounding_facts: tuple[str, ...] = (),
    ) -> ReplyResult:
        request = self._request_from_outcome(outcome, user_text=user_text, grounding_facts=grounding_facts)
        drafted = self._reply_backend.compose(request)
        verified = self._verify(drafted, outcome, context)
        if verified.allowed:
            return ReplyResult(text=verified.text, verified=True, fallback_used=False, reason=None)
        fallback = self._fallback_reply(request)
        fallback_verification = self._verify(fallback, outcome, context)
        return ReplyResult(
            text=fallback_verification.text if fallback_verification.allowed else None,
            verified=fallback_verification.allowed,
            fallback_used=True,
            reason=verified.reason,
        )

    def _request_from_outcome(
        self,
        outcome: DecisionOutcome,
        *,
        user_text: str,
        grounding_facts: tuple[str, ...],
    ) -> ReplyRequest:
        return ReplyRequest(
            kind=outcome.kind,
            user_text=user_text,
            committed_events=_committed_event_summaries(outcome),
            blocked_reasons=_blocked_reasons(outcome),
            pending_summary=_pending_summary(outcome),
            memory_updates=_domain_updates(outcome, "memory"),
            execution_updates=_domain_updates(outcome, "execution"),
            candidate_summaries=tuple(str(item) for item in outcome.candidates if str(item).strip()),
            explanation=outcome.explanation,
            contract=outcome.reply_contract,
            grounding_facts=grounding_facts,
            metadata={"selected_candidate_id": outcome.selected_candidate_id} if outcome.selected_candidate_id else None,
        )

    def _verify(self, reply: str | None, outcome: DecisionOutcome, context: CoachContext | None):
        return self._verifier.verify(str(reply or ""), outcome, context)

    def _fallback_reply(self, request: ReplyRequest) -> str:
        if request.kind == "plan_pending":
            return f"{request.explanation.reason_summary} Tu confirmes ?"
        if request.kind == "plan_choice_pending":
            return f"{request.explanation.reason_summary} Tu choisis l'option que tu veux garder ?"
        if request.kind == "plan_committed":
            committed = " ".join(request.committed_events).strip()
            return committed or request.explanation.reason_summary
        if request.kind == "plan_blocked":
            return request.explanation.reason_summary
        if request.kind == "execution_updated" and request.execution_updates:
            return " ".join(request.execution_updates)
        if request.kind == "memory_updated":
            return request.explanation.reason_summary
        if request.kind == "clarification":
            return request.explanation.next_step or request.explanation.reason_summary
        return request.explanation.reason_summary


def _committed_event_summaries(outcome: DecisionOutcome) -> tuple[str, ...]:
    summaries: list[str] = []
    for result in outcome.applied_commands:
        if result.status != "applied":
            continue
        summary = str(result.payload.get("summary") or result.payload.get("user_visible_summary") or "").strip()
        if summary:
            summaries.append(summary)
    return tuple(summaries)


def _blocked_reasons(outcome: DecisionOutcome) -> tuple[str, ...]:
    reasons: list[str] = []
    for result in outcome.applied_commands:
        if result.status != "blocked":
            continue
        reason = str(result.payload.get("reason") or "").strip()
        if reason:
            reasons.append(reason)
    if outcome.kind == "plan_blocked" and not reasons:
        reasons.append(outcome.explanation.reason_summary)
    return tuple(reasons)


def _pending_summary(outcome: DecisionOutcome) -> str | None:
    if outcome.kind in {"plan_pending", "plan_choice_pending"}:
        return outcome.explanation.reason_summary
    return None


def _domain_updates(outcome: DecisionOutcome, domain: str) -> tuple[str, ...]:
    updates: list[str] = []
    for result in outcome.applied_commands:
        if result.domain != domain or result.status != "applied":
            continue
        summary = str(result.payload.get("summary") or "").strip()
        if summary:
            updates.append(summary)
    return tuple(updates)
```

- [ ] **Step 4: Export composer**

Modify `backend/src/fitmas/decision/__init__.py`:

```python
from .reply_composer import DecisionReplyComposer, ReplyBackend, ReplyComposer
```

Add to `__all__`:

```python
"DecisionReplyComposer",
"ReplyBackend",
```

- [ ] **Step 5: Run tests**

Run:

```bash
./scripts/test-backend tests/test_decision_reply_composer.py tests/test_decision_output_verifier.py tests/test_decision_runtime_architecture.py -q
```

Expected:

```text
all selected tests pass
```

## Task 4: Legacy Final Reply Backend

**Files:**
- Create: `backend/src/fitmas/legacy/final_reply_backend.py`
- Modify: `tests/test_decision_runtime_architecture.py`
- Create: `tests/test_legacy_final_reply_backend.py`

- [ ] **Step 1: Write backend tests**

Create `tests/test_legacy_final_reply_backend.py`:

```python
from __future__ import annotations

from fitmas.decision import DecisionExplanation, ReplyContract
from fitmas.decision.reply_request import ReplyRequest
from fitmas.legacy.final_reply_backend import LegacyFinalReplyBackend


def _request(kind: str) -> ReplyRequest:
    return ReplyRequest(
        kind=kind,  # type: ignore[arg-type]
        user_text="deplace la seance",
        committed_events=("Footing deplace vendredi.",) if kind == "plan_committed" else (),
        blocked_reasons=("Aucune option valide.",) if kind == "plan_blocked" else (),
        pending_summary="Option possible, confirmation recommandee." if kind == "plan_pending" else None,
        memory_updates=(),
        execution_updates=(),
        candidate_summaries=("move_friday: deplacer vendredi",),
        explanation=DecisionExplanation(
            decision_label="label",
            reason_summary="reason",
            evidence=(),
            tradeoff=None,
            impact={},
            protected=(),
            next_step=None,
        ),
        contract=ReplyContract(mode=kind, audience="telegram", allowed_claims=(), forbidden_claims=()),
    )


def test_backend_uses_plan_adaptation_reply_for_pending() -> None:
    calls = []

    def fake_request_text(**kwargs):
        calls.append(kwargs["prompt"])
        if "Reponse sortante a verifier:" in kwargs["prompt"]:
            return '{"verdict":"allow","reason":"pending ok","repaired_reply":""}'
        return "Je te propose vendredi. Tu confirmes ?"

    reply = LegacyFinalReplyBackend(request_text_fn=fake_request_text, verifier_text_fn=fake_request_text).compose(
        _request("plan_pending")
    )

    assert reply == "Je te propose vendredi. Tu confirmes ?"
    assert any("Confirmation en attente" in prompt for prompt in calls)


def test_backend_uses_committed_events_for_commit() -> None:
    def fake_request_text(**kwargs):
        if "Reponse sortante a verifier:" in kwargs["prompt"]:
            return '{"verdict":"allow","reason":"event ok","repaired_reply":""}'
        return "C'est cale vendredi."

    reply = LegacyFinalReplyBackend(request_text_fn=fake_request_text, verifier_text_fn=fake_request_text).compose(
        _request("plan_committed")
    )

    assert reply == "C'est cale vendredi."
```

- [ ] **Step 2: Run and verify failure**

Run:

```bash
./scripts/test-backend tests/test_legacy_final_reply_backend.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'fitmas.legacy.final_reply_backend'
```

- [ ] **Step 3: Implement backend adapter**

Create `backend/src/fitmas/legacy/final_reply_backend.py`:

```python
from __future__ import annotations

from fitmas import final_reply
from fitmas.decision.reply_request import ReplyRequest
from fitmas.plan_patch_adaptation_policy import AdaptationPolicyDecision


class LegacyFinalReplyBackend:
    def __init__(self, *, request_text_fn=final_reply.request_text, verifier_text_fn=final_reply.request_text):
        self._request_text_fn = request_text_fn
        self._verifier_text_fn = verifier_text_fn

    def compose(self, request: ReplyRequest) -> str | None:
        if request.kind in {"plan_committed", "plan_pending", "plan_choice_pending", "plan_blocked"}:
            return self._compose_plan(request)
        context = self._context_from_request(request)
        return final_reply.compose_final_reply(context, request_text_fn=self._request_text_fn, force=True)

    def _compose_plan(self, request: ReplyRequest) -> str | None:
        policy_decision = _policy_decision_from_request(request)
        return final_reply.compose_plan_adaptation_reply(
            policy_decision=policy_decision,
            user_text=request.user_text,
            committed_events=request.committed_events,
            candidate_summaries=request.candidate_summaries,
            extra_facts=(
                *request.grounding_facts,
                f"Decision: {request.explanation.decision_label}",
                f"Raison: {request.explanation.reason_summary}",
            ),
            request_text_fn=self._request_text_fn,
            verifier_text_fn=self._verifier_text_fn,
        )

    def _context_from_request(self, request: ReplyRequest) -> final_reply.FinalReplyContext:
        return final_reply.FinalReplyContext(
            user_text=request.user_text,
            committed_events=request.committed_events,
            blocked_events=tuple(
                final_reply.BlockedEvent(command=request.kind, reason=reason)
                for reason in request.blocked_reasons
            ),
            pending_summary=request.pending_summary,
            memory_actions_applied=request.memory_updates,
            execution_actions_applied=request.execution_updates,
            allowed_to_claim_mutation=bool(request.committed_events),
            pipeline="conversation",
            pipeline_capability=request.kind,
            extra_facts=(
                *request.grounding_facts,
                f"Decision: {request.explanation.decision_label}",
                f"Raison: {request.explanation.reason_summary}",
            ),
        )


def _policy_decision_from_request(request: ReplyRequest) -> AdaptationPolicyDecision:
    action = {
        "plan_committed": "commit",
        "plan_pending": "pending_confirmation",
        "plan_choice_pending": "pending_choice",
        "plan_blocked": "block",
    }[request.kind]
    return AdaptationPolicyDecision(
        action=action,  # type: ignore[arg-type]
        selected_candidate_id=str((request.metadata or {}).get("selected_candidate_id") or "") or None,
        candidate_options=tuple(request.candidate_summaries),
        reason=request.explanation.reason_summary,
        user_facing_reason=request.explanation.reason_summary,
        requires_confirmation_reason=request.pending_summary,
        risk_level="low" if action == "commit" else "medium" if action != "block" else "high",  # type: ignore[arg-type]
    )
```

- [ ] **Step 4: Update architecture tests**

Modify `tests/test_decision_runtime_architecture.py` so `test_legacy_understanding_adapter_is_only_legacy_module_importing_llm_contracts` allows the new backend to import `fitmas.final_reply` but not `fitmas.llm` or `fitmas.plan_patch`:

```python
allowed_final_reply_imports = {
    legacy / "final_reply_backend.py",
}
```

Then assert any `fitmas.final_reply` offender outside that set fails.

- [ ] **Step 5: Run tests**

Run:

```bash
./scripts/test-backend tests/test_legacy_final_reply_backend.py tests/test_decision_runtime_architecture.py -q
```

Expected:

```text
all selected tests pass
```

## Task 5: Planning Outcome Adapter

**Files:**
- Create: `backend/src/fitmas/legacy/planning_outcome_adapter.py`
- Create: `tests/test_planning_outcome_adapter.py`

- [ ] **Step 1: Write adapter tests**

Create `tests/test_planning_outcome_adapter.py`:

```python
from __future__ import annotations

from types import SimpleNamespace

from fitmas.domain.planning.models import PlanningCommandResult, PlanningDecisionResult
from fitmas.legacy.planning_outcome_adapter import planning_decision_to_outcome


def _decision(kind: str, *, command_result: PlanningCommandResult | None = None) -> PlanningDecisionResult:
    return PlanningDecisionResult(
        kind=kind,  # type: ignore[arg-type]
        selected_candidate_id="cand_1",
        candidate_options=("cand_1", "cand_2") if kind == "pending_choice" else (),
        reason="Option possible, confirmation recommandee.",
        policy_decision=SimpleNamespace(risk_level="medium"),
        selected_patch=None,
        evaluated_candidates=(SimpleNamespace(candidate=SimpleNamespace(id="cand_1", rationale="move friday")),),
        command_result=command_result,
        pending_confirmation_id=44 if kind.startswith("pending") else None,
    )


def test_adapter_maps_commit_to_plan_committed_outcome() -> None:
    outcome = planning_decision_to_outcome(
        _decision(
            "commit",
            command_result=PlanningCommandResult(
                status="applied",
                event_count=1,
                pending_confirmation_id=None,
                service_result=None,
                payload={"summary": "Footing deplace vendredi.", "event_id": "evt_1"},
            ),
        )
    )

    assert outcome.kind == "plan_committed"
    assert outcome.applied_commands[0].event_id == "evt_1"
    assert outcome.reply_contract.allowed_claims == ("plan_committed",)


def test_adapter_maps_pending_choice_to_plan_choice_pending() -> None:
    outcome = planning_decision_to_outcome(
        _decision(
            "pending_choice",
            command_result=PlanningCommandResult(
                status="pending",
                event_count=0,
                pending_confirmation_id=44,
                service_result=None,
                payload={"candidate_options": ("cand_1", "cand_2")},
            ),
        )
    )

    assert outcome.kind == "plan_choice_pending"
    assert outcome.reply_contract.forbidden_claims == ("plan_committed",)
    assert outcome.explanation.next_step == "await_user_choice"


def test_adapter_maps_block_to_plan_blocked_without_applied_commands() -> None:
    outcome = planning_decision_to_outcome(_decision("block"))

    assert outcome.kind == "plan_blocked"
    assert outcome.applied_commands == ()
    assert outcome.explanation.reason_summary == "Option possible, confirmation recommandee."
```

- [ ] **Step 2: Run and verify failure**

Run:

```bash
./scripts/test-backend tests/test_planning_outcome_adapter.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'fitmas.legacy.planning_outcome_adapter'
```

- [ ] **Step 3: Implement adapter**

Create `backend/src/fitmas/legacy/planning_outcome_adapter.py`:

```python
from __future__ import annotations

from typing import Any

from fitmas.decision import CommandResult, DecisionExplanation, DecisionOutcome, ReplyContract
from fitmas.domain.planning.models import PlanningDecisionResult


def planning_decision_to_outcome(decision: PlanningDecisionResult) -> DecisionOutcome:
    kind = _outcome_kind(decision)
    return DecisionOutcome(
        kind=kind,
        commands=(),
        applied_commands=_command_results(decision),
        candidates=_candidate_summaries(decision),
        selected_candidate_id=decision.selected_candidate_id,
        explanation=DecisionExplanation(
            decision_label=_decision_label(kind),
            reason_summary=decision.reason,
            evidence=_evidence(decision),
            tradeoff=None,
            impact=_impact(decision),
            protected=_protected(kind),
            next_step=_next_step(kind),
        ),
        reply_contract=ReplyContract(
            mode=kind,
            audience="telegram",
            allowed_claims=("plan_committed",) if kind == "plan_committed" else ("pending_created",) if "pending" in kind else (),
            forbidden_claims=() if kind == "plan_committed" else ("plan_committed",),
        ),
    )


def _outcome_kind(decision: PlanningDecisionResult):
    return {
        "commit": "plan_committed",
        "pending_confirmation": "plan_pending",
        "pending_choice": "plan_choice_pending",
        "block": "plan_blocked",
    }[decision.kind]


def _command_results(decision: PlanningDecisionResult) -> tuple[CommandResult, ...]:
    result = decision.command_result
    if result is None:
        return ()
    if result.status == "applied":
        return (
            CommandResult(
                command_id=f"planning:{decision.selected_candidate_id or 'selected'}",
                domain="planning",
                name="plan_change",
                status="applied",
                event_id=str(result.payload.get("event_id") or "planning_event"),
                payload=result.payload,
            ),
        )
    return ()


def _candidate_summaries(decision: PlanningDecisionResult) -> tuple[str, ...]:
    summaries: list[str] = []
    for evaluated in decision.evaluated_candidates:
        candidate = getattr(evaluated, "candidate", None)
        candidate_id = str(getattr(candidate, "id", "") or "").strip()
        rationale = str(getattr(candidate, "rationale", "") or "").strip()
        if candidate_id or rationale:
            summaries.append(": ".join(bit for bit in (candidate_id, rationale) if bit))
    return tuple(summaries or decision.candidate_options)


def _decision_label(kind: str) -> str:
    return {
        "plan_committed": "Adaptation appliquee",
        "plan_pending": "Adaptation a confirmer",
        "plan_choice_pending": "Choix d'adaptation a confirmer",
        "plan_blocked": "Adaptation bloquee",
    }[kind]


def _evidence(decision: PlanningDecisionResult) -> tuple[str, ...]:
    items = [f"policy={decision.kind}"]
    if decision.selected_candidate_id:
        items.append(f"selected_candidate_id={decision.selected_candidate_id}")
    if decision.pending_confirmation_id is not None:
        items.append(f"pending_confirmation_id={decision.pending_confirmation_id}")
    return tuple(items)


def _impact(decision: PlanningDecisionResult) -> dict[str, Any]:
    payload = dict(getattr(decision.command_result, "payload", {}) or {})
    if decision.pending_confirmation_id is not None:
        payload["pending_confirmation_id"] = decision.pending_confirmation_id
    return payload


def _protected(kind: str) -> tuple[str, ...]:
    if kind == "plan_blocked":
        return ("coherence semaine", "risque sportif")
    if "pending" in kind:
        return ("confirmation utilisateur", "coherence semaine")
    return ("verite planning",)


def _next_step(kind: str) -> str | None:
    if kind == "plan_pending":
        return "await_user_confirmation"
    if kind == "plan_choice_pending":
        return "await_user_choice"
    return None
```

- [ ] **Step 4: Run tests**

Run:

```bash
./scripts/test-backend tests/test_planning_outcome_adapter.py -q
```

Expected:

```text
all selected tests pass
```

## Task 6: Conversation Planning Runtime Uses ReplyComposer

**Files:**
- Modify: `backend/src/fitmas/conversation_pipeline.py`
- Create: `tests/test_conversation_planning_runtime_reply_composer.py`

- [ ] **Step 1: Write conversation mapper tests**

Create `tests/test_conversation_planning_runtime_reply_composer.py`:

```python
from __future__ import annotations

from types import SimpleNamespace

from fitmas import conversation_pipeline
from fitmas.decision.reply_request import ReplyResult
from fitmas.domain.planning.models import PlanningCommandResult, PlanningDecisionResult


def _planning_result(kind: str) -> PlanningDecisionResult:
    return PlanningDecisionResult(
        kind=kind,  # type: ignore[arg-type]
        selected_candidate_id="cand_1",
        candidate_options=(),
        reason="Option possible, confirmation recommandee.",
        policy_decision=None,
        selected_patch=None,
        evaluated_candidates=(),
        command_result=PlanningCommandResult(
            status="pending" if kind.startswith("pending") else "blocked",
            event_count=0,
            pending_confirmation_id=55 if kind.startswith("pending") else None,
            service_result=None,
            payload={"reason": "Option possible, confirmation recommandee."},
        ),
        pending_confirmation_id=55 if kind.startswith("pending") else None,
    )


def test_planning_runtime_mapper_uses_reply_composer(monkeypatch) -> None:
    calls = []

    class FakeComposer:
        def compose(self, outcome, context, *, user_text="", grounding_facts=()):
            calls.append((outcome, user_text))
            return ReplyResult(text="Je te propose vendredi. Tu confirmes ?", verified=True, fallback_used=False, reason=None)

    monkeypatch.setattr(conversation_pipeline, "_decision_reply_composer", lambda: FakeComposer())

    outcome = conversation_pipeline._conversation_outcome_from_planning_runtime_result(
        _planning_result("pending_confirmation"),
        user_text="deplace demain",
        grounding_facts=("date locale: 2026-05-14",),
    )

    assert calls
    assert calls[0][0].kind == "plan_pending"
    assert outcome.reply_text == "Je te propose vendredi. Tu confirmes ?"
    assert outcome.pending_confirmation is True
    assert outcome.pending_confirmation_id == 55
```

- [ ] **Step 2: Run and verify failure**

Run:

```bash
./scripts/test-backend tests/test_conversation_planning_runtime_reply_composer.py -q
```

Expected:

```text
TypeError or AttributeError from old mapper signature/body
```

- [ ] **Step 3: Add composer factory in conversation pipeline**

Modify `backend/src/fitmas/conversation_pipeline.py` imports:

```python
from fitmas.decision import DecisionReplyComposer
from fitmas.legacy.final_reply_backend import LegacyFinalReplyBackend
from fitmas.legacy.planning_outcome_adapter import planning_decision_to_outcome
```

Add helper:

```python
def _decision_reply_composer() -> DecisionReplyComposer:
    return DecisionReplyComposer(reply_backend=LegacyFinalReplyBackend())
```

- [ ] **Step 4: Replace planning runtime mapper internals**

Change `_conversation_outcome_from_planning_runtime_result` signature:

```python
def _conversation_outcome_from_planning_runtime_result(
    result,
    *,
    user_text: str = "",
    grounding_facts: tuple[str, ...] = (),
) -> ConversationTurnOutcome:
```

Replace its body:

```python
    decision_outcome = planning_decision_to_outcome(result)
    reply_result = _decision_reply_composer().compose(
        decision_outcome,
        context=None,
        user_text=user_text,
        grounding_facts=grounding_facts,
    )
    reply_text = reply_result.text or decision_outcome.explanation.reason_summary
    pending = decision_outcome.kind in {"plan_pending", "plan_choice_pending"}
    return ConversationTurnOutcome(
        extraction=Extraction(confidence=0.85),
        reply_text=reply_text,
        response_mode=f"planning_runtime_{result.kind}",
        mutation_applied=decision_outcome.kind == "plan_committed",
        pending_confirmation=pending,
        pending_confirmation_id=getattr(result, "pending_confirmation_id", None),
    )
```

Update the call site:

```python
outcome = _conversation_outcome_from_planning_runtime_result(
    planning_runtime_result,
    user_text=payload.text,
    grounding_facts=render_grounding_packet_for_prompt(grounding_packet),
)
```

- [ ] **Step 5: Run tests**

Run:

```bash
./scripts/test-backend tests/test_conversation_planning_runtime_reply_composer.py tests/test_conversation_planning_runtime_adapter.py -q
```

Expected:

```text
all selected tests pass
```

## Task 7: PlanPatch Service Result Adapter

**Files:**
- Create: `backend/src/fitmas/legacy/plan_patch_reply_adapter.py`
- Create: `tests/test_plan_patch_reply_adapter.py`

- [ ] **Step 1: Write adapter tests**

Create `tests/test_plan_patch_reply_adapter.py`:

```python
from __future__ import annotations

from types import SimpleNamespace

from fitmas.legacy.plan_patch_reply_adapter import plan_patch_service_result_to_outcome
from fitmas.plan_patch import PlanPatch, PlanPatchOperation, PlanPatchOperationValidation, PlanPatchValidation
from fitmas.plan_mutation_service import PlanPatchServiceResult


def _patch() -> PlanPatch:
    return PlanPatch(
        coach_message="Je deplace la seance.",
        operations=[
            PlanPatchOperation(operation_type="move_session", target_session_id=42, target_date="2026-05-15", rationale="move")
        ],
    )


def test_adapter_maps_applied_service_result_to_committed_outcome() -> None:
    service_result = PlanPatchServiceResult(
        validation=PlanPatchValidation(status="valid", operation_results=(), summary="valid"),
        patch=_patch(),
        mutation_result=SimpleNamespace(
            applied_events=(SimpleNamespace(user_visible_summary="Footing deplace vendredi.", id=123),),
            blocked_events=(),
        ),
    )

    outcome = plan_patch_service_result_to_outcome(service_result, mode="applied")

    assert outcome.kind == "plan_committed"
    assert outcome.applied_commands[0].payload["summary"] == "Footing deplace vendredi."


def test_adapter_maps_requires_confirmation_to_pending_outcome() -> None:
    service_result = PlanPatchServiceResult(
        validation=PlanPatchValidation(
            status="requires_confirmation",
            operation_results=(
                PlanPatchOperationValidation(
                    operation_type="move_session",
                    status="requires_confirmation",
                    warning_messages=("Ce changement modifie la semaine.",),
                ),
            ),
            summary="confirm",
        ),
        patch=_patch(),
    )

    outcome = plan_patch_service_result_to_outcome(service_result, mode="pending")

    assert outcome.kind == "plan_pending"
    assert outcome.reply_contract.forbidden_claims == ("plan_committed",)
    assert "Ce changement modifie la semaine." in outcome.explanation.reason_summary
```

- [ ] **Step 2: Run and verify failure**

Run:

```bash
./scripts/test-backend tests/test_plan_patch_reply_adapter.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'fitmas.legacy.plan_patch_reply_adapter'
```

- [ ] **Step 3: Implement adapter**

Create `backend/src/fitmas/legacy/plan_patch_reply_adapter.py`:

```python
from __future__ import annotations

from typing import Literal

from fitmas.decision import CommandResult, DecisionExplanation, DecisionOutcome, ReplyContract
from fitmas.plan_mutation_service import PlanPatchServiceResult


PlanPatchReplyMode = Literal["applied", "pending", "blocked", "clarification"]


def plan_patch_service_result_to_outcome(
    service_result: PlanPatchServiceResult | None,
    *,
    mode: PlanPatchReplyMode,
) -> DecisionOutcome:
    kind = _kind(mode)
    return DecisionOutcome(
        kind=kind,
        commands=(),
        applied_commands=_applied_commands(service_result) if kind == "plan_committed" else (),
        candidates=_operation_summaries(service_result),
        selected_candidate_id=None,
        explanation=DecisionExplanation(
            decision_label=_label(kind),
            reason_summary=_reason_summary(service_result, mode=mode),
            evidence=_operation_summaries(service_result),
            tradeoff=None,
            impact={},
            protected=("verite planning",) if kind == "plan_committed" else ("coherence semaine",),
            next_step="await_user_confirmation" if kind == "plan_pending" else None,
        ),
        reply_contract=ReplyContract(
            mode=kind,
            audience="telegram",
            allowed_claims=("plan_committed",) if kind == "plan_committed" else ("pending_created",) if kind == "plan_pending" else (),
            forbidden_claims=() if kind == "plan_committed" else ("plan_committed",),
        ),
    )


def _kind(mode: PlanPatchReplyMode):
    return {
        "applied": "plan_committed",
        "pending": "plan_pending",
        "blocked": "plan_blocked",
        "clarification": "clarification",
    }[mode]


def _applied_commands(service_result: PlanPatchServiceResult | None) -> tuple[CommandResult, ...]:
    mutation_result = getattr(service_result, "mutation_result", None)
    events = tuple(getattr(mutation_result, "applied_events", ()) or ())
    results: list[CommandResult] = []
    for index, event in enumerate(events, start=1):
        summary = str(getattr(event, "user_visible_summary", "") or "").strip()
        results.append(
            CommandResult(
                command_id=f"plan_patch:{index}",
                domain="planning",
                name=str(getattr(event, "command_type", "") or "plan_patch"),
                status="applied",
                event_id=str(getattr(event, "id", "") or f"plan_patch_event_{index}"),
                payload={"summary": summary},
            )
        )
    return tuple(results)


def _reason_summary(service_result: PlanPatchServiceResult | None, *, mode: PlanPatchReplyMode) -> str:
    if service_result is None:
        return "Changement planning traite."
    for result in service_result.validation.operation_results:
        if result.warning_messages:
            return str(result.warning_messages[0])
        if result.block_reason:
            return str(result.block_reason)
    summary = str(service_result.validation.summary or "").strip()
    if summary:
        return summary
    return "Changement planning traite."


def _operation_summaries(service_result: PlanPatchServiceResult | None) -> tuple[str, ...]:
    patch = getattr(service_result, "patch", None)
    if patch is None:
        return ()
    summaries: list[str] = []
    for operation in patch.operations:
        bits = [operation.operation_type]
        if operation.target_session_id is not None:
            bits.append(f"target_session_id={operation.target_session_id}")
        if operation.target_date:
            bits.append(f"target_date={operation.target_date}")
        if operation.new_sport_type:
            bits.append(f"new_sport_type={operation.new_sport_type}")
        summaries.append(" | ".join(bits))
    return tuple(summaries)


def _label(kind: str) -> str:
    return {
        "plan_committed": "Adaptation appliquee",
        "plan_pending": "Adaptation a confirmer",
        "plan_blocked": "Adaptation bloquee",
        "clarification": "Clarification requise",
    }[kind]
```

- [ ] **Step 4: Run tests**

Run:

```bash
./scripts/test-backend tests/test_plan_patch_reply_adapter.py -q
```

Expected:

```text
all selected tests pass
```

## Task 8: Legacy PlanPatch Helpers Delegate To ReplyComposer

**Files:**
- Modify: `backend/src/fitmas/conversation_pipeline.py`
- Modify: `tests/test_final_reply.py`
- Modify: `tests/test_plan_adaptation_final_reply.py`

- [ ] **Step 1: Add helper-level regression tests**

Create or extend a focused test file if direct helper tests already exist:

```python
def test_plan_patch_pending_helper_uses_decision_reply_composer(monkeypatch):
    # Use monkeypatch on conversation_pipeline._decision_reply_composer.
    # Call _build_plan_patch_confirmation_prompt(service_result).
    # Assert composer receives DecisionOutcome(kind="plan_pending").
```

Concrete expected assertions:

```python
assert captured_outcome.kind == "plan_pending"
assert reply == "Je te propose ce changement. Tu confirmes ?"
```

- [ ] **Step 2: Replace `_applied_plan_patch_reply` internals**

In `backend/src/fitmas/conversation_pipeline.py`, import:

```python
from fitmas.legacy.plan_patch_reply_adapter import plan_patch_service_result_to_outcome
```

Change `_applied_plan_patch_reply` to:

```python
def _applied_plan_patch_reply(service_result: PlanPatchServiceResult | None, *, fallback: str) -> str:
    outcome = plan_patch_service_result_to_outcome(service_result, mode="applied")
    reply_result = _decision_reply_composer().compose(outcome, context=None)
    if reply_result.text:
        return reply_result.text
    committed = " ".join(str(result.payload.get("summary") or "") for result in outcome.applied_commands).strip()
    return committed or fallback
```

Keep `_post_event_reply_matches_plan_patch_result` in place until tests prove it is redundant. Do not delete old helper functions in this task.

- [ ] **Step 3: Replace `_blocked_plan_patch_reply` internals**

Change `_blocked_plan_patch_reply` to:

```python
def _blocked_plan_patch_reply(service_result: PlanPatchServiceResult | None) -> str:
    outcome = plan_patch_service_result_to_outcome(service_result, mode="blocked")
    reply_result = _decision_reply_composer().compose(outcome, context=None)
    return reply_result.text or outcome.explanation.reason_summary
```

- [ ] **Step 4: Replace `_build_plan_patch_confirmation_prompt` internals**

Change `_build_plan_patch_confirmation_prompt` to:

```python
def _build_plan_patch_confirmation_prompt(
    service_result: PlanPatchServiceResult | None,
    *,
    grounding: ReplyGroundingPacket | None = None,
) -> str:
    outcome = plan_patch_service_result_to_outcome(service_result, mode="pending")
    reply_result = _decision_reply_composer().compose(
        outcome,
        context=None,
        grounding_facts=render_grounding_packet_for_prompt(grounding),
    )
    return reply_result.text or f"{outcome.explanation.reason_summary} Tu confirmes ?"
```

- [ ] **Step 5: Run focused reply tests**

Run:

```bash
./scripts/test-backend tests/test_final_reply.py tests/test_plan_adaptation_final_reply.py tests/test_core_flows.py -q
```

Expected:

```text
all selected tests pass
```

If `tests/test_core_flows.py` fails because exact wording changed, do not weaken semantic assertions. Adjust the composer backend so replies still include required confirmation markers, committed event truth, or blocked reason.

## Task 9: Architecture Tests For Single Visible Planning Reply Path

**Files:**
- Create: `tests/test_phase5_reply_architecture.py`
- Modify: `tests/test_decision_runtime_architecture.py`

- [ ] **Step 1: Write architecture tests**

Create `tests/test_phase5_reply_architecture.py`:

```python
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FITMAS = ROOT / "backend" / "src" / "fitmas"
DECISION = FITMAS / "decision"
LEGACY = FITMAS / "legacy"
CONVERSATION = FITMAS / "conversation_pipeline.py"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_decision_reply_modules_do_not_import_legacy_final_reply() -> None:
    offenders = []
    for path in sorted(DECISION.glob("*.py")):
        imports = _imports(path)
        if "fitmas.final_reply" in imports or "fitmas.legacy" in imports:
            offenders.append(path.name)

    assert offenders == []


def test_only_legacy_final_reply_backend_imports_final_reply_for_new_phase5_path() -> None:
    offenders = []
    for path in sorted(LEGACY.glob("*.py")):
        imports = _imports(path)
        if "fitmas.final_reply" in imports and path.name != "final_reply_backend.py":
            offenders.append(path.name)

    assert offenders == []


def test_conversation_planning_runtime_mapper_uses_reply_composer() -> None:
    source = CONVERSATION.read_text(encoding="utf-8")
    assert "_decision_reply_composer().compose" in source
    assert "planning_runtime_block" in source
```

- [ ] **Step 2: Run architecture tests**

Run:

```bash
./scripts/test-backend tests/test_phase5_reply_architecture.py tests/test_decision_runtime_architecture.py -q
```

Expected:

```text
all selected tests pass
```

## Task 10: Cutover Flag Guard Tests

**Files:**
- Modify: `tests/test_conversation_planning_runtime_reply_composer.py`

- [ ] **Step 1: Add cutover flag tests**

Append to `tests/test_conversation_planning_runtime_reply_composer.py`:

```python
def test_planning_runtime_cutover_is_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("FITMAS_PLANNING_RUNTIME_CUTOVER", raising=False)

    assert conversation_pipeline._planning_runtime_cutover_enabled() is False


def test_planning_runtime_cutover_can_be_enabled_explicitly(monkeypatch) -> None:
    monkeypatch.setenv("FITMAS_PLANNING_RUNTIME_CUTOVER", "1")

    assert conversation_pipeline._planning_runtime_cutover_enabled() is True


def test_planning_runtime_mapper_uses_fallback_if_composer_rejects(monkeypatch) -> None:
    class FakeComposer:
        def compose(self, outcome, context, *, user_text="", grounding_facts=()):
            return ReplyResult(text=None, verified=False, fallback_used=True, reason="voice")

    monkeypatch.setattr(conversation_pipeline, "_decision_reply_composer", lambda: FakeComposer())

    outcome = conversation_pipeline._conversation_outcome_from_planning_runtime_result(
        _planning_result("block"),
        user_text="force la seance",
        grounding_facts=(),
    )

    assert outcome.response_mode == "planning_runtime_block"
    assert outcome.reply_text == "Option possible, confirmation recommandee."
```

- [ ] **Step 2: Run flag tests**

Run:

```bash
./scripts/test-backend tests/test_conversation_planning_runtime_reply_composer.py tests/test_core_flows.py -q
```

Expected:

```text
all selected tests pass with flag-off defaults
```

- [ ] **Step 3: Optional manual flag-on probe**

Run this only after the selected and full suites pass:

```bash
FITMAS_PLANNING_RUNTIME_CUTOVER=1 ./scripts/test-backend tests/test_conversation_planning_runtime_reply_composer.py -q
```

Expected:

```text
unit-level mapper tests pass
```

Do not run the full core suite with the flag as an acceptance gate in Phase 5. If an agent chooses to run it and finds semantic failures, keep the flag off and record the failing cases in `docs/DECISION-RUNTIME-REFACTOR.md` under "Remaining Phase 5 Cutover Risks". Do not force policy from the reply layer.

## Task 11: Documentation And Verification

**Files:**
- Modify: `docs/DECISION-RUNTIME-REFACTOR.md`
- Modify: `docs/BUILD-ORDER.md`
- Modify: `docs/superpowers/plans/2026-05-14-decision-runtime-phase-5-reply-composer.md`

- [ ] **Step 1: Update refactor doc**

Add to `docs/DECISION-RUNTIME-REFACTOR.md`:

```markdown
Livres en Phase 5 initiale :

- `ReplyRequest` et `ReplyResult` ajoutent un contrat de parole pure dans `decision/` ;
- `DecisionReplyComposer` transforme `DecisionOutcome` en demande de reply, puis verifie la sortie ;
- `DecisionOutputVerifier` bloque claims sans event, jargon interne et voix invalide ;
- `legacy/final_reply_backend.py` devient le seul pont vers l'ancien `final_reply.py` ;
- les outcomes planning et PlanPatch legacy sont adaptes vers `DecisionOutcome` avant parole visible ;
- le cutover conversation planning reste opt-in jusqu'a parite semantique flag-on.
```

- [ ] **Step 2: Update build order**

In `docs/BUILD-ORDER.md`, update Roadmap Active:

```markdown
1. Phase 5 : ReplyComposer unique depuis DecisionOutcome
2. Phase 6 : prompts simplifies en Understanding / Reviewer / Reply
3. Phase 7+ : heartbeat via runtime, kill legacy
```

Add Phase 5 local status once implemented.

- [ ] **Step 3: Run targeted tests**

Run:

```bash
./scripts/test-backend \
  tests/test_decision_reply_composer.py \
  tests/test_decision_output_verifier.py \
  tests/test_legacy_final_reply_backend.py \
  tests/test_planning_outcome_adapter.py \
  tests/test_plan_patch_reply_adapter.py \
  tests/test_conversation_planning_runtime_reply_composer.py \
  tests/test_phase5_reply_architecture.py \
  tests/test_decision_runtime_architecture.py \
  -q
```

Expected:

```text
all selected tests pass
```

- [ ] **Step 4: Run regression suites**

Run:

```bash
./scripts/test-backend tests/test_final_reply.py tests/test_plan_adaptation_final_reply.py tests/test_core_flows.py -q
./scripts/test-backend -q
```

Expected:

```text
all selected tests pass
full suite passes
```

## Acceptance Criteria

Phase 5 is accepted when:

- planning runtime replies come from `DecisionOutcome -> DecisionReplyComposer`;
- legacy PlanPatch visible helpers delegate to `DecisionReplyComposer`;
- `decision/` still has no import of `fitmas.final_reply`, `fitmas.legacy`, DB, `PlanPatch`, or `MutationDecision`;
- only `legacy/final_reply_backend.py` imports `fitmas.final_reply` for the new path;
- pending replies ask for confirmation or choice and never claim commit;
- committed replies require applied event evidence;
- blocked replies explain the block without claiming action;
- flag-off full suite passes;
- flag-on planning smoke tests pass or documented semantic failures stay behind the flag.

## Explicit Non-Goals

- Do not delete `final_reply.py`.
- Do not migrate heartbeat.
- Do not rewrite prompts into `llm/prompts/reply.py`; that is Phase 6.
- Do not enable `FITMAS_PLANNING_RUNTIME_CUTOVER` by default.
- Do not remove legacy PlanPatch/MutationDecision branches yet.
- Do not make `conversation_pipeline.py` thin in this phase; reduce speech responsibility first.

## Review Checklist

Ask these on every PR:

```text
Does any new code produce visible text outside ReplyComposer?
Does decision/ import final_reply, legacy, PlanPatch, MutationDecision or DB?
Does a pending reply claim an action was done?
Does a committed reply have an applied event id?
Does conversation_pipeline add a new reply branch instead of delegating?
Did a test assert only exact copy while missing semantic guards?
Is FITMAS_PLANNING_RUNTIME_CUTOVER still off by default?
```

## Execution Recommendation

Run this phase inline with checkpoints after Tasks 3, 6, 8 and 11.

Reason: tasks are tightly coupled around `conversation_pipeline.py`; multiple agents editing it in parallel would create merge risk. Subagents can still review architecture tests or inspect reply helper callsites, but implementation should stay serial.
