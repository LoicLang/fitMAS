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
    """Generate the morning briefing message for today."""
    db = SessionLocal()
    try:
        user = repo.get_user(db)
        plan = repo.get_active_plan(db, user.id)
        today_key = _get_today_key()
        day = repo.get_day_plan(db, plan.id, today_key)
        if not day:
            return None

        label = DAY_LABELS[today_key]

        # Try LLM-generated briefing
        system = (
            "Tu es FitMAS, coach running IA. Ton ton: clair, court, direct, chaleureux sans cheerleading. "
            "Tu tutoies toujours. Reponds en francais. Max 2-3 phrases."
        )
        prompt = (
            f"Genere un message matinal pour {label}.\n"
            f"Seance: {day.session_title}\n"
            f"Objectif: {day.session_goal}\n"
            f"Priorite: {day.priority}\n"
            f"Note: {day.session_note}"
        )
        llm_msg = _llm_generate(system, prompt)
        if llm_msg:
            # Save to DB
            repo.add_message(db, user.id, "agent", llm_msg)
            return llm_msg

        # Fallback: structured message
        msg = (
            f"Bonjour. {label} — {day.session_title}.\n"
            f"{day.session_goal}. Priorite: {day.priority}."
        )
        repo.add_message(db, user.id, "agent", msg)
        return msg
    finally:
        db.close()


def pre_session_reminder() -> str | None:
    """Generate a reminder the evening before a key session."""
    db = SessionLocal()
    try:
        user = repo.get_user(db)
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
            "Tu es FitMAS, coach running IA. Ton ton: clair, court, direct. "
            "Tu tutoies toujours. Reponds en francais. Max 2 phrases. "
            "Rappelle la seance de demain et demande comment l'utilisateur se sent."
        )
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


def weekly_review() -> str | None:
    """Generate a Sunday evening weekly review."""
    db = SessionLocal()
    try:
        user = repo.get_user(db)
        plan = repo.get_active_plan(db, user.id)

        # Build week summary
        lines = []
        for day_row in plan.days:
            label = DAY_LABELS.get(day_row.day, day_row.day)
            changed = len(day_row.change_notes) > 0
            marker = " (modifie)" if changed else ""
            lines.append(f"- {label}: {day_row.session_title}{marker}")
        week_text = "\n".join(lines)

        system = (
            "Tu es FitMAS, coach running IA. Ton ton: clair, court, direct, chaleureux. "
            "Tu tutoies toujours. Reponds en francais. Max 4-5 phrases. "
            "Fais un bilan de la semaine et donne une perspective pour la suivante."
        )
        prompt = f"Resume de la semaine:\n{week_text}\nIntention: {plan.intention}"
        llm_msg = _llm_generate(system, prompt)
        if llm_msg:
            repo.add_message(db, user.id, "agent", llm_msg)
            return llm_msg

        msg = "Fin de semaine. Le plan a tenu ses reperes. On prend de la marge pour la suite."
        repo.add_message(db, user.id, "agent", msg)
        return msg
    finally:
        db.close()
