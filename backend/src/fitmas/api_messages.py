from __future__ import annotations

import logging
import unicodedata
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from fitmas import mutations, repository as repo
from fitmas.adaptation import check_and_adapt_health_facts
from fitmas.adaptation_log import build_adaptation_log_entry
from fitmas.activity_helpers import claimed_activities_last_days
from fitmas.activity_claims import (
    ActivityClaim,
    NonCompletionClaim,
    build_claim_fact_payloads,
    build_execution_conflict_archive_payloads,
    build_non_completion_fact_payloads,
    format_activity_claim_for_prompt,
    format_non_completion_claim_for_prompt,
)
from fitmas.execution_clarification import ExecutionClarification, build_execution_clarification
from fitmas.execution_evidence import classify_execution_evidence
from fitmas.athlete_profile import build_athlete_profile
from fitmas.api_payloads import IncomingMessage
from fitmas.calibration_llm import extract_calibration_resolution, generate_calibration_ack
from fitmas.calibration_needs import (
    build_resolution_memory_updates,
    find_open_calibration_need,
    is_standalone_calibration_answer,
    should_apply_calibration_resolution,
)
from fitmas.conversation_context import (
    activity_claim_summary_for_prompt,
    build_claim_memory_updates,
    build_conversation_context,
    execution_summary_for_prompt,
    non_completion_summary_for_prompt,
    signal_summary_for_prompt,
    temporal_summary_for_prompt,
)
from fitmas.conversation_contract import ConversationPipelineDependencies, ConversationTurnInput, ConversationUserNotFoundError
from fitmas.db import get_db
from fitmas.llm import MutationDecision, decide, extract_facts, make_plan_summary, make_timeline_summary, select_prompt_facts
from fitmas.memory_profile import upsert_profile_memory
from fitmas.memory_routing import split_memory_payloads
from fitmas.models import DayId, Extraction, Message, MessageReply, MessageRole
from fitmas.nlp import extract_reply, generate_reply
from fitmas.planning_window_resolution import resolve_planning_window
from fitmas.replan_from_life_change import (
    maybe_replan_from_life_change,
    maybe_replan_from_user_indication,
)
from fitmas.signals import collect_signals
from fitmas.tools.contract import ToolContext
from fitmas.user_indication_llm import interpret_user_indication
from fitmas.user_indications import (
    UserIndication,
    UserIndicationKind,
    UserIndicationPolarity,
    UserIndicationScope,
    build_health_fact_payloads_from_indication,
    looks_like_execution_clarification_prompt,
    supports_planning_resolution,
)
from fitmas.time_context import get_timezone

logger = logging.getLogger(__name__)

router = APIRouter()

_DAY_VALUES = {d.value for d in DayId}
_ACK_TEXTS = {"ok", "ok merci", "merci", "ca marche", "c est bon", "c'est bon", "top merci", "bien recu"}
_GREETING_TEXTS = {"salut", "bonjour", "hello", "yo"}
_MOTIVATION_TEXTS = {
    "je suis motive",
    "je suis motive cette semaine",
    "je suis motive en ce moment",
    "je suis chaud",
    "je suis chaud cette semaine",
}
_POST_REPLY_HEALTH_TEXT_MARKERS = (
    "j ai mal",
    "j'ai mal",
    "douleur",
    "gene",
    "gêne",
    "ca tire",
    "ça tire",
    "fatigue",
    "crame",
    "cramé",
    "rince",
    "rincé",
)
_NO_CHANGE_MUTATION_MARKERS = (
    "j annule",
    "j'oublie",
    "on oublie",
    "j annule",
    "on annule",
    "je deplace",
    "on decale",
    "je remplace",
    "on remplace",
    "je te mets",
    "on te met",
    "on y va sur",
    "on met pas",
)
_LOAD_RECALIBRATION_MARKERS = (
    "loup",
    "rate",
    "raté",
    "charges",
    "charge",
    "semaine derniere",
)


def _resolve_day_updated(decision: MutationDecision) -> DayId | None:
    """Extract the affected day from a mutation decision."""
    target = decision.to_day or decision.from_day
    if target and target in _DAY_VALUES:
        return DayId(target)
    return None


def _to_mutation_decision(proposed, *, fitmas_message: str) -> MutationDecision:
    return MutationDecision(
        mutation_type=proposed.mutation_type,
        target_session_id=proposed.target_session_id,
        second_session_id=None,
        target_date=proposed.target_date,
        from_day=proposed.from_day,
        to_day=proposed.to_day,
        new_title=proposed.new_title,
        new_goal=proposed.new_goal,
        new_sport_type=proposed.new_sport_type,
        new_session_type=proposed.new_session_type,
        new_duration_min=proposed.new_duration_min,
        new_intensity=proposed.new_intensity,
        new_description=proposed.new_description,
        rationale=proposed.rationale,
        fitmas_message=fitmas_message,
    )


def _normalize_text(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    return " ".join(folded.lower().strip().split())


def _maybe_low_signal_reply(text: str, *, has_open_calibration_need: bool) -> str | None:
    if has_open_calibration_need:
        return None
    normalized = _normalize_text(text)
    if normalized in _ACK_TEXTS:
        return "Bien recu."
    if normalized in _GREETING_TEXTS:
        return "Salut."
    if normalized in _MOTIVATION_TEXTS:
        return "Bien. On garde cette energie, rien a changer pour l'instant."
    return None


def _should_run_post_reply_health_adaptation(
    *,
    user_text: str,
    extracted_facts: list[dict],
    user_indication: UserIndication | None,
) -> bool:
    if user_indication is not None and user_indication.kind is UserIndicationKind.HEALTH_SIGNAL:
        return True
    if not any(str(fact.get("category") or "") in {"health", "fatigue"} for fact in extracted_facts):
        return False
    normalized = _normalize_text(user_text)
    return any(marker in normalized for marker in _POST_REPLY_HEALTH_TEXT_MARKERS)


def _week_scope_reply(indication: UserIndication | None, resolution) -> str | None:
    if indication is None or indication.kind is not UserIndicationKind.AVAILABILITY_CONSTRAINT:
        return None
    if indication.scope is not UserIndicationScope.WEEK or resolution is None:
        return None
    if resolution.matched_session_id is not None:
        return None

    if not resolution.candidate_sessions:
        return f"OK. Je n'ai rien de sensible planifie sur {resolution.reference_label}. Rien a proteger la-dessus."

    parts = []
    for candidate in resolution.candidate_sessions[:3]:
        parts.append(f"{candidate.session_title} le {candidate.scheduled_date.isoformat()}")
    sessions_brief = ", ".join(parts)
    if indication.polarity is UserIndicationPolarity.UNAVAILABLE:
        return (
            f"OK. Dans cette fenetre j'ai {sessions_brief}. "
            "Si tu es off complet pendant ce bloc, je les retire et je garde le reste propre. "
            "Tu confirmes qu'on part sur off complet ?"
        )
    return (
        f"OK. Dans cette fenetre j'ai {sessions_brief}. "
        "Tu gardes un petit creneau en deplacement, ou je pars sur une version tres legere ?"
    )


def _human_time_label(indication: UserIndication | None, resolution) -> str:
    label = ""
    if indication is not None and indication.time_reference is not None:
        label = indication.time_reference.label or ""
    elif resolution is not None:
        label = resolution.reference_label or ""
    if label.startswith("explicit_"):
        label = label.removeprefix("explicit_")
    normalized = (
        label.replace("morning", "matin")
        .replace("midday", "midi")
        .replace("evening", "soir")
        .replace("monday", "lundi")
        .replace("tuesday", "mardi")
        .replace("wednesday", "mercredi")
        .replace("thursday", "jeudi")
        .replace("friday", "vendredi")
        .replace("saturday", "samedi")
        .replace("sunday", "dimanche")
        .strip()
    )
    return normalized or "sur ce creneau"


def _no_candidate_constraint_reply(indication: UserIndication | None, resolution) -> str | None:
    if indication is None or indication.kind is not UserIndicationKind.AVAILABILITY_CONSTRAINT:
        return None
    if resolution is None or resolution.candidate_sessions:
        return None
    if indication.scope not in {UserIndicationScope.SINGLE_WINDOW, UserIndicationScope.SINGLE_DAY}:
        return None
    return f"OK. Je n'ai rien de sensible planifie {_human_time_label(indication, resolution)}. Rien a bouger pour l'instant."


def _active_memory_payloads(db: Session, user_id: int) -> tuple[list[object], list[dict]]:
    rows = repo.get_active_memory_items(
        db,
        user_id,
        profile_limit=24,
        working_limit=24,
        include_patterns=True,
        pattern_limit=6,
        total_limit=36,
    )
    return rows, [repo.to_pydantic_fact(row).model_dump() for row in rows]


def _persist_memory_updates(db: Session, user_id: int, payloads: list[dict]) -> None:
    profile_payloads, working_payloads = split_memory_payloads(payloads)
    if profile_payloads:
        upsert_profile_memory(db, user_id, profile_payloads)
    if working_payloads:
        repo.upsert_working_memory(db, user_id, working_payloads)


def _value(obj, key: str):
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _coerce_local_date(value, *, timezone_name: str | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.date()
        return value.astimezone(get_timezone(timezone_name)).date()
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            try:
                return date.fromisoformat(value[:10])
            except ValueError:
                return None
        if parsed.tzinfo is None:
            return parsed.date()
        return parsed.astimezone(get_timezone(timezone_name)).date()
    return None


def _execution_contestation_reply(
    *,
    db: Session,
    user,
    scheduled_sessions,
    activities,
    timezone_name: str | None,
    non_completion_claim,
) -> str | None:
    if non_completion_claim is None or non_completion_claim.resolved_date_iso is None:
        return None

    target_date = date.fromisoformat(non_completion_claim.resolved_date_iso)
    sessions_on_date = [
        session
        for session in scheduled_sessions
        if _coerce_local_date(_value(session, "scheduled_date"), timezone_name=timezone_name) == target_date
        and str(_value(session, "sport_type") or "").lower() != "rest"
    ]
    target_session = next(
        (
            session
            for session in sessions_on_date
            if non_completion_claim.sport_type
            and str(_value(session, "sport_type") or "").lower() == non_completion_claim.sport_type
        ),
        sessions_on_date[0] if len(sessions_on_date) == 1 else None,
    )
    activities_on_date = [
        activity
        for activity in activities
        if _coerce_local_date(_value(activity, "started_at") or _value(activity, "created_at"), timezone_name=timezone_name) == target_date
    ]
    evidence = classify_execution_evidence(
        planned_session=target_session,
        activities=activities_on_date,
    )
    if evidence.display_status == "confirmed_done":
        return None

    if target_session is not None and str(_value(target_session, "completion_status") or "").lower() in {"planned", "done"}:
        updated_session = repo.set_scheduled_session_status(db, int(_value(target_session, "id")), "skipped")
        if updated_session is not None:
            _, day_plan = repo.get_current_week_day_plan_for_session(db, user=user, session=updated_session)
            if day_plan is not None and str(day_plan.completion_status or "").lower() == "done":
                day_plan.completion_status = "skipped"
                db.commit()

    title = str(_value(target_session, "session_title") or "").strip()
    if title:
        subject = title.lower()
    elif non_completion_claim.sport_type:
        sport_labels = {
            "running": "cette sortie running",
            "swimming": "cette seance natation",
            "cycling": "cette sortie velo",
            "strength": "cette seance renfo",
            "climbing": "cette seance escalade",
        }
        subject = sport_labels.get(non_completion_claim.sport_type, "cette seance")
    else:
        subject = "cette seance"
    return f"OK. Je ne compte pas {subject} comme faite. Je repars de ce que tu me dis, pas d'une validation implicite."


def _targeted_execution_clarification(
    *,
    db: Session,
    user,
    conversation_context,
    user_indication: UserIndication | None,
    resolved_non_completion_claim: NonCompletionClaim | None,
    resolved_activity_claim: ActivityClaim | None,
    previous_agent_text: str | None,
) -> ExecutionClarification | None:
    if (
        user_indication is not None
        and user_indication.kind is UserIndicationKind.AVAILABILITY_CONSTRAINT
    ):
        return None
    if (
        user_indication is not None
        and user_indication.kind is UserIndicationKind.HEALTH_SIGNAL
        and user_indication.execution_completed is False
    ):
        return None
    if looks_like_execution_clarification_prompt(previous_agent_text):
        return None

    today = conversation_context.temporal_resolution.local_date
    yesterday = today.fromordinal(today.toordinal() - 1)
    if (
        resolved_non_completion_claim is not None
        and resolved_non_completion_claim.resolved_date_iso == yesterday.isoformat()
    ):
        return None
    if (
        resolved_activity_claim is not None
        and resolved_activity_claim.resolved_date_iso == yesterday.isoformat()
    ):
        return None

    recent_sessions = repo.get_scheduled_sessions_between_dates(
        db,
        user.id,
        start_date=today.fromordinal(today.toordinal() - 13),
        end_date=today,
        limit=42,
    )
    yesterday_sessions = [
        session
        for session in recent_sessions
        if _coerce_local_date(_value(session, "scheduled_date"), timezone_name=user.timezone) == yesterday
        and str(_value(session, "sport_type") or "").lower() != "rest"
    ]
    if not yesterday_sessions:
        return None

    recent_claims = claimed_activities_last_days(db, user, days=14)
    return build_execution_clarification(
        today=today,
        target_session=yesterday_sessions[0],
        target_date=yesterday,
        scheduled_sessions=recent_sessions,
        activities=repo.get_activities(db, user.id, limit=120),
        claims=list(recent_claims),
    )


def _latest_agent_text(conversation_history: list[dict]) -> str | None:
    for msg in reversed(conversation_history):
        if msg.get("role") == "agent":
            return str(msg.get("text") or "")
    return None


def _yesterday_target_session(db: Session, user, *, today: date):
    recent_sessions = repo.get_scheduled_sessions_between_dates(
        db,
        user.id,
        start_date=today.fromordinal(today.toordinal() - 13),
        end_date=today,
        limit=42,
    )
    yesterday = today.fromordinal(today.toordinal() - 1)
    return next(
        (
            session
            for session in recent_sessions
            if _coerce_local_date(_value(session, "scheduled_date"), timezone_name=user.timezone) == yesterday
            and str(_value(session, "sport_type") or "").lower() != "rest"
        ),
        None,
    )


def _resolved_non_completion_from_indication(indication: UserIndication | None) -> NonCompletionClaim | None:
    if indication is None or indication.execution_completed is not False:
        return None
    if indication.time_reference is None or indication.time_reference.resolved_date is None:
        return None
    return NonCompletionClaim(
        sport_type=indication.execution_sport_type,
        resolved_date_iso=indication.time_reference.resolved_date.isoformat(),
        confidence=max(float(indication.confidence or 0.0), 0.82),
        source_text=indication.source_text,
    )


def _resolved_activity_from_indication(indication: UserIndication | None) -> ActivityClaim | None:
    if indication is None or indication.execution_completed is not True:
        return None
    if indication.time_reference is None or indication.time_reference.resolved_date is None:
        return None
    return ActivityClaim(
        sport_type=indication.execution_sport_type,
        duration_min=indication.execution_duration_min,
        resolved_date_iso=indication.time_reference.resolved_date.isoformat(),
        temporal_reference=indication.time_reference.relative_reference or indication.time_reference.label,
        confidence=max(float(indication.confidence or 0.0), 0.82),
        source_text=indication.source_text,
    )


def _apply_non_completion_resolution(
    *,
    db: Session,
    user,
    scheduled_sessions,
    timezone_name: str | None,
    non_completion_claim: NonCompletionClaim | None,
) -> None:
    if non_completion_claim is None or non_completion_claim.resolved_date_iso is None:
        return
    target_date = date.fromisoformat(non_completion_claim.resolved_date_iso)
    sessions_on_date = [
        session
        for session in scheduled_sessions
        if _coerce_local_date(_value(session, "scheduled_date"), timezone_name=timezone_name) == target_date
        and str(_value(session, "sport_type") or "").lower() != "rest"
    ]
    target_session = next(
        (
            session
            for session in sessions_on_date
            if non_completion_claim.sport_type
            and str(_value(session, "sport_type") or "").lower() == non_completion_claim.sport_type
        ),
        sessions_on_date[0] if len(sessions_on_date) == 1 else None,
    )
    if target_session is None:
        return
    if str(_value(target_session, "completion_status") or "").lower() not in {"planned", "done"}:
        return
    updated_session = repo.set_scheduled_session_status(db, int(_value(target_session, "id")), "skipped")
    if updated_session is None:
        return
    _, day_plan = repo.get_current_week_day_plan_for_session(db, user=user, session=updated_session)
    if day_plan is not None and str(day_plan.completion_status or "").lower() == "done":
        day_plan.completion_status = "skipped"
        db.commit()


def _render_applied_decision_reply(
    *,
    decision: MutationDecision,
    updated_session,
    fallback_text: str,
) -> str:
    if decision.mutation_type != "replace_session":
        return fallback_text
    title = str(_value(updated_session, "session_title") or decision.new_title or "seance adaptee").strip()
    duration_min = _value(updated_session, "duration_min") or decision.new_duration_min
    intensity = str(_value(updated_session, "intensity") or decision.new_intensity or "").strip().lower()
    parts = [f"OK. Je bascule sur {title.lower()}."]
    detail_bits: list[str] = []
    if duration_min:
        detail_bits.append(f"{int(duration_min)} min")
    intensity_labels = {
        "easy": "facile",
        "moderate": "controle",
        "hard": "soutenu",
    }
    if intensity in intensity_labels:
        detail_bits.append(intensity_labels[intensity])
    if detail_bits:
        parts.append(f"{', '.join(detail_bits).capitalize()}.")
    if decision.rationale:
        parts.append(decision.rationale)
    return " ".join(parts)


def _sanitize_no_change_reply(*, user_text: str, reply_text: str, decision: MutationDecision) -> str:
    if decision.mutation_type != "no_change":
        return reply_text
    normalized_reply = _normalize_text(reply_text)
    if not any(marker in normalized_reply for marker in _NO_CHANGE_MUTATION_MARKERS):
        return reply_text
    normalized_user = _normalize_text(user_text)
    if any(marker in normalized_user for marker in _LOAD_RECALIBRATION_MARKERS):
        return (
            "Tu as raison. Vu la semaine reelle, on ne repart pas comme si tout avait ete encaisse. "
            "On doit recalibrer la suite plus simple avant de recharger."
        )
    return (
        "Je reste propre sur les faits: tant qu'un changement n'est pas applique au planning, "
        "je n'en parle pas comme si c'etait deja fait."
    )


@router.post("/api/v0/messages", response_model=MessageReply)
def post_message(payload: IncomingMessage, db: Session = Depends(get_db)) -> MessageReply:
    from fitmas.conversation_pipeline import run_conversation_turn

    try:
        return run_conversation_turn(
            ConversationTurnInput(text=payload.text),
            db=db,
            dependencies=ConversationPipelineDependencies(
                decide=decide,
                extract_facts=extract_facts,
                check_and_adapt_health_facts=check_and_adapt_health_facts,
                interpret_user_indication=interpret_user_indication,
            ),
        )
    except ConversationUserNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
