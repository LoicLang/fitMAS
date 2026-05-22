from __future__ import annotations

from datetime import date, datetime
from typing import Any

from fitmas.decision.conversation_contract import ConversationTurnOutcome
from fitmas.decision import DecisionExplanation, DecisionOutcome, ReplyContract
from fitmas.models import Extraction


def compose_activity_highlight_reply(
    *,
    composer: Any,
    activities: tuple[Any, ...],
    user_text: str,
    turn_plan: Any,
    turn_context: dict[str, object],
    grounding_facts: tuple[str, ...],
) -> ConversationTurnOutcome | None:
    if not _turn_plan_is_activity_highlight(turn_plan):
        return None
    summary = _activity_highlight_summary(activities)
    if summary is None:
        summary = "Je n'ai pas assez d'activites recentes exploitables pour classer une sortie."
    outcome = DecisionOutcome(
        kind="answer",
        commands=(),
        applied_commands=(),
        candidates=(),
        selected_candidate_id=None,
        explanation=DecisionExplanation(
            decision_label="Activity highlight",
            reason_summary=summary,
            evidence=("turn_plan.activity_highlights",),
            tradeoff=None,
            impact={},
            protected=("no_legacy_decide", "read_only"),
            next_step=None,
        ),
        reply_contract=ReplyContract(
            mode="canonical_activity_highlight",
            audience="conversation",
            allowed_claims=("read_truth", "answer"),
            forbidden_claims=("plan_committed", "plan_pending", "plan_changed"),
        ),
    )
    result = composer.compose(outcome, None, user_text=user_text, grounding_facts=grounding_facts)
    text = str((getattr(result, "text", None) if result is not None else None) or summary).strip()
    if not text:
        return None
    turn_context["canonical_activity_highlight"] = {
        "source": "activity_history",
        "composed": True,
        "verified": bool(getattr(result, "verified", False)) if result is not None else False,
        "fallback_used": bool(getattr(result, "fallback_used", False)) if result is not None else True,
    }
    turn_context["legacy_decide"] = {
        "source": "activity_highlight",
        "ok": True,
        "error_type": None,
        "artifact_kind": "none",
        "response_type": "canonical_activity_highlight",
        "decision_present": False,
        "has_plan_patch": False,
        "has_pending_resolution": False,
        "memory_action_count": 0,
        "execution_action_count": 0,
        "decide_none_present": False,
        "legacy_skipped": True,
    }
    return ConversationTurnOutcome(
        extraction=Extraction(confidence=_confidence(turn_plan)),
        reply_text=text,
        response_mode="canonical_activity_highlight",
        decision=None,
        mutation_applied=False,
        pending_confirmation=False,
    )


def _turn_plan_is_activity_highlight(turn_plan: Any) -> bool:
    if turn_plan is None:
        return False
    intents = {
        str(getattr(turn_plan, "primary_intent", "") or ""),
        *(str(item or "") for item in tuple(getattr(turn_plan, "secondary_intents", ()) or ())),
    }
    return "activity_highlights" in intents


def _activity_highlight_summary(activities: tuple[Any, ...]) -> str | None:
    recent = tuple(activity for activity in activities if _duration_min(activity) is not None)
    if not recent:
        return None
    longest_duration = max(recent, key=lambda item: _duration_min(item) or 0)
    title = _title(longest_duration)
    duration = _duration_min(longest_duration)
    started = _date_label(_started_at(longest_duration))
    sport = _sport_label(longest_duration)
    summary = f"Ta plus longue sortie recente en duree, c'est {title} ({sport})"
    if started:
        summary += f" du {started}"
    if duration is not None:
        summary += f" : {duration} min"
    if not any((_distance_m(activity) or 0) > 0 for activity in activities):
        summary += ". Je n'ai pas de distance exploitable sur ces activites."
    else:
        summary += "."
    return summary


def _title(activity: Any) -> str:
    return str(_value(activity, "title") or "activite").strip() or "activite"


def _sport_label(activity: Any) -> str:
    sport = str(_value(activity, "sport_type") or "").strip().lower()
    return {
        "cycling": "velo",
        "running": "course",
        "swimming": "natation",
        "strength": "renfo",
    }.get(sport, sport or "sport")


def _duration_min(activity: Any) -> int | None:
    raw = _value(activity, "duration_min")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _distance_m(activity: Any) -> float | None:
    raw = _value(activity, "distance_m")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _started_at(activity: Any) -> date | None:
    raw = _value(activity, "started_at")
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _date_label(value: date | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _confidence(turn_plan: Any) -> float:
    try:
        return max(0.0, min(1.0, float(getattr(turn_plan, "confidence", 0.8) or 0.8)))
    except (TypeError, ValueError):
        return 0.8


def _value(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)
