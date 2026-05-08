"""Terminal heartbeat reply context builders.

These helpers only transform structured heartbeat truth into composer facts.
They never interpret free user text.
"""
from __future__ import annotations

from typing import Any

from fitmas import final_reply
from fitmas.skills.heartbeat.context import HeartbeatContextBundle

_READ_ONLY_FORBIDDEN_CLAIMS = (
    "aucun changement planning n'a ete commit par ce heartbeat read-only",
    "ne pas annoncer de seance deplacee, remplacee, allegee ou verrouillee comme deja faite",
)


def build_briefing_reply_context(
    *,
    bundle: HeartbeatContextBundle,
    time_context: dict[str, str],
    active_fact_lines: list[str] | tuple[str, ...],
) -> final_reply.HeartbeatReplyContext:
    return final_reply.HeartbeatReplyContext(
        role="briefing",
        capability=_capability_label(bundle.capability),
        temporal=_temporal_lines(time_context),
        today_truth=_today_truth_lines(bundle),
        yesterday_truth=_yesterday_truth_lines(bundle),
        week_digest=_week_digest_lines(bundle),
        plan_window=_plan_window_lines(bundle),
        active_facts=_active_reply_facts(active_fact_lines),
        angle="message matinal utile, naturel, sans fiche interne",
        forbidden_claims=_READ_ONLY_FORBIDDEN_CLAIMS,
    )


def build_reminder_reply_context(
    *,
    key_session: Any,
    time_context: dict[str, str],
    active_fact_lines: list[str] | tuple[str, ...],
) -> final_reply.HeartbeatReplyContext:
    return final_reply.HeartbeatReplyContext(
        role="reminder",
        capability="read_only",
        temporal=_temporal_lines(time_context),
        plan_window=(_scheduled_session_line(key_session),),
        active_facts=_active_reply_facts(active_fact_lines),
        angle="rappel pre-seance court, utile, non anxiogene",
        forbidden_claims=_READ_ONLY_FORBIDDEN_CLAIMS,
    )


def build_review_reply_context(
    *,
    week_sessions: list[Any] | tuple[Any, ...],
    time_context: dict[str, str],
    total_sessions: int,
    done_count: int,
    planned_count: int,
    actual_activity_count: int,
    actual_duration_min: int,
    claimed_activity_count: int,
    claimed_duration_min: int,
    active_fact_lines: list[str] | tuple[str, ...],
    weekly_highlights: str = "",
) -> final_reply.HeartbeatReplyContext:
    week_digest = [
        (
            f"total_sessions={total_sessions} done_count={done_count} "
            f"planned_not_done={planned_count}"
        ),
        (
            f"actual_activity_count={actual_activity_count} "
            f"actual_duration_min={actual_duration_min} "
            f"claimed_activity_count={claimed_activity_count} "
            f"claimed_duration_min={claimed_duration_min}"
        ),
    ]
    if weekly_highlights.strip():
        week_digest.append(f"evenements_explicatifs={weekly_highlights.strip()}")
    return final_reply.HeartbeatReplyContext(
        role="review",
        capability="read_only",
        temporal=_temporal_lines(time_context),
        week_digest=tuple(week_digest),
        plan_window=tuple(_scheduled_session_line(session) for session in week_sessions),
        active_facts=_active_reply_facts(active_fact_lines),
        angle="bilan hebdo utile, factuel, sans recitation",
        forbidden_claims=_READ_ONLY_FORBIDDEN_CLAIMS,
    )


def _capability_label(capability: Any) -> str:
    if getattr(capability, "read_only", False):
        return "read_only"
    if getattr(capability, "can_emit_candidate", False):
        return "candidate_only"
    return "message_only"


def _temporal_lines(time_context: dict[str, str]) -> tuple[str, ...]:
    pieces = [
        str(time_context.get("date_fr") or time_context.get("date") or "").strip(),
        str(time_context.get("day_label_fr") or time_context.get("day_label") or "").strip(),
        str(time_context.get("time_fr") or time_context.get("time") or "").strip(),
    ]
    line = " ".join(piece for piece in pieces if piece)
    return (line,) if line else ()


def _today_truth_lines(bundle: HeartbeatContextBundle) -> tuple[str, ...]:
    today = bundle.today
    lines = [f"{today.occurred_on.isoformat()} ({today.day_label}) status={today.status}"]
    if today.planned_session is not None:
        lines.append(_planned_session_line(today.planned_session))
    else:
        lines.append("aucune seance planifiee")
    return tuple(lines)


def _yesterday_truth_lines(bundle: HeartbeatContextBundle) -> tuple[str, ...]:
    yesterday = bundle.yesterday
    lines = [
        f"{yesterday.occurred_on.isoformat()} ({yesterday.day_label}) status={yesterday.status}",
        (
            f"linked_activity_count={yesterday.linked_activity_count} "
            f"offplan_activity_count={yesterday.offplan_activity_count} "
            f"claim_count={yesterday.claim_count}"
        ),
    ]
    lines.extend(_planned_session_line(session) for session in yesterday.planned_sessions)
    return tuple(lines)


def _week_digest_lines(bundle: HeartbeatContextBundle) -> tuple[str, ...]:
    week = bundle.week
    return (
        (
            f"{week.window_days}j: planned={week.planned_count} "
            f"confirmed={week.confirmed_count} claimed={week.claimed_count} "
            f"offplan={week.offplan_count} missed_streak_days={week.missed_streak_days}"
        ),
    )


def _plan_window_lines(bundle: HeartbeatContextBundle) -> tuple[str, ...]:
    return tuple(_plan_window_line(session) for session in bundle.plan_window.sessions)


def _planned_session_line(session: Any) -> str:
    pieces = [str(getattr(session, "sport", "") or "sport")]
    title = str(getattr(session, "title", "") or "").strip()
    if title:
        pieces.append(f'"{title}"')
    duration = getattr(session, "duration_min", None)
    if duration is not None:
        pieces.append(f"{duration}min")
    status = str(getattr(session, "completion_status", "") or "").strip()
    if status:
        pieces.append(f"[{status}]")
    return " ".join(pieces)


def _plan_window_line(session: Any) -> str:
    pieces = [
        f"{session.scheduled_date.isoformat()} ({session.day_label})",
        session.sport or "sport",
    ]
    if session.title:
        pieces.append(f'"{session.title}"')
    if session.duration_min is not None:
        pieces.append(f"{session.duration_min}min")
    pieces.append(f"[{session.completion_status}]")
    pieces.append(f"slot={session.slot_kind}")
    return " ".join(pieces)


def _scheduled_session_line(session: Any) -> str:
    pieces: list[str] = []
    scheduled = getattr(session, "scheduled_date", None)
    if scheduled is not None:
        if hasattr(scheduled, "date"):
            scheduled = scheduled.date()
        pieces.append(str(scheduled))
    label = str(getattr(session, "label", "") or "").strip()
    if label:
        pieces.append(f"({label.lower()})")
    pieces.append(str(getattr(session, "sport_type", "") or "sport"))
    title = str(getattr(session, "session_title", "") or "").strip()
    if title:
        pieces.append(f'"{title}"')
    duration = getattr(session, "duration_min", None)
    if duration is not None:
        pieces.append(f"{duration}min")
    status = str(getattr(session, "completion_status", "") or "").strip()
    if status:
        pieces.append(f"[{status}]")
    return " ".join(pieces)


def _active_reply_facts(active_fact_lines: list[str] | tuple[str, ...]) -> tuple[final_reply.HeartbeatReplyFact, ...]:
    return tuple(
        final_reply.HeartbeatReplyFact(category="", value=_fact_line_value(line))
        for line in active_fact_lines
        if _fact_line_value(line)
    )


def _fact_line_value(line: str) -> str:
    return str(line or "").strip().removeprefix("-").strip()
