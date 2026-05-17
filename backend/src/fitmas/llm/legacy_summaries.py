from __future__ import annotations


def make_plan_summary(days: list) -> str:
    """Build a compact plan summary to inject into the LLM prompt."""
    lines = []
    for d in days:
        lines.append(
            f"- {d.label} ({d.day}): [{getattr(d, 'sport_type', 'running')}] {d.session_title} — {d.session_goal} "
            f"(priorite: {d.priority}, flexibilite: {d.flexibility})"
        )
    return "\n".join(lines)


def make_timeline_summary(sessions: list) -> str:
    lines = []
    for session in sessions:
        day = getattr(session, "day", "")
        date_value = getattr(session, "scheduled_date", "")
        sport_type = getattr(session, "sport_type", "running")
        session_type = getattr(session, "session_type", "")
        status = getattr(session, "completion_status", "planned")
        slot = _timeline_slot_kind(session)
        movable_target = slot == "free_flexible"
        status_key = str(status or "").strip().lower()
        can_swap_with_training = slot in {"training", "free_flexible"} and status_key not in {"done", "skipped", "canceled"}
        swappable = can_swap_with_training
        lines.append(
            f"- id={getattr(session, 'id', '?')} | date={date_value} | day={day} | "
            f"slot={slot} | movable_target={str(movable_target).lower()} | "
            f"swappable={str(swappable).lower()} | "
            f"can_swap_with_training={str(can_swap_with_training).lower()} | [{sport_type}/{session_type}] "
            f"{getattr(session, 'session_title', '')} | goal={getattr(session, 'session_goal', '')} | status={status}"
        )
    return "\n".join(lines)


def _timeline_slot_kind(session: object) -> str:
    sport = str(getattr(session, "sport_type", "") or "").strip().lower()
    session_type = str(getattr(session, "session_type", "") or "").strip().lower()
    status = str(getattr(session, "completion_status", "") or "").strip().lower()
    if status in {"done", "skipped", "canceled"}:
        return "closed"
    recovery_like = sport in {"rest", "off", ""} or session_type in {"rest", "recovery", "mobility"}
    if recovery_like:
        return "free_flexible"
    return "training"
