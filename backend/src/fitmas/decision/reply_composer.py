from __future__ import annotations

from typing import Protocol

from .context import CoachContext
from .outcome import DecisionOutcome
from .output_verifier import DecisionOutputVerifier, OutputVerifier
from .reply_request import ReplyRequest, ReplyResult


class ReplyComposer(Protocol):
    def compose(self, outcome: DecisionOutcome, context: CoachContext) -> str:
        ...


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
        if verified.allowed and _reply_satisfies_contract(verified.text, request):
            return ReplyResult(text=verified.text, verified=True, fallback_used=False, reason=None)

        fallback = self._fallback_reply(request)
        fallback_verification = self._verify(fallback, outcome, context)
        return ReplyResult(
            text=fallback_verification.text if fallback_verification.allowed else None,
            verified=fallback_verification.allowed,
            fallback_used=True,
            reason=verified.reason or "reply_contract",
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
            if request.explanation.next_step:
                return f"{request.explanation.reason_summary} {request.explanation.next_step}".strip()
            return f"{request.explanation.reason_summary} Tu confirmes ?"
        if request.kind == "plan_choice_pending":
            if request.explanation.next_step:
                return f"{request.explanation.reason_summary} {request.explanation.next_step}".strip()
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


def _reply_satisfies_contract(text: str, request: ReplyRequest) -> bool:
    if request.kind == "plan_pending" and "pending_created" in request.contract.allowed_claims:
        return _mentions_confirmation(text)
    return True


def _mentions_confirmation(text: str) -> bool:
    value = str(text or "")
    normalized = value.lower()
    return "?" in value or "confirmes" in normalized or "feu vert" in normalized or "ton accord" in normalized
