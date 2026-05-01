from __future__ import annotations

import logging
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from fitmas import repository as repo
from fitmas.adaptation import check_and_adapt_health_facts
from fitmas.activity_helpers import claimed_activities_last_days
from fitmas.api_payloads import IncomingMessage
from fitmas.availability_constraints import parse_availability_fact_key
from fitmas.conversation_contract import ConversationPipelineDependencies, ConversationTurnInput, ConversationUserNotFoundError
from fitmas.conversation_turn_planner import plan_conversation_turn
from fitmas.db import get_db
from fitmas.execution_clarification import (
    ExecutionClarification,
    build_execution_clarification,
    looks_like_execution_clarification_prompt,
)
from fitmas.llm import decide, extract_facts, make_timeline_summary, select_prompt_facts
from fitmas.memory_profile import upsert_profile_memory
from fitmas.memory_routing import split_memory_payloads
from fitmas.models import DayId, MessageReply
from fitmas.time_context import get_timezone

logger = logging.getLogger(__name__)

router = APIRouter()

_DAY_VALUES = {d.value for d in DayId}


def _resolve_day_updated(decision) -> DayId | None:
    """Extract the affected day from a structured mutation decision."""
    target = decision.to_day or decision.from_day
    if target and target in _DAY_VALUES:
        return DayId(target)
    return None


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


def _targeted_execution_clarification(
    *,
    db: Session,
    user,
    conversation_context,
    previous_agent_text: str | None,
) -> ExecutionClarification | None:
    if looks_like_execution_clarification_prompt(previous_agent_text):
        return None

    today = conversation_context.temporal_resolution.local_date
    yesterday = today.fromordinal(today.toordinal() - 1)

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

    # Chantier 4 : skip la clarification si la séance d'hier tombe dans une
    # contrainte d'indisponibilité encore active (ex : "piscine fermée 2
    # semaines" → ne pas redemander "tu l'as faite ou pas ?" pour la natation
    # de lundi qui tombe dans la fenêtre).
    if _yesterday_session_covered_by_active_constraint(
        db=db,
        user=user,
        yesterday_session=yesterday_sessions[0],
        yesterday=yesterday,
    ):
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


def _yesterday_session_covered_by_active_constraint(
    *,
    db: Session,
    user,
    yesterday_session,
    yesterday: date,
) -> bool:
    """Retourne True si une `UserFact` availability active recouvre la séance
    d'hier (date dans la fenêtre ET sport match ou sport non spécifié).

    Filtrage par `fact_is_current` effectué en amont via
    `repo.get_active_facts`, donc on n'a pas à re-vérifier `expires_at`."""
    active_facts = repo.get_active_facts(db, user.id, limit=60)
    session_sport = str(_value(yesterday_session, "sport_type") or "").strip().lower() or None
    for fact in active_facts:
        if str(_value(fact, "category") or "").lower() != "availability":
            continue
        parsed = parse_availability_fact_key(_value(fact, "key"))
        if parsed is None:
            continue
        if not (parsed.start_date <= yesterday <= parsed.end_date):
            continue
        if parsed.sport_type is None:
            # contrainte générale (voyage, indispo totale) → couvre tout
            return True
        if session_sport is not None and parsed.sport_type == session_sport:
            return True
    return False


def _latest_agent_text(conversation_history: list[dict]) -> str | None:
    for msg in reversed(conversation_history):
        if msg.get("role") == "agent":
            return str(msg.get("text") or "")
    return None


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
                plan_turn=plan_conversation_turn,
            ),
        )
    except ConversationUserNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
