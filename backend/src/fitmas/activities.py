from __future__ import annotations

from datetime import datetime, timedelta

from fitmas.models import DayPlan
from fitmas.planner import normalize_sports


def normalize_activity_sport(raw_sport: str) -> str:
    values = normalize_sports([raw_sport])
    return values[0] if values else "running"


def infer_activity_title(sport_type: str, duration_min: int | None, note: str) -> str:
    if note.strip():
        return note.strip()[:80]

    labels = {
        "running": "Course",
        "cycling": "Velo",
        "swimming": "Natation",
        "climbing": "Escalade",
        "strength": "Renfo",
        "rest": "Recuperation",
    }
    label = labels.get(sport_type, sport_type.capitalize())
    if duration_min:
        return f"{label} {duration_min} min"
    return label


def is_activity_this_week(started_at: datetime | None, plan_created_at: datetime | None) -> bool:
    """Only match activities from the current plan week."""
    if not started_at:
        return False
    if plan_created_at is None:
        return True

    plan_week_start = plan_created_at.date() - timedelta(days=plan_created_at.weekday())
    plan_week_end = plan_week_start + timedelta(days=6)
    return plan_week_start <= started_at.date() <= plan_week_end


def match_activity_to_day(
    *,
    sport_type: str,
    started_at: datetime | None,
    duration_min: int | None,
    week_days: list[DayPlan],
    plan_created_at: datetime | None = None,
) -> tuple[str | None, str]:
    if not week_days:
        return None, ""

    # Don't match old activities to current plan
    if not is_activity_this_week(started_at, plan_created_at):
        return None, "activite hors semaine courante"

    candidate_scores: list[tuple[int, DayPlan, str]] = []
    started_day = started_at.strftime("%A").lower() if started_at else None

    for day in week_days:
        if day.sport_type != sport_type:
            continue

        score = 0
        reasons: list[str] = []

        score += 4
        reasons.append("meme sport")

        if started_day and day.day.value == started_day:
            score += 3
            reasons.append("meme jour")

        if duration_min and day.duration_min:
            delta = abs(duration_min - day.duration_min)
            if delta <= 15:
                score += 2
                reasons.append("duree proche")
            elif delta <= 30:
                score += 1
                reasons.append("duree compatible")

        if day.flexibility == "flexible":
            score += 1
            reasons.append("jour flexible")

        if score > 0:
            candidate_scores.append((score, day, ", ".join(reasons)))

    if not candidate_scores:
        return None, ""

    candidate_scores.sort(key=lambda item: item[0], reverse=True)
    best = candidate_scores[0]
    return best[1].day.value, best[2]
