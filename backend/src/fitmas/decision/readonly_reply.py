from __future__ import annotations

import os
from typing import Any

from fitmas.domain.coaching import coach_voice
from fitmas.decision.conversation_contract import ConversationTurnOutcome
from fitmas.decision import CoachUnderstanding, DecisionExplanation, DecisionOutcome, ReplyContract
from fitmas.decision.command_mapping import commands_from_understanding
from fitmas.decision.message_models import Extraction


_READONLY_INTENTS = {
    "answer",
    "general_answer",
    "plan_lookup",
    "fact_recall",
}
_NON_READONLY_INTENTS = {
    "availability_signal",
    "clarification",
    "close",
    "execution_report",
    "health_signal",
    "memory_update",
    "pending_response",
    "plan_change",
}
_NON_READONLY_PRIMARY_INTENTS = {
    "availability_constraint",
    "close_turn",
    "execution_report",
    "health_signal",
    "plan_mutation",
}


def canonical_readonly_provider_enabled() -> bool:
    return _env_flag_enabled("FITMAS_CANONICAL_READONLY_PROVIDER", default=True)


def should_use_canonical_readonly_without_legacy(
    *,
    understanding: CoachUnderstanding | None,
    turn_plan: Any,
    pending_confirmation: Any,
) -> bool:
    if not canonical_readonly_provider_enabled():
        return False
    if understanding is None:
        return False
    if _turn_plan_has_non_readonly_primary_intent(turn_plan):
        return False
    if understanding.intent in _NON_READONLY_INTENTS:
        return False
    if understanding.intent == "plan_change" or understanding.requested_change is not None:
        return False
    if understanding.pending_resolution is not None or _has_active_pending(pending_confirmation):
        return False
    if commands_from_understanding(understanding).commands:
        return False
    return _turn_plan_is_readonly_answer(turn_plan) or understanding.intent in _READONLY_INTENTS


def compose_canonical_readonly_reply(
    *,
    composer,
    understanding: CoachUnderstanding,
    user_text: str,
    turn_plan: Any,
    turn_context: dict[str, object],
    grounding_facts: tuple[str, ...],
) -> ConversationTurnOutcome | None:
    outcome = _answer_outcome_from_understanding(understanding, turn_plan=turn_plan)
    result = composer.compose(
        outcome,
        None,
        user_text=user_text,
        grounding_facts=grounding_facts,
    )
    text = str((getattr(result, "text", None) if result is not None else None) or "").strip()
    if not text:
        text = _grounded_readonly_fallback(
            understanding=understanding,
            turn_plan=turn_plan,
            grounding_facts=grounding_facts,
        )
        if text:
            turn_context["canonical_readonly_reply"] = {
                "intent": understanding.intent,
                "source": "grounding_fallback",
                "composed": True,
                "verified": True,
                "fallback_used": True,
                "reason": getattr(result, "reason", None) if result is not None else "empty",
            }
            _trace_legacy_skipped(turn_context)
            return ConversationTurnOutcome(
                extraction=Extraction(confidence=understanding.confidence),
                reply_text=text,
                response_mode="canonical_readonly_answer",
                decision=None,
                mutation_applied=False,
            )
        turn_context["canonical_readonly_reply"] = {
            "intent": understanding.intent,
            "source": "coach_understanding",
            "composed": False,
            "reason": getattr(result, "reason", None) if result is not None else "empty",
        }
        return None

    fallback_text = _grounded_readonly_fallback(
        understanding=understanding,
        turn_plan=turn_plan,
        grounding_facts=grounding_facts,
    )
    if fallback_text and not _plan_lookup_reply_mentions_plan_truth(text, grounding_facts):
        turn_context["canonical_readonly_reply"] = {
            "intent": understanding.intent,
            "source": "grounding_fallback",
            "composed": True,
            "verified": True,
            "fallback_used": True,
            "reason": "ungrounded_plan_lookup_reply",
        }
        _trace_legacy_skipped(turn_context)
        return ConversationTurnOutcome(
            extraction=Extraction(confidence=understanding.confidence),
            reply_text=fallback_text,
            response_mode="canonical_readonly_answer",
            decision=None,
            mutation_applied=False,
        )

    turn_context["canonical_readonly_reply"] = {
        "intent": understanding.intent,
        "source": "coach_understanding",
        "composed": True,
        "verified": bool(getattr(result, "verified", False)),
        "fallback_used": bool(getattr(result, "fallback_used", False)),
    }
    _trace_legacy_skipped(turn_context)
    return ConversationTurnOutcome(
        extraction=Extraction(confidence=understanding.confidence),
        reply_text=text,
        response_mode="canonical_readonly_answer",
        decision=None,
        mutation_applied=False,
    )


def _answer_outcome_from_understanding(
    understanding: CoachUnderstanding,
    *,
    turn_plan: Any,
) -> DecisionOutcome:
    reason = understanding.user_summary or "Reponse basee sur le contexte disponible."
    primary_intent = str(getattr(turn_plan, "primary_intent", "") or "")
    return DecisionOutcome(
        kind="answer",
        commands=(),
        applied_commands=(),
        candidates=(),
        selected_candidate_id=None,
        explanation=DecisionExplanation(
            decision_label=primary_intent or understanding.intent or "answer",
            reason_summary=reason,
            evidence=(),
            tradeoff=None,
            impact={},
            protected=(),
            next_step=None,
        ),
        reply_contract=ReplyContract(
            mode="canonical_readonly_answer",
            audience="user",
            allowed_claims=("read_truth", "answer"),
            forbidden_claims=("mutation_committed", "pending_created", "plan_changed"),
        ),
    )


def _grounded_readonly_fallback(
    *,
    understanding: CoachUnderstanding,
    turn_plan: Any,
    grounding_facts: tuple[str, ...],
) -> str | None:
    primary_intent = str(getattr(turn_plan, "primary_intent", "") or "")
    if understanding.intent != "plan_lookup" and primary_intent != "plan_lookup":
        return None
    lines = tuple(_humanize_plan_window_line(line) for line in grounding_facts)
    plan_lines = tuple(line for line in lines if line)
    if not plan_lines:
        return None
    return "Voici ce que j'ai dans le planning : " + " ".join(plan_lines[:8])


def _humanize_plan_window_line(line: str) -> str | None:
    text = str(line or "").strip()
    if not text.startswith("- ") or " id=" not in text:
        return None
    text = text.removeprefix("- ").strip()
    date_part, _, rest = text.partition(" id=")
    date_part = date_part.strip()
    date_label = _date_label(date_part)
    title = _quoted_title(rest)
    duration = _duration_label(rest)
    if not title:
        title = _sport_label(rest)
    pieces = [date_label, title]
    if duration:
        pieces.append(duration)
    return f"{pieces[0]} : {', '.join(pieces[1:])}."


def _plan_lookup_reply_mentions_plan_truth(text: str, grounding_facts: tuple[str, ...]) -> bool:
    plan_lines = tuple(line for line in grounding_facts if _humanize_plan_window_line(line))
    if not plan_lines:
        return True
    normalized_reply = coach_voice.normalize_for_voice_guard(text)
    for line in plan_lines:
        if _plan_line_has_truth_marker_in_reply(line, normalized_reply):
            return True
    return False


def _plan_line_has_truth_marker_in_reply(line: str, normalized_reply: str) -> bool:
    date_text = str(line or "").removeprefix("- ").partition(" id=")[0].strip()
    iso_date = date_text.split(" ", 1)[0].strip()
    title = _quoted_title(line)
    for marker in (title, iso_date):
        normalized_marker = coach_voice.normalize_for_voice_guard(str(marker or ""))
        if normalized_marker and normalized_marker in normalized_reply:
            return True
    return False


def _date_label(value: str) -> str:
    text = str(value or "").strip()
    if "(" in text and ")" in text:
        date_text, _, remainder = text.partition("(")
        day_label, _, _ = remainder.partition(")")
        date_text = date_text.strip()
        day_label = day_label.strip()
        if date_text and day_label:
            return f"{day_label} {date_text}"
    return text


def _quoted_title(value: str) -> str | None:
    parts = str(value or "").split('"')
    if len(parts) >= 3:
        title = parts[1].strip()
        if title:
            return title
    return None


def _duration_label(value: str) -> str | None:
    for token in str(value or "").split():
        if token.endswith("min"):
            raw = token.removesuffix("min").strip()
            return f"{raw} min" if raw else None
    return None


def _sport_label(value: str) -> str:
    tokens = str(value or "").split()
    if len(tokens) >= 2:
        return tokens[1]
    return "seance"


def _trace_legacy_skipped(turn_context: dict[str, object]) -> None:
    turn_context["legacy_decide"] = {
        "source": "coach_understanding_readonly",
        "ok": True,
        "error_type": None,
        "artifact_kind": "none",
        "response_type": "canonical_readonly_answer",
        "decision_present": False,
        "has_plan_patch": False,
        "has_pending_resolution": False,
        "memory_action_count": 0,
        "execution_action_count": 0,
        "decide_none_present": False,
        "legacy_skipped": True,
    }


def _turn_plan_is_readonly_answer(turn_plan: Any) -> bool:
    if turn_plan is None:
        return False
    primary_intent = str(getattr(turn_plan, "primary_intent", "") or "")
    if primary_intent in _NON_READONLY_PRIMARY_INTENTS:
        return False
    if primary_intent in _READONLY_INTENTS:
        return True
    if bool(getattr(turn_plan, "requires_truth_read", False)):
        return True
    return str(getattr(turn_plan, "truth_scope", "") or "") in {"plan_window", "facts", "memory"}


def _turn_plan_has_non_readonly_primary_intent(turn_plan: Any) -> bool:
    if turn_plan is None:
        return False
    primary_intent = str(getattr(turn_plan, "primary_intent", "") or "")
    return primary_intent in _NON_READONLY_PRIMARY_INTENTS


def _has_active_pending(pending_confirmation: Any) -> bool:
    return pending_confirmation is not None and str(getattr(pending_confirmation, "status", "") or "") == "pending"


def _env_flag_enabled(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
