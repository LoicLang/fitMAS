"""FitMAS Heartbeat — proactive coach messages.

Runs on a schedule and evaluates whether to send a message to the user.
Three trigger types:
  1. Morning briefing (07:30) — summary of today's session
  2. Pre-session reminder (18:00 the day before a key session)
  3. Weekly review (Sunday 20:00) — recap + next week preparation
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime

from sqlalchemy.orm import Session

from fitmas import repository as repo, schema as s
from fitmas.db import SessionLocal

logger = logging.getLogger(__name__)

# Minimum hours between proactive coach messages
PROACTIVE_COOLDOWN_HOURS = 4
# Minimum hours since last user exchange before sending a pre-session reminder
RECENT_EXCHANGE_HOURS = 2

DAY_MAP = {
    0: "monday", 1: "tuesday", 2: "wednesday",
    3: "thursday", 4: "friday", 5: "saturday", 6: "sunday",
}

DAY_LABELS = {
    "monday": "Lundi", "tuesday": "Mardi", "wednesday": "Mercredi",
    "thursday": "Jeudi", "friday": "Vendredi", "saturday": "Samedi",
    "sunday": "Dimanche",
}

NEXT_DAY = {
    "monday": "tuesday", "tuesday": "wednesday", "wednesday": "thursday",
    "thursday": "friday", "friday": "saturday", "saturday": "sunday",
    "sunday": "monday",
}


def _get_today_key() -> str:
    return DAY_MAP[datetime.now().weekday()]


def _check_cooldown(db: Session, user_id: int, cooldown_hours: float = PROACTIVE_COOLDOWN_HOURS) -> bool:
    """Return True if enough time has passed since the last proactive agent message."""
    last_agent_msg = (
        db.query(s.CoachMessage)
        .filter(s.CoachMessage.user_id == user_id, s.CoachMessage.role == "agent")
        .order_by(s.CoachMessage.created_at.desc())
        .first()
    )
    if not last_agent_msg or not last_agent_msg.created_at:
        return True  # no previous message, ok to send
    elapsed = (datetime.now() - last_agent_msg.created_at).total_seconds() / 3600
    if elapsed < cooldown_hours:
        logger.info("Cooldown active: last agent msg %.1fh ago (need %.1fh)", elapsed, cooldown_hours)
        return False
    return True


def _had_recent_exchange(db: Session, user_id: int, hours: float = RECENT_EXCHANGE_HOURS) -> bool:
    """Return True if the user sent a message recently."""
    last_user_msg = (
        db.query(s.CoachMessage)
        .filter(s.CoachMessage.user_id == user_id, s.CoachMessage.role == "user")
        .order_by(s.CoachMessage.created_at.desc())
        .first()
    )
    if not last_user_msg or not last_user_msg.created_at:
        return False
    elapsed = (datetime.now() - last_user_msg.created_at).total_seconds() / 3600
    return elapsed < hours


def _llm_generate(system: str, prompt: str) -> str | None:
    """Call the LLM for heartbeat messages. Returns None on failure."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception:
        logger.exception("Heartbeat LLM call failed")
        return None


def morning_briefing() -> str | None:
    """Generate the morning briefing message for today, aware of yesterday's status."""
    db = SessionLocal()
    try:
        user = repo.get_user(db)

        # Cooldown: don't spam if we sent something recently
        if not _check_cooldown(db, user.id, cooldown_hours=PROACTIVE_COOLDOWN_HOURS):
            logger.info("Morning briefing skipped — cooldown active")
            return None

        plan = repo.get_active_plan(db, user.id)
        today_key = _get_today_key()
        day = repo.get_day_plan(db, plan.id, today_key)
        if not day:
            return None

        label = DAY_LABELS[today_key]

        # Check yesterday's completion
        yesterday_key, yesterday_status = repo.get_yesterday_status(db, plan.id, today_key)
        yesterday_label = DAY_LABELS.get(yesterday_key or "", "")
        yesterday_day = repo.get_day_plan(db, plan.id, yesterday_key) if yesterday_key else None

        yesterday_context = ""
        if yesterday_day and yesterday_day.sport_type != "rest":
            if yesterday_status == "done":
                yesterday_context = f"\nHier ({yesterday_label}): {yesterday_day.session_title} — fait. Bien."
            elif yesterday_status == "planned":
                yesterday_context = (
                    f"\nHier ({yesterday_label}): {yesterday_day.session_title} — "
                    f"pas marque comme fait. A noter."
                )
            elif yesterday_status in ("skipped", "adapted"):
                yesterday_context = f"\nHier ({yesterday_label}): adapte/saute. On avance."

        # Try LLM-generated briefing
        system = (
            f"Tu es {user.coach_name}, coach multisport IA. "
            f"Style: {user.coach_style}. "
            f"Ton ton: clair, court, direct, chaleureux sans cheerleading. "
            "Tu tutoies toujours. Reponds en francais. Max 3-4 phrases."
        )
        if user.coach_soul:
            system += f"\nAme du coach: {user.coach_soul}"

        prompt = (
            f"Genere un message matinal pour {label}.\n"
            f"Seance: {day.session_title} ({day.sport_type})\n"
            f"Objectif: {day.session_goal}\n"
            f"Priorite: {day.priority}\n"
            f"Note: {day.session_note}"
            f"{yesterday_context}"
        )
        llm_msg = _llm_generate(system, prompt)
        if llm_msg:
            repo.add_message(db, user.id, "agent", llm_msg)
            return llm_msg

        # Fallback: structured message
        msg = f"Bonjour. {label} — {day.session_title}.\n{day.session_goal}. Priorite: {day.priority}."
        if yesterday_context:
            msg += f"\n{yesterday_context.strip()}"
        repo.add_message(db, user.id, "agent", msg)
        return msg
    finally:
        db.close()


def pre_session_reminder() -> str | None:
    """Generate a reminder the evening before a key session."""
    db = SessionLocal()
    try:
        user = repo.get_user(db)

        # Cooldown: don't send if recent proactive message
        if not _check_cooldown(db, user.id, cooldown_hours=PROACTIVE_COOLDOWN_HOURS):
            logger.info("Pre-session reminder skipped — cooldown active")
            return None

        # Skip if user just talked to the coach
        if _had_recent_exchange(db, user.id, hours=RECENT_EXCHANGE_HOURS):
            logger.info("Pre-session reminder skipped — recent exchange")
            return None

        plan = repo.get_active_plan(db, user.id)
        today_key = _get_today_key()
        tomorrow_key = NEXT_DAY[today_key]
        day = repo.get_day_plan(db, plan.id, tomorrow_key)
        if not day:
            return None

        # Only remind before key/important sessions
        key_words = ("cle", "fort", "qualite", "bloc", "longue", "long")
        is_key = any(w in (day.priority + day.session_title).lower() for w in key_words)
        if not is_key:
            logger.info("Tomorrow (%s) is not a key session — skipping reminder", tomorrow_key)
            return None

        label = DAY_LABELS[tomorrow_key]

        system = (
            f"Tu es {user.coach_name}, coach multisport IA. "
            f"Style: {user.coach_style}. "
            "Ton ton: clair, court, direct. "
            "Tu tutoies toujours. Reponds en francais. Max 2 phrases. "
            "Rappelle la seance de demain et demande comment l'utilisateur se sent."
        )
        if user.coach_soul:
            system += f"\nAme du coach: {user.coach_soul}"
        prompt = (
            f"Demain {label}: {day.session_title} — {day.session_goal}.\n"
            f"Priorite: {day.priority}."
        )
        llm_msg = _llm_generate(system, prompt)
        if llm_msg:
            repo.add_message(db, user.id, "agent", llm_msg)
            return llm_msg

        msg = f"Demain c'est {day.session_title}. Tu te sens comment pour {label.lower()} ?"
        repo.add_message(db, user.id, "agent", msg)
        return msg
    finally:
        db.close()


def weekly_review(*, regenerate: bool = True) -> str | None:
    """Generate a Sunday evening weekly review. Optionally regenerate next week's plan."""
    db = SessionLocal()
    try:
        user = repo.get_user(db)
        plan = repo.get_active_plan(db, user.id)

        # Build week summary with completion statuses
        lines = []
        done_count = 0
        planned_count = 0
        for day_row in plan.days:
            label = DAY_LABELS.get(day_row.day, day_row.day)
            status_marker = ""
            if day_row.sport_type != "rest":
                if day_row.completion_status == "done":
                    status_marker = " ✅"
                    done_count += 1
                elif day_row.completion_status == "planned":
                    status_marker = " (pas fait)"
                    planned_count += 1
                elif day_row.completion_status in ("skipped", "adapted"):
                    status_marker = f" ({day_row.completion_status})"
            changed = len(day_row.change_notes) > 0
            if changed:
                status_marker += " (modifie)"
            lines.append(f"- {label}: {day_row.session_title}{status_marker}")
        week_text = "\n".join(lines)

        system = (
            f"Tu es {user.coach_name}, coach multisport IA. "
            f"Style: {user.coach_style}. "
            "Ton ton: clair, court, direct, chaleureux. "
            "Tu tutoies toujours. Reponds en francais. Max 4-5 phrases. "
            "Fais un bilan de la semaine et donne une perspective pour la suivante."
        )
        if user.coach_soul:
            system += f"\nAme du coach: {user.coach_soul}"
        prompt = (
            f"Resume de la semaine:\n{week_text}\n"
            f"Intention: {plan.intention}\n"
            f"Seances faites: {done_count}. Seances prevues non faites: {planned_count}."
        )
        llm_msg = _llm_generate(system, prompt)
        if llm_msg:
            repo.add_message(db, user.id, "agent", llm_msg)
            return llm_msg

        msg = "Fin de semaine. Le plan a tenu ses reperes. On prend de la marge pour la suite."
        repo.add_message(db, user.id, "agent", msg)
        return msg
    finally:
        # Regenerate next week after review
        if regenerate:
            try:
                _regenerate_next_week(db, user)
            except Exception:
                logger.exception("Failed to regenerate week after review")
        db.close()


def _regenerate_next_week(db: Session, user: s.User) -> None:
    """Regenerate a fresh weekly plan after review."""
    from fitmas.planner import build_week_plan
    from fitmas.llm import formulate_week_plan

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
    user_profile = {
        "primary_objective": user.primary_objective,
        "sports": sports,
        "weekly_structure_notes": user.weekly_structure_notes,
        "constraints": constraints,
        "preferences": [p.text for p in user.preferences],
        **coach_profile,
    }

    planner_output = build_week_plan(
        sports=sports,
        weekly_structure_notes=user.weekly_structure_notes,
        constraints=constraints,
        coach_name=user.coach_name,
    )
    enriched = formulate_week_plan(planner_output, user_profile=user_profile, coach_profile=user_profile)
    repo.replace_plan(
        db, user.id,
        intention=enriched["intention"],
        summary=enriched["summary"],
        days=[dict(day) for day in enriched["days"]],
    )
    repo.add_message(db, user.id, "agent", f"Nouvelle semaine posee. {enriched['intention']}")
    logger.info("Next week regenerated for user %s", user.id)
