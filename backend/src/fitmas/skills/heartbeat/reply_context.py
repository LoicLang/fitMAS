"""Terminal heartbeat reply context builders.

These helpers only transform structured heartbeat truth into composer facts.
They never interpret free user text.
"""
from __future__ import annotations

from typing import Any

from fitmas import final_reply
from fitmas.skills.heartbeat.context import HeartbeatContextBundle


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
        active_facts=tuple(
            final_reply.HeartbeatReplyFact(category="", value=_fact_line_value(line))
            for line in active_fact_lines
            if _fact_line_value(line)
        ),
        angle="message matinal utile, naturel, sans fiche interne",
        forbidden_claims=(
            "aucun changement planning n'a ete commit par ce heartbeat read-only",
            "ne pas annoncer de seance deplacee, remplacee, allegee ou verrouillee comme deja faite",
        ),
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


def _fact_line_value(line: str) -> str:
    return str(line or "").strip().removeprefix("-").strip()
