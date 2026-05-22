from __future__ import annotations

from fitmas import repository as repo
from fitmas.app.telegram.delivery import CoachDraft, persist_draft
from fitmas.core.db import SessionLocal
from fitmas.app.telegram.channel import resolve_chat_id

DAY_LABELS = {
    "monday": "Lundi",
    "tuesday": "Mardi",
    "wednesday": "Mercredi",
    "thursday": "Jeudi",
    "friday": "Vendredi",
    "saturday": "Samedi",
    "sunday": "Dimanche",
}

SPORT_EMOJIS = {
    "running": "🏃",
    "cycling": "🚴",
    "swimming": "🏊",
    "climbing": "🧗",
    "strength": "💪",
    "rest": "🛌",
}


def resolve_owner_chat_id() -> int | None:
    db = SessionLocal()
    try:
        return resolve_chat_id(db)
    finally:
        db.close()


def persist_draft_for_owner(draft: CoachDraft) -> None:
    db = SessionLocal()
    try:
        user = repo.get_user_optional(db)
        if user:
            persist_draft(user.id, draft, db=db)
    finally:
        db.close()


def format_week_overview(week: dict, *, heading: str | None = None) -> str:
    lines: list[str] = []
    if heading:
        lines.append(heading)
        lines.append("")
    if week.get("intention"):
        lines.append(f"*{week['intention']}*")
    if week.get("summary"):
        lines.append(week["summary"])
    if week.get("intention") or week.get("summary"):
        lines.append("")
    for day in week.get("days", []):
        emoji = SPORT_EMOJIS.get(day.get("sport_type", "rest"), "⚪")
        lines.append(f"{emoji} *{day['label']}* — {day['session_title']}")
    return "\n".join(lines).strip()


def persistable_plan_draft(week: dict) -> CoachDraft:
    return CoachDraft(
        text=format_week_overview(week, heading="*Nouvelle semaine:*"),
        proactive=True,
    )
