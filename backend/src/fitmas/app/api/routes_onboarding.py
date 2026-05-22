from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from fitmas.core import orm as s
from fitmas.app.api.payloads import OnboardPayload, OnboardPreviewPayload
from fitmas.app.api.support import apply_onboarding_to_user, build_onboarding_facts, normalized_onboarding_payload
from fitmas.domain.coaching.calibration_status import build_calibration_status, build_initial_calibration_status
from fitmas.core.db import get_db
from fitmas.domain.coaching.generated_week_coherence import GeneratedWeekCoherenceBlocked, guard_generated_week_coherence
import fitmas.llm.gateway as gw
from fitmas.llm.legacy_onboarding import (
    formulate_onboarding_recap,
    formulate_week_plan,
    preview_coach_voice,
)
from fitmas.domain.memory.profile_memory import replace_profile_memory
from fitmas.app.api.onboarding_models import OnboardPreview, OnboardResult
from fitmas.domain.planning.view_models import WeeklyPlan
from fitmas.app.api.onboarding_contract import build_goal_summary, build_onboarding_setup_preview, build_protected_focus
from fitmas.domain.planning.periodization import compute_mesocycle_state, derive_total_weeks
from fitmas.domain.planning.planner import build_week_plan
from fitmas.domain.planning.planning_state import refresh_planning_state
from fitmas.domain.planning import template_repository as template_repo
from fitmas.core.time_context import build_time_context, get_local_now
from fitmas.domain.athlete import repository as athlete_repo
from fitmas.domain.coaching import repo_conversation
from fitmas.domain.coaching import repository as coaching_repo
from fitmas.domain.execution import repository as execution_repo
from fitmas.domain.memory import repository as memory_repo

logger = logging.getLogger(__name__)

router = APIRouter()

_TITLE_DURATION_RE = re.compile(r"\b\d+\s*min\b", re.IGNORECASE)


def _build_user_profile(user: s.User) -> dict:
    sports = [sport.sport_type for sport in user.sports if sport.active]
    constraints = [c.text for c in user.constraints]
    coach_profile = {
        "coach_name": user.coach_name,
        "coach_style": user.coach_style,
        "coach_relationship": user.coach_relationship,
        "coach_do": user.coach_do,
        "coach_dont": user.coach_dont,
        "coach_soul": user.coach_soul,
    }
    return {
        "primary_objective": user.primary_objective,
        "sports": sports,
        "weekly_structure_notes": user.weekly_structure_notes,
        "constraints": constraints,
        "preferences": [p.text for p in user.preferences],
        "timezone": user.timezone,
        **coach_profile,
    }


def _generate_enriched_week(profile: dict) -> dict:
    planner_output = build_week_plan(
        sports=profile["sports"],
        weekly_structure_notes=profile["weekly_structure_notes"],
        constraints=profile["constraints"],
        coach_name=profile["coach_name"],
    )
    enriched = formulate_week_plan(
        planner_output,
        user_profile=profile,
        coach_profile=profile,
        time_context=build_time_context(profile.get("timezone")),
        request_json_fn=gw.request_json,
    )
    return _normalize_generated_week_text_durations(enriched)


def _normalize_generated_week_text_durations(week: dict) -> dict:
    normalized = dict(week)
    normalized_days: list[dict] = []
    for raw_day in week.get("days", []):
        day = dict(raw_day)
        if _rest_day_has_active_structured_payload(day):
            day = _clean_generated_rest_day(day)
            normalized_days.append(day)
            continue
        duration_min = day.get("duration_min")
        title = str(day.get("session_title") or "")
        if isinstance(duration_min, int) and duration_min > 0 and title:
            day["session_title"] = _TITLE_DURATION_RE.sub(f"{duration_min}min", title, count=1)
        normalized_days.append(day)
    normalized["days"] = normalized_days
    return normalized


def _rest_day_has_active_structured_payload(day: dict) -> bool:
    sport_type = str(day.get("sport_type") or "").strip().lower()
    if sport_type not in {"rest", "off"}:
        return False
    duration_min = day.get("duration_min")
    try:
        has_duration = int(duration_min or 0) > 0
    except (TypeError, ValueError):
        has_duration = False
    try:
        has_load = int(day.get("load_score") or 0) > 0
    except (TypeError, ValueError):
        has_load = False
    has_description = bool(str(day.get("session_description") or "").strip())
    session_type = str(day.get("session_type") or "").strip().lower()
    has_active_type = bool(session_type and session_type not in {"rest", "off"})
    return has_duration or has_load or has_description or has_active_type


def _clean_generated_rest_day(day: dict) -> dict:
    cleaned = dict(day)
    cleaned.update(
        {
            "sport_type": "rest",
            "session_type": "rest",
            "session_title": "Repos",
            "session_goal": "Recuperer.",
            "session_note": "Repos.",
            "session_description": "",
            "duration_min": None,
            "intensity": "easy",
            "load_score": 0,
            "priority": "Souplesse",
            "nutrition_focus": "",
            "flexibility": "flexible",
            "watch_items": [],
        }
    )
    return cleaned


def _compute_mesocycle(db: Session, user_id: int):
    """Compute mesocycle state by advancing from the latest persisted total weeks."""
    current_plan = (
        db.query(s.WeeklyPlan)
        .filter(s.WeeklyPlan.user_id == user_id, s.WeeklyPlan.status == "active")
        .first()
    )
    if current_plan is None:
        return compute_mesocycle_state(total_weeks=1)

    prev_total = int(getattr(current_plan, "total_weeks", 0) or 0)
    if prev_total < 1:
        prev_total = derive_total_weeks(
            mesocycle_number=current_plan.mesocycle_number,
            mesocycle_week=current_plan.mesocycle_week,
        )
    return compute_mesocycle_state(total_weeks=prev_total + 1)


def _generate_enriched_week_for_user(db: Session, user: s.User) -> dict:
    profile = _build_user_profile(user)
    planning_bundle = refresh_planning_state(db, user=user)
    mesocycle = _compute_mesocycle(db, user.id)
    planner_output = build_week_plan(
        sports=profile["sports"],
        weekly_structure_notes=profile["weekly_structure_notes"],
        constraints=profile["constraints"],
        coach_name=profile["coach_name"],
        planning_decision=planning_bundle.decision,
        athlete_profile=planning_bundle.profile,
        zones=planning_bundle.zones,
        cycle_week=mesocycle.week_in_cycle,
    )
    enriched = formulate_week_plan(
        planner_output,
        user_profile=profile,
        coach_profile=profile,
        time_context=build_time_context(profile.get("timezone")),
        request_json_fn=gw.request_json,
    )
    enriched = _normalize_generated_week_text_durations(enriched)
    enriched["_mesocycle_week"] = mesocycle.week_in_cycle
    enriched["_mesocycle_number"] = mesocycle.cycle_number
    enriched["_total_weeks"] = mesocycle.total_weeks
    review = guard_generated_week_coherence(
        enriched,
        timezone_name=user.timezone,
        activities=execution_repo.get_activities(db, user.id, limit=120),
        active_facts=_active_facts_for_generated_week_review(db, user.id),
    )
    if review.used_fallback:
        logger.warning(
            "generated_week.week_coherence_fallback user=%s summary=%s",
            user.id,
            review.review.summary,
        )
    return _normalize_generated_week_text_durations(review.week)


@router.post("/api/v0/onboard/preview", response_model=OnboardPreview)
def preview_onboarding(payload: OnboardPreviewPayload) -> OnboardPreview:
    normalized_payload = normalized_onboarding_payload(payload)
    time_context = build_time_context(normalized_payload.get("timezone"))
    recap = formulate_onboarding_recap(normalized_payload, time_context=time_context, request_text_fn=gw.request_text)
    preview = preview_coach_voice(normalized_payload, time_context=time_context, request_json_fn=gw.request_json)
    calibration_status = build_initial_calibration_status(normalized_payload)
    return OnboardPreview(
        normalized_sports=normalized_payload["sports"],
        setup_preview=build_onboarding_setup_preview(normalized_payload),
        coach_preview=preview,
        recap=recap,
        calibration_status=calibration_status.as_dict(),
    )


@router.post("/api/v0/onboard", response_model=OnboardResult)
def onboard(payload: OnboardPayload, db: Session = Depends(get_db)) -> OnboardResult:
    normalized_payload = normalized_onboarding_payload(payload)
    time_context = build_time_context(normalized_payload.get("timezone"))
    recap = formulate_onboarding_recap(normalized_payload, time_context=time_context, request_text_fn=gw.request_text)

    user = athlete_repo.get_user_optional(db)
    if user is None:
        user = s.User(name=normalized_payload["name"])
        db.add(user)
        db.flush()

    apply_onboarding_to_user(user, normalized_payload)
    db.commit()

    athlete_repo.replace_user_lists(
        db,
        user,
        sports=normalized_payload["sports"],
        constraints=normalized_payload["constraints"],
        preferences=normalized_payload["preferences"],
    )
    replace_profile_memory(db, user.id, build_onboarding_facts(normalized_payload))
    try:
        enriched_week = _generate_enriched_week_for_user(db, user)
    except GeneratedWeekCoherenceBlocked as exc:
        raise HTTPException(status_code=409, detail="Generated week blocked by sport quality review") from exc
    planning_bundle = refresh_planning_state(db, user=user)
    calibration_status = build_calibration_status(
        profile=planning_bundle.profile,
        memory_items=memory_repo.get_active_memory_items(
            db,
            user.id,
            profile_limit=24,
            working_limit=24,
            include_patterns=True,
            pattern_limit=6,
            total_limit=36,
        ),
        activities=execution_repo.get_activities(db, user.id, limit=120),
        adaptation_events=coaching_repo.get_recent_adaptation_events(db, user.id, limit=12),
        today=get_local_now(user.timezone).date(),
    )

    db.query(s.CoachMessage).filter(s.CoachMessage.user_id == user.id).delete()
    db.commit()

    # First coach message — anchor the relationship and show we understood
    sports_str = ", ".join(normalized_payload["sports"][:3])
    coach_name = normalized_payload["coach_name"]
    goal_summary = build_goal_summary(normalized_payload) or normalized_payload["primary_objective"]
    protected_focus = build_protected_focus(normalized_payload)
    first_msg = (
        f"{coach_name} est en place.\n"
        f"Cap retenu: {goal_summary}.\n"
        f"Je pose une premiere semaine autour de {sports_str} en protegeant {protected_focus}.\n"
        f"Statut: {calibration_status.label}.\n"
        f"Si un creneau bouge ou si quelque chose sonne faux, tu me l'ecris et j'ajuste."
    )
    repo_conversation.add_message(db, user.id, "agent", first_msg)

    plan = template_repo.replace_plan(
        db,
        user.id,
        intention=enriched_week["intention"],
        summary=enriched_week["summary"],
        days=[dict(day) for day in enriched_week["days"]],
        timezone_name=user.timezone,
        mesocycle_week=enriched_week.get("_mesocycle_week", 1),
        mesocycle_number=enriched_week.get("_mesocycle_number", 1),
        total_weeks=enriched_week.get("_total_weeks", 1),
    )

    return OnboardResult(
        recap=recap,
        week_plan=template_repo.to_pydantic_plan(plan),
        calibration_status=calibration_status.as_dict(),
    )


@router.post("/api/v0/week/regenerate", response_model=WeeklyPlan)
def regenerate_week(db: Session = Depends(get_db)) -> WeeklyPlan:
    user = athlete_repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")

    try:
        enriched_week = _generate_enriched_week_for_user(db, user)
    except GeneratedWeekCoherenceBlocked as exc:
        raise HTTPException(status_code=409, detail="Generated week blocked by sport quality review") from exc
    plan = template_repo.replace_plan(
        db,
        user.id,
        intention=enriched_week["intention"],
        summary=enriched_week["summary"],
        days=[dict(day) for day in enriched_week["days"]],
        timezone_name=user.timezone,
        mesocycle_week=enriched_week.get("_mesocycle_week", 1),
        mesocycle_number=enriched_week.get("_mesocycle_number", 1),
        total_weeks=enriched_week.get("_total_weeks", 1),
    )

    logger.info("Week regenerated for user %s (mesocycle %s/%s)", user.id, enriched_week.get("_mesocycle_week", 1), enriched_week.get("_mesocycle_number", 1))
    return template_repo.to_pydantic_plan(plan)


def _active_facts_for_generated_week_review(db: Session, user_id: int) -> tuple[dict, ...]:
    try:
        rows = memory_repo.get_active_memory_items(
            db,
            user_id,
            profile_limit=24,
            working_limit=24,
            include_patterns=True,
            pattern_limit=6,
            total_limit=36,
        )
    except Exception:
        logger.warning("generated_week.active_facts_unavailable user=%s", user_id, exc_info=True)
        return ()
    payloads: list[dict] = []
    for row in rows:
        try:
            payloads.append(memory_repo.to_pydantic_fact(row).model_dump())
        except Exception:
            continue
    return tuple(payloads)
