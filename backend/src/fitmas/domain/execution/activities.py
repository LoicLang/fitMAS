from __future__ import annotations

from datetime import date, datetime
from typing import Any

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


def match_activity_to_day(
    *,
    sport_type: str,
    started_at: datetime | None,
    duration_min: int | None,
    scheduled_sessions: list[Any],
) -> tuple[str | None, str]:
    if not scheduled_sessions:
        return None, ""
    activity_date = _activity_local_date(started_at)
    if activity_date is None:
        return None, "activite hors semaine courante"

    candidate_scores: list[tuple[int, Any, str]] = []
    for session in scheduled_sessions:
        if _session_date(session) != activity_date:
            continue
        if _value(session, "sport_type") != sport_type:
            continue
        if str(_value(session, "completion_status") or "").strip().lower() in {"done", "skipped", "canceled"}:
            continue

        score = 0
        reasons: list[str] = []

        score += 4
        reasons.append("meme sport")

        score += 3
        reasons.append("meme jour")

        session_duration = _value(session, "duration_min")
        if duration_min and session_duration:
            delta = abs(duration_min - int(session_duration))
            if delta <= 15:
                score += 2
                reasons.append("duree proche")
            elif delta <= 30:
                score += 1
                reasons.append("duree compatible")

        if _value(session, "flexibility") == "flexible":
            score += 1
            reasons.append("jour flexible")

        if score > 0:
            candidate_scores.append((score, session, ", ".join(reasons)))

    if not candidate_scores:
        return None, ""

    candidate_scores.sort(key=lambda item: item[0], reverse=True)
    best = candidate_scores[0]
    return str(_value(best[1], "day") or ""), best[2]


def _activity_local_date(started_at: datetime | None) -> date | None:
    if started_at is None:
        return None
    return started_at.date()


def _session_date(session: Any) -> date | None:
    raw = _value(session, "scheduled_date")
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    if raw:
        try:
            return date.fromisoformat(str(raw)[:10])
        except ValueError:
            return None
    return None


def _value(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)
