from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from fitmas import repository as repo, schema as s
from fitmas.api_payloads import OnboardPayload, OnboardPreviewPayload
from fitmas.api_support import apply_onboarding_to_user, build_onboarding_facts, normalized_onboarding_payload
from fitmas.db import get_db
from fitmas.llm import formulate_onboarding_recap, formulate_week_plan, preview_coach_voice
from fitmas.models import OnboardPreview, OnboardResult, WeeklyPlan
from fitmas.periodization import compute_mesocycle_state
from fitmas.planner import build_week_plan
from fitmas.planning_state import refresh_planning_state
from fitmas.time_context import build_time_context

logger = logging.getLogger(__name__)

router = APIRouter()


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
    return formulate_week_plan(
        planner_output,
        user_profile=profile,
        coach_profile=profile,
        time_context=build_time_context(profile.get("timezone")),
    )


def _compute_mesocycle(db: Session, user_id: int):
    """Compute mesocycle state by advancing from the previous plan's mesocycle."""
    current_plan = (
        db.query(s.WeeklyPlan)
        .filter(s.WeeklyPlan.user_id == user_id, s.WeeklyPlan.status == "active")
        .first()
    )
    if current_plan is None:
        return compute_mesocycle_state(total_weeks=1)

    # Advance: current plan's total_weeks = (number - 1) * cycle_length + week
    prev_total = (current_plan.mesocycle_number - 1) * 4 + current_plan.mesocycle_week
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
    )
    enriched["_mesocycle_week"] = mesocycle.week_in_cycle
    enriched["_mesocycle_number"] = mesocycle.cycle_number
    return enriched


@router.post("/api/v0/onboard/preview", response_model=OnboardPreview)
def preview_onboarding(payload: OnboardPreviewPayload) -> OnboardPreview:
    normalized_payload = normalized_onboarding_payload(payload)
    time_context = build_time_context(normalized_payload.get("timezone"))
    recap = formulate_onboarding_recap(normalized_payload, time_context=time_context)
    preview = preview_coach_voice(normalized_payload, time_context=time_context)
    return OnboardPreview(
        normalized_sports=normalized_payload["sports"],
        coach_preview=preview,
        recap=recap,
    )


@router.post("/api/v0/onboard", response_model=OnboardResult)
def onboard(payload: OnboardPayload, db: Session = Depends(get_db)) -> OnboardResult:
    normalized_payload = normalized_onboarding_payload(payload)
    time_context = build_time_context(normalized_payload.get("timezone"))
    recap = formulate_onboarding_recap(normalized_payload, time_context=time_context)

    user = repo.get_user_optional(db)
    if user is None:
        user = s.User(name=normalized_payload["name"])
        db.add(user)
        db.flush()

    apply_onboarding_to_user(user, normalized_payload)
    db.commit()

    repo.replace_user_lists(
        db,
        user,
        sports=normalized_payload["sports"],
        constraints=normalized_payload["constraints"],
        preferences=normalized_payload["preferences"],
    )
    repo.replace_user_facts(db, user.id, build_onboarding_facts(normalized_payload))
    enriched_week = _generate_enriched_week_for_user(db, user)

    db.query(s.CoachMessage).filter(s.CoachMessage.user_id == user.id).delete()
    db.commit()

    repo.add_message(
        db,
        user.id,
        "agent",
        f"{normalized_payload['coach_name']} est en place. Je t'ai pose une premiere semaine qu'on pourra faire bouger intelligemment.",
    )

    plan = repo.replace_plan(
        db,
        user.id,
        intention=enriched_week["intention"],
        summary=enriched_week["summary"],
        days=[dict(day) for day in enriched_week["days"]],
        timezone_name=user.timezone,
        mesocycle_week=enriched_week.get("_mesocycle_week", 1),
        mesocycle_number=enriched_week.get("_mesocycle_number", 1),
    )

    return OnboardResult(recap=recap, week_plan=repo.to_pydantic_plan(plan))


@router.post("/api/v0/week/regenerate", response_model=WeeklyPlan)
def regenerate_week(db: Session = Depends(get_db)) -> WeeklyPlan:
    user = repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")

    enriched_week = _generate_enriched_week_for_user(db, user)
    plan = repo.replace_plan(
        db,
        user.id,
        intention=enriched_week["intention"],
        summary=enriched_week["summary"],
        days=[dict(day) for day in enriched_week["days"]],
        timezone_name=user.timezone,
        mesocycle_week=enriched_week.get("_mesocycle_week", 1),
        mesocycle_number=enriched_week.get("_mesocycle_number", 1),
    )

    logger.info("Week regenerated for user %s (mesocycle %s/%s)", user.id, enriched_week.get("_mesocycle_week", 1), enriched_week.get("_mesocycle_number", 1))
    return repo.to_pydantic_plan(plan)
