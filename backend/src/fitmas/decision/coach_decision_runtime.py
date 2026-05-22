from __future__ import annotations

from typing import Any

from fitmas.decision.conversation_contract import ConversationTurnOutcome
from fitmas.decision import DecisionExplanation, DecisionOutcome, ReplyContract
from fitmas.decision.message_models import Extraction


def legacy_provider_skip_reason(turn_context: dict[str, object]) -> str:
    legacy_trace = turn_context.get("legacy_decide")
    if isinstance(legacy_trace, dict) and legacy_trace.get("legacy_skipped") is True:
        return _trace_reason("legacy_decide", legacy_trace, default="already_skipped")

    planning = turn_context.get("canonical_planning_provider")
    if isinstance(planning, dict):
        result = str(planning.get("result") or "").strip()
        if result in {"blocked", "handled"} or _denies_legacy_provider(planning):
            return _trace_reason("canonical_planning_provider", planning, default=result)

    pending = turn_context.get("canonical_pending_provider")
    if isinstance(pending, dict):
        result = str(pending.get("result") or "").strip()
        if result == "handled" or _denies_legacy_provider(pending):
            return _trace_reason("canonical_pending_provider", pending, default=result)

    readonly = turn_context.get("canonical_readonly_reply")
    if isinstance(readonly, dict):
        if _denies_legacy_provider(readonly):
            return _trace_reason("canonical_readonly_reply", readonly, default="compose_failed")
        if readonly.get("composed") is True:
            return _trace_reason("canonical_readonly_reply", readonly, default="composed")

    clarification = turn_context.get("canonical_clarification")
    if isinstance(clarification, dict):
        if _denies_legacy_provider(clarification):
            return _trace_reason("canonical_clarification", clarification, default="compose_failed")
        if clarification.get("composed") is True:
            return _trace_reason("canonical_clarification", clarification, default="composed")

    return "coach_decision_provider_removed"


def trace_legacy_provider_skipped(turn_context: dict[str, object], *, reason: str) -> None:
    turn_context["legacy_decide"] = {
        "legacy_skipped": True,
        "source": "legacy_provider_gate",
        "reason": str(reason or "canonical_provider_clarification"),
    }


def canonical_provider_clarification_outcome(
    *,
    reason: str,
    user_text: str,
    grounding_facts: tuple[str, ...],
    decision_reply_composer_fn,
) -> ConversationTurnOutcome:
    decision_outcome = DecisionOutcome(
        kind="clarification",
        commands=(),
        applied_commands=(),
        candidates=(),
        selected_candidate_id=None,
        explanation=DecisionExplanation(
            decision_label="Tour repris proprement",
            reason_summary="Je n'ai pas assez d'elements fiables pour agir proprement.",
            evidence=("canonical_provider_clarification", reason),
            tradeoff=None,
            impact={},
            protected=("no_legacy_decide", "no_uncommitted_plan_claim"),
            next_step="Redis-moi le changement voulu en une phrase et je le reprends proprement.",
        ),
        reply_contract=ReplyContract(
            mode="canonical_provider_clarification",
            audience="conversation",
            allowed_claims=("clarification",),
            forbidden_claims=("plan_committed", "plan_pending", "execution_updated_without_event"),
        ),
    )
    reply_result = decision_reply_composer_fn().compose(
        decision_outcome,
        context=None,
        user_text=user_text,
        grounding_facts=grounding_facts,
    )
    return ConversationTurnOutcome(
        extraction=Extraction(confidence=0.65),
        reply_text=reply_result.text or decision_outcome.explanation.next_step or decision_outcome.explanation.reason_summary,
        response_mode="canonical_provider_clarification",
        mutation_applied=False,
        pending_confirmation=False,
    )


def decide_none_context(turn_context: dict[str, object]) -> dict[str, object]:
    existing = turn_context.get("decide_none")
    if isinstance(existing, dict):
        return existing
    return {
        "reason": "unknown",
        "prompt_trace": None,
        "events": [],
    }


def _trace_reason(source: str, trace: dict[str, Any], *, default: str) -> str:
    reason = _reason(trace, default=default)
    return f"{source}:{reason}"


def _reason(trace: dict[str, Any], *, default: str) -> str:
    for key in ("fallback_reason", "reason", "attempt_reason", "result"):
        value = str(trace.get(key) or "").strip()
        if value:
            return value
    return default


def _denies_legacy_provider(trace: dict[str, Any]) -> bool:
    return trace.get("deny_legacy_provider") is True
