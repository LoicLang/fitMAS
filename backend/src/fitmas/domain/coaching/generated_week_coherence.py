from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Sequence

from fitmas.domain.planning.plan_patch import PlanPatch, PlanPatchOperation, PlanPatchValidation, validate_plan_patch
from fitmas.core.time_context import current_week_dates, get_local_now
from fitmas.domain.planning.week_coherence import (
    WeekCoherenceReview,
    aggregate_week_coherence_policy,
    build_week_coherence_context,
    review_week_coherence_with_llm,
)


class GeneratedWeekCoherenceBlocked(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class GeneratedWeekCoherenceResult:
    week: dict[str, Any]
    patch: PlanPatch
    validation: PlanPatchValidation
    review: WeekCoherenceReview
    policy_status: str
    used_fallback: bool = False


def guard_generated_week_coherence(
    enriched_week: dict[str, Any],
    *,
    timezone_name: str | None,
    now: datetime | None = None,
    activities: Sequence[Any] = (),
    active_facts: Sequence[Any] = (),
    request_json_fn: Callable[..., Any] | None = None,
) -> GeneratedWeekCoherenceResult:
    """Review a generated week before it is persisted as ScheduledSessions."""
    result = _review_generated_week(
        enriched_week,
        timezone_name=timezone_name,
        now=now,
        activities=activities,
        active_facts=active_facts,
        request_json_fn=request_json_fn,
    )
    if _review_allows_generated_week(result):
        return result

    fallback_week = _conservative_fallback_week(enriched_week, review_summary=result.review.summary)
    fallback = _review_generated_week(
        fallback_week,
        timezone_name=timezone_name,
        now=now,
        activities=activities,
        active_facts=active_facts,
        request_json_fn=request_json_fn,
        used_fallback=True,
    )
    if _review_blocks_generated_week(fallback):
        raise GeneratedWeekCoherenceBlocked(fallback.review.summary)
    return fallback


def _review_generated_week(
    enriched_week: dict[str, Any],
    *,
    timezone_name: str | None,
    now: datetime | None,
    activities: Sequence[Any],
    active_facts: Sequence[Any],
    request_json_fn: Callable[..., Any] | None,
    used_fallback: bool = False,
) -> GeneratedWeekCoherenceResult:
    patch = _plan_patch_from_generated_week(enriched_week, timezone_name=timezone_name, now=now)
    validation = validate_plan_patch(
        None,  # create-session validation does not require DB access.
        plan_id=0,
        patch=patch,
        scheduled_sessions=(),
        timezone_name=timezone_name,
        now=now,
    )
    context = build_week_coherence_context(
        patch=patch,
        validation=validation,
        scheduled_sessions=(),
        activities=activities,
        active_facts=active_facts,
        timezone_name=timezone_name,
    )
    review = review_week_coherence_with_llm(
        context,
        request_json_fn=request_json_fn or _request_week_coherence_json,
    )
    policy_status = aggregate_week_coherence_policy(
        patch_validation=validation,
        week_review=review,
        deterministic_checks=context.deterministic_checks,
        allow_requires_confirmation=False,
    )
    return GeneratedWeekCoherenceResult(
        week=enriched_week,
        patch=patch,
        validation=validation,
        review=review,
        policy_status=policy_status,
        used_fallback=used_fallback,
    )


def _plan_patch_from_generated_week(
    enriched_week: dict[str, Any],
    *,
    timezone_name: str | None,
    now: datetime | None,
) -> PlanPatch:
    week_dates = current_week_dates(timezone_name, now=now)
    today = get_local_now(timezone_name, now=now).date()
    operations: list[PlanPatchOperation] = []
    for day in enriched_week.get("days") or []:
        if not isinstance(day, dict) or not _is_active_training_day(day):
            continue
        day_key = str(day.get("day") or "").strip()
        target_date = week_dates.get(day_key)
        if target_date is None or target_date < today:
            continue
        duration_min = _positive_int(day.get("duration_min"))
        if duration_min is None:
            continue
        operations.append(
            PlanPatchOperation(
                operation_type="create_session",
                target_date=target_date.isoformat(),
                new_title=str(day.get("session_title") or "Seance generee").strip(),
                new_goal=str(day.get("session_goal") or "").strip() or None,
                new_sport_type=str(day.get("sport_type") or "").strip(),
                new_session_type=str(day.get("session_type") or "easy").strip(),
                new_duration_min=duration_min,
                new_intensity=str(day.get("intensity") or "easy").strip(),
                new_description=str(day.get("session_description") or "").strip() or None,
                rationale=f"Semaine generee avant commit: {day_key}.",
            )
        )
    return PlanPatch(
        coach_message="Review sportive de la semaine generee avant commit.",
        operations=operations,
    )


def _conservative_fallback_week(enriched_week: dict[str, Any], *, review_summary: str) -> dict[str, Any]:
    fallback = deepcopy(enriched_week)
    fallback["summary"] = "Semaine allegee par prudence: on garde du mouvement facile sans ajouter de charge dure."
    for day in fallback.get("days") or []:
        if not isinstance(day, dict) or not _is_active_training_day(day):
            continue
        day["intensity"] = "easy"
        day["load_score"] = min(_int(day.get("load_score"), default=1), 1)
        day["duration_min"] = min(_int(day.get("duration_min"), default=30), 45)
        day["priority"] = "Support"
        if str(day.get("sport_type") or "").strip().lower() == "strength":
            day["session_type"] = "mobility"
            day["session_title"] = "Mobilite facile"
        else:
            day["session_type"] = "easy"
            title = str(day.get("session_title") or "Seance facile").strip()
            day["session_title"] = f"{title} - version facile"
        day["session_goal"] = "Garder le mouvement sans ajouter de charge dure."
        day["session_note"] = "Version allegee par prudence."
    return fallback


def _review_allows_generated_week(result: GeneratedWeekCoherenceResult) -> bool:
    return result.policy_status == "valid"


def _review_blocks_generated_week(result: GeneratedWeekCoherenceResult) -> bool:
    return result.policy_status == "blocked"


def _is_active_training_day(day: dict[str, Any]) -> bool:
    sport = str(day.get("sport_type") or "").strip().lower()
    return sport not in {"", "rest", "off"}


def _positive_int(value: Any) -> int | None:
    parsed = _int(value, default=0)
    return parsed if parsed > 0 else None


def _int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _request_week_coherence_json(**kwargs) -> dict[str, Any] | None:
    from fitmas.domain.planning.patch_mutation_service import _request_week_coherence_json as request_json

    return request_json(**kwargs)
