"""FitMAS Signals — derive actionable signals from plan + activity data.

Each signal function returns a dict (or None) with:
  - kind: str — signal identifier
  - severity: "info" | "warning" | "action"
  - summary: str — human-readable description for the coach LLM
  - data: dict — structured context for downstream use
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from fitmas import repository as repo, schema as s
from fitmas.time_context import DAY_KEYS, DAY_LABELS_FR, build_time_context

logger = logging.getLogger(__name__)

Signal = dict[str, Any]

PREV_DAY = {
    "monday": "sunday", "tuesday": "monday", "wednesday": "tuesday",
    "thursday": "wednesday", "friday": "thursday", "saturday": "friday",
    "sunday": "saturday",
}


def collect_signals(db: Session, user: s.User) -> list[Signal]:
    """Run all signal detectors and return any that fired."""
    plan = repo.get_active_plan(db, user.id)
    time_ctx = build_time_context(user.timezone)
    today_key = time_ctx["day_key"]

    signals: list[Signal] = []

    for detector in (
        _detect_missed_key_session,
        _detect_silence,
        _detect_high_cumulative_load,
        _detect_big_session_done,
        _detect_streak,
    ):
        try:
            signal = detector(db, user, plan, today_key)
            if signal:
                signals.append(signal)
        except Exception:
            logger.exception("Signal detector %s failed", detector.__name__)

    return signals


# ── B2: Missed key session ──────────────────────────────────────────────────

def _detect_missed_key_session(
    db: Session, user: s.User, plan: s.WeeklyPlan, today_key: str,
) -> Signal | None:
    """Fire if yesterday was a key session that wasn't completed."""
    yesterday_key = PREV_DAY[today_key]
    day = repo.get_day_plan(db, plan.id, yesterday_key)
    if not day:
        return None

    # Only care about actual sport sessions (not rest)
    if day.sport_type == "rest":
        return None

    # Only fire for key / important sessions
    key_words = ("cle", "fort", "qualite", "bloc", "longue", "long", "important")
    is_key = any(w in (day.priority + day.session_title + day.session_type).lower() for w in key_words)
    if not is_key:
        return None

    if day.completion_status == "done":
        return None

    label = DAY_LABELS_FR.get(yesterday_key, yesterday_key)
    return {
        "kind": "missed_key_session",
        "severity": "warning",
        "summary": (
            f"Seance cle de {label} ({day.session_title}) non realisee. "
            f"Sport: {day.sport_type}, priorite: {day.priority}."
        ),
        "data": {
            "day": yesterday_key,
            "session_title": day.session_title,
            "sport_type": day.sport_type,
            "priority": day.priority,
        },
    }


# ── B3: Silence (no activity for N days) ────────────────────────────────────

def _detect_silence(
    db: Session, user: s.User, plan: s.WeeklyPlan, today_key: str,
) -> Signal | None:
    """Fire if 3+ consecutive days have no activity and no 'done' status."""
    today_idx = DAY_KEYS.index(today_key)

    silent_days = 0
    for offset in range(1, 4):  # check yesterday, day-before, day-before-that
        check_idx = (today_idx - offset) % 7
        check_key = DAY_KEYS[check_idx]
        day = repo.get_day_plan(db, plan.id, check_key)
        if day and day.sport_type != "rest" and day.completion_status != "done":
            silent_days += 1
        else:
            break  # streak broken

    if silent_days < 3:
        return None

    # Also check if user sent any message in the last 3 days
    last_msg = (
        db.query(s.CoachMessage)
        .filter(s.CoachMessage.user_id == user.id, s.CoachMessage.role == "user")
        .order_by(s.CoachMessage.created_at.desc())
        .first()
    )
    if last_msg and last_msg.created_at:
        hours_since = (datetime.now() - last_msg.created_at).total_seconds() / 3600
        if hours_since < 48:
            return None  # user is active in conversation, just not logging

    return {
        "kind": "silence_3_days",
        "severity": "action",
        "summary": (
            f"{silent_days} jours consecutifs sans activite realisee. "
            "Check-in recommande."
        ),
        "data": {"silent_days": silent_days},
    }


# ── B4: High cumulative load ────────────────────────────────────────────────

def _detect_high_cumulative_load(
    db: Session, user: s.User, plan: s.WeeklyPlan, today_key: str,
) -> Signal | None:
    """Fire if done sessions this week already exceed safe load threshold."""
    total_load = 0
    done_count = 0
    remaining_load = 0

    for day_row in plan.days:
        if day_row.completion_status == "done":
            total_load += day_row.load_score
            done_count += 1
        elif day_row.completion_status == "planned" and day_row.sport_type != "rest":
            remaining_load += day_row.load_score

    # Also factor in actual activity duration vs planned
    recent_activities = (
        db.query(s.Activity)
        .filter(
            s.Activity.user_id == user.id,
            s.Activity.started_at.isnot(None),
            s.Activity.started_at >= datetime.now() - timedelta(days=7),
        )
        .all()
    )

    actual_minutes = sum(a.duration_min or 0 for a in recent_activities)
    planned_done_minutes = sum(
        d.duration_min or 0
        for d in plan.days
        if d.completion_status == "done" and d.duration_min
    )

    # Threshold: load > 18 (out of typical 20-25 weekly) or duration 30%+ over plan
    overload = False
    reason_parts = []

    if total_load >= 18:
        overload = True
        reason_parts.append(f"charge cumulee {total_load} (seuil 18)")

    if planned_done_minutes > 0 and actual_minutes > planned_done_minutes * 1.3:
        overload = True
        reason_parts.append(
            f"duree reelle {actual_minutes}min vs {planned_done_minutes}min prevues (+{int((actual_minutes/planned_done_minutes - 1)*100)}%)"
        )

    if not overload:
        return None

    return {
        "kind": "high_cumulative_load",
        "severity": "warning",
        "summary": f"Charge elevee cette semaine: {', '.join(reason_parts)}. Suggestion: alleger la suite.",
        "data": {
            "total_load": total_load,
            "done_count": done_count,
            "remaining_load": remaining_load,
            "actual_minutes": actual_minutes,
            "planned_done_minutes": planned_done_minutes,
        },
    }


# ── B5: Big session completed ───────────────────────────────────────────────

def _detect_big_session_done(
    db: Session, user: s.User, plan: s.WeeklyPlan, today_key: str,
) -> Signal | None:
    """Fire if a significant session was logged in the last 6 hours."""
    cutoff = datetime.now() - timedelta(hours=6)

    recent = (
        db.query(s.Activity)
        .filter(
            s.Activity.user_id == user.id,
            s.Activity.created_at >= cutoff,
        )
        .order_by(s.Activity.created_at.desc())
        .first()
    )

    if not recent:
        return None

    # "Big" = long duration, high HR, or high elevation
    is_big = False
    reason = []

    if recent.duration_min and recent.duration_min >= 60:
        is_big = True
        reason.append(f"{recent.duration_min}min")

    if recent.avg_hr and recent.avg_hr >= 155:
        is_big = True
        reason.append(f"FC moy {int(recent.avg_hr)}bpm")

    if recent.elevation_m and recent.elevation_m >= 500:
        is_big = True
        reason.append(f"{int(recent.elevation_m)}m D+")

    if recent.distance_m and recent.distance_m >= 15000:
        is_big = True
        reason.append(f"{recent.distance_m/1000:.1f}km")

    if not is_big:
        return None

    return {
        "kind": "big_session_done",
        "severity": "info",
        "summary": (
            f"Grosse seance recente: {recent.title} ({recent.sport_type}) — "
            f"{', '.join(reason)}. Feedback coach recommande."
        ),
        "data": {
            "activity_id": recent.id,
            "title": recent.title,
            "sport_type": recent.sport_type,
            "duration_min": recent.duration_min,
            "distance_m": recent.distance_m,
            "elevation_m": recent.elevation_m,
            "avg_hr": recent.avg_hr,
        },
    }


# ── Bonus: Streak detection ─────────────────────────────────────────────────

def _detect_streak(
    db: Session, user: s.User, plan: s.WeeklyPlan, today_key: str,
) -> Signal | None:
    """Fire if user has completed 3+ consecutive planned sessions."""
    today_idx = DAY_KEYS.index(today_key)
    streak = 0

    for offset in range(1, 8):  # look back up to 7 days
        check_idx = (today_idx - offset) % 7
        check_key = DAY_KEYS[check_idx]
        day = repo.get_day_plan(db, plan.id, check_key)
        if not day:
            break
        if day.sport_type == "rest":
            continue  # rest days don't break streaks
        if day.completion_status == "done":
            streak += 1
        else:
            break

    if streak < 3:
        return None

    return {
        "kind": "streak",
        "severity": "info",
        "summary": f"{streak} seances consecutives realisees. Regularite solide.",
        "data": {"streak": streak},
    }


# ── Signal-based heartbeat messages ─────────────────────────────────────────

def format_signals_for_prompt(signals: list[Signal]) -> str:
    """Format signals into a block for the LLM system prompt."""
    if not signals:
        return ""
    lines = ["Signaux detectes:"]
    for sig in signals:
        icon = {"info": "ℹ️", "warning": "⚠️", "action": "🔴"}.get(sig["severity"], "•")
        lines.append(f"{icon} [{sig['kind']}] {sig['summary']}")
    return "\n".join(lines)
