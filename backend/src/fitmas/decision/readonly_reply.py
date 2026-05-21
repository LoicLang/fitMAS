from __future__ import annotations

import os
from typing import Any, Callable

from sqlalchemy.orm import Session

from fitmas import coach_voice
from fitmas import repository as repo
from fitmas.conversation_contract import ConversationTurnOutcome
from fitmas.decision import CoachUnderstanding, DecisionExplanation, DecisionOutcome, ReplyContract
from fitmas.decision.command_mapping import commands_from_understanding
from fitmas.grounding_contract import ReplyGroundingPacket
from fitmas.models import Extraction
import fitmas.llm.reply_backend as final_reply


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


def memory_action_phrases_for_final_reply(action_result: dict) -> tuple[str, ...]:
    if int(action_result.get("memory_applied") or 0) <= 0:
        return ()
    return ("Memoire utilisateur mise a jour.",)


def execution_action_phrases_for_final_reply(
    db: Session,
    *,
    user,
    action_result: dict,
) -> tuple[str, ...]:
    phrases: list[str] = []
    for raw_session_id in tuple(action_result.get("execution_updated_session_ids") or ()):
        try:
            session_id = int(raw_session_id)
        except (TypeError, ValueError):
            continue
        session = repo.get_scheduled_session(db, user.id, session_id)
        if session is None:
            continue
        title = str(session.session_title or "La seance").strip()
        status = str(session.completion_status or "").strip()
        if status == "done":
            phrases.append(f"{title} notee comme faite.")
        elif status == "skipped":
            phrases.append(f"{title} notee comme non faite.")
        else:
            phrases.append(f"{title} mise a jour.")
    if not phrases and int(action_result.get("execution_applied") or 0) > 0:
        phrases.append("Execution notee.")
    return tuple(phrases)


def compose_no_change_reply_for_turn(
    *,
    db: Session,
    user,
    user_text: str,
    original_reply: str,
    turn_context: dict[str, object],
    grounding: ReplyGroundingPacket | None = None,
    action_result: dict | None = None,
) -> tuple[str, str | None]:
    action_result = action_result or {}
    memory_actions_applied = memory_action_phrases_for_final_reply(action_result)
    execution_actions_applied = execution_action_phrases_for_final_reply(
        db,
        user=user,
        action_result=action_result,
    )
    primary_intent = turn_context_primary_intent(turn_context)
    plan_lookup_capability = primary_intent == "plan_lookup" or (
        turn_context_requires_truth_read(turn_context)
        and primary_intent not in {"plan_mutation", "availability_constraint", "health_signal", "execution_report"}
    )
    capability = (
        "plan_lookup"
        if plan_lookup_capability
        else "execution_report"
        if primary_intent == "execution_report"
        else "no_change"
    )
    if capability == "plan_lookup":
        lookup_grounding = grounding if turn_context_should_ground_plan_lookup(turn_context) else None
        composed_reply = final_reply.compose_plan_lookup_reply(
            user_text=user_text,
            original_llm_reply=original_reply,
            memory_actions_applied=memory_actions_applied,
            execution_actions_applied=execution_actions_applied,
            grounding=lookup_grounding,
        )
    elif capability == "execution_report":
        composed_reply = final_reply.compose_execution_report_reply(
            user_text=user_text,
            original_llm_reply=original_reply,
            memory_actions_applied=memory_actions_applied,
            execution_actions_applied=execution_actions_applied,
        )
    else:
        composed_reply = final_reply.compose_no_change_reply(
            user_text=user_text,
            original_llm_reply=original_reply,
            memory_actions_applied=memory_actions_applied,
            execution_actions_applied=execution_actions_applied,
        )
    if not composed_reply:
        if not _is_safe_original_reply(original_reply):
            fallback = _safe_no_change_fallback()
            turn_context["final_reply"] = {
                "capability": capability,
                "draft": original_reply,
                "output": fallback,
                "source": "canonical_safe_reply",
                "composed": False,
            }
            return fallback, "canonical_no_action_safe_reply"
        turn_context["final_reply"] = {
            "capability": capability,
            "draft": original_reply,
            "output": original_reply,
            "source": "draft_fallback",
            "composed": False,
        }
        return original_reply, None
    turn_context["final_reply"] = {
        "capability": capability,
        "draft": original_reply,
        "output": composed_reply,
        "source": "composer",
        "composed": True,
    }
    turn_context["final_reply_composed"] = True
    turn_context["final_reply_capability"] = capability
    return composed_reply, f"{capability}_composed"


def turn_context_primary_intent(turn_context: dict[str, object]) -> str:
    turn_plan = turn_context.get("turn_plan")
    if not isinstance(turn_plan, dict):
        return ""
    return str(turn_plan.get("primary_intent") or "")


def turn_context_requires_truth_read(turn_context: dict[str, object]) -> bool:
    turn_plan = turn_context.get("turn_plan")
    if not isinstance(turn_plan, dict):
        return False
    return bool(turn_plan.get("requires_truth_read")) or str(turn_plan.get("truth_scope") or "") == "plan_window"


def turn_context_should_ground_plan_lookup(turn_context: dict[str, object]) -> bool:
    turn_plan = turn_context.get("turn_plan")
    if not isinstance(turn_plan, dict):
        return False
    if str(turn_plan.get("truth_scope") or "") == "plan_window":
        return True
    refs = turn_plan.get("temporal_references")
    return isinstance(refs, list) and bool(refs)


def should_compose_understanding_command_reply(action_result: dict | None) -> bool:
    action_result = action_result or {}
    if str(action_result.get("command_source") or "") != "coach_understanding":
        return False
    return any(
        int(action_result.get(key) or 0) > 0
        for key in (
            "memory_applied",
            "memory_blocked",
            "execution_applied",
            "execution_blocked",
            "execution_deferred",
        )
    )


def compose_understanding_command_reply(
    *,
    db,
    user,
    user_text: str,
    understanding: CoachUnderstanding,
    turn_context: dict[str, object],
    grounding,
    action_result: dict,
    compose_no_change_reply_for_turn_fn: Callable[..., tuple[str, str | None]] | None,
) -> ConversationTurnOutcome:
    original_reply = _reply_hint_from_understanding(understanding)
    response_mode = "canonical_command_reply"
    if compose_no_change_reply_for_turn_fn is not None:
        reply_text, composed_mode = compose_no_change_reply_for_turn_fn(
            db=db,
            user=user,
            user_text=user_text,
            original_reply=original_reply,
            turn_context=turn_context,
            grounding=grounding,
            action_result=action_result,
        )
        if composed_mode:
            response_mode = composed_mode
    else:
        reply_text = original_reply
    return ConversationTurnOutcome(
        extraction=Extraction(confidence=understanding.confidence),
        reply_text=reply_text,
        response_mode=response_mode,
        decision=None,
        mutation_applied=False,
    )


def _reply_hint_from_understanding(understanding: CoachUnderstanding) -> str:
    if understanding.user_summary:
        return understanding.user_summary
    if understanding.intent == "execution_report":
        return "Signal d'execution compris."
    if understanding.intent == "pending_response":
        return "Confirmation comprise."
    return "Signal compris."


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


def _is_safe_original_reply(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    if coach_voice.message_violates_coach_voice(value):
        return False
    if coach_voice.message_has_user_facing_internal_jargon(value):
        return False
    if coach_voice.message_looks_receipt_style(value):
        return False
    return True


def _safe_no_change_fallback() -> str:
    return "Bien recu. Rien ne bouge dans le plan sur ce tour."


def _env_flag_enabled(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
