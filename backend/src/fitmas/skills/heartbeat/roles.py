"""Heartbeat roles — bounded capability profiles for proactive messages.

Each role defines:
- What data it can read (tool budget)
- What side effects it can trigger (write permissions)
- How to build its prompt
- What output shape it produces

Roles are composed in heartbeat.py which handles gating and delivery.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Sequence

from sqlalchemy.orm import Session

from fitmas import repository as repo, schema as s
from fitmas.activity_helpers import (
    activities_last_days as _activities_last_days,
    activities_on_local_date as _activities_on_local_date,
    claimed_activities_last_days as _claimed_activities_last_days,
    claimed_activities_on_local_date as _claimed_activities_on_local_date,
)
from fitmas.athlete_profile import build_athlete_profile
from fitmas.calibration_needs import (
    CalibrationNeedType,
    detect_calibration_need,
    looks_like_clarification_message,
    render_hidden_need_brief,
)
from fitmas.calibration_status import build_calibration_status
from fitmas.coach_messages import CoachDraft
from fitmas.execution_clarification import build_execution_clarification
from fitmas.execution_evidence import classify_execution_evidence
from fitmas.fact_memory import fact_is_current
from fitmas.knowledge import load_sport_knowledge
from fitmas.planning_contract import build_availability_state
from fitmas.signals import collect_signals, format_signals_for_prompt
from fitmas.time_context import DAY_LABELS_FR, build_time_context, get_local_now, render_time_context

logger = logging.getLogger(__name__)

DAY_MAP = {
    0: "monday", 1: "tuesday", 2: "wednesday",
    3: "thursday", 4: "friday", 5: "saturday", 6: "sunday",
}
DAY_LABELS = {key: label.capitalize() for key, label in DAY_LABELS_FR.items()}
NEXT_DAY = {
    "monday": "tuesday", "tuesday": "wednesday", "wednesday": "thursday",
    "thursday": "friday", "friday": "saturday", "saturday": "sunday",
    "sunday": "monday",
}
PREV_DAY = {
    "monday": "sunday", "tuesday": "monday", "wednesday": "tuesday",
    "thursday": "wednesday", "friday": "thursday", "saturday": "friday",
    "sunday": "saturday",
}

HEARTBEAT_FACT_CATEGORIES = ("health", "fatigue", "constraint")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def get_active_fact_lines(
    db: Session,
    user: s.User,
    *,
    suppress_stable_constraints: bool = True,
) -> list[str]:
    """Return short fact lines for active health/fatigue/constraint facts."""
    facts = repo.get_active_memory_items(
        db,
        user.id,
        profile_limit=24,
        working_limit=48,
        include_patterns=True,
        pattern_limit=8,
        total_limit=72,
    )
    relevant = [
        f for f in facts
        if f.category in HEARTBEAT_FACT_CATEGORIES and fact_is_current(f)
    ]
    filtered = [
        fact
        for fact in relevant
        if not _should_suppress_fact(fact, suppress_stable_constraints=suppress_stable_constraints)
    ]
    return [f"- [{f.category}] {f.value}" for f in filtered[:5]]


def format_active_facts_for_prompt(
    db: Session,
    user: s.User,
    *,
    suppress_stable_constraints: bool = True,
) -> str:
    lines = get_active_fact_lines(db, user, suppress_stable_constraints=suppress_stable_constraints)
    if not lines:
        return ""
    return "\n\nFaits actifs a prendre en compte:\n" + "\n".join(lines)


def select_calibration_need(
    db: Session,
    user: s.User,
    *,
    preferred_types: tuple[CalibrationNeedType, ...],
    today: date,
    source: str,
) -> object | None:
    memory_items = repo.get_active_memory_items(
        db, user.id,
        profile_limit=24, working_limit=24,
        include_patterns=True, pattern_limit=8, total_limit=48,
    )
    profile = build_athlete_profile(user, facts=memory_items)
    availability_state = build_availability_state(profile)
    activities = repo.get_activities(db, user.id, limit=30)
    adaptation_events = repo.get_recent_adaptation_events(db, user.id, limit=6)
    scheduled_sessions = repo.get_scheduled_sessions(db, user.id, date_from=today, limit=14)
    calibration_status = build_calibration_status(
        profile=profile,
        memory_items=memory_items,
        activities=activities,
        adaptation_events=adaptation_events,
        today=today,
    )
    return detect_calibration_need(
        profile=profile,
        calibration_status=calibration_status,
        availability_state=availability_state,
        scheduled_sessions=scheduled_sessions,
        memory_items=memory_items,
        today=today,
        source=source,
        channel_hint="telegram",
        preferred_types=preferred_types,
    )


# ---------------------------------------------------------------------------
# Role contracts
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class HeartbeatRole:
    """Declares the capabilities and constraints of a heartbeat role."""
    name: str
    can_read: tuple[str, ...]    # what data sources this role can access
    can_write: tuple[str, ...]   # what side effects this role can trigger
    max_output_sentences: int


BRIEFING_ROLE = HeartbeatRole(
    name="briefing",
    can_read=("plan", "signals", "facts", "yesterday_status", "calibration"),
    can_write=("message",),
    max_output_sentences=4,
)

REMINDER_ROLE = HeartbeatRole(
    name="reminder",
    can_read=("plan", "signals", "facts", "calibration"),
    can_write=("message",),
    max_output_sentences=2,
)

REVIEW_ROLE = HeartbeatRole(
    name="review",
    can_read=("plan", "activities", "completion_stats", "facts"),
    can_write=("message", "trigger_regeneration"),
    max_output_sentences=5,
)

SIGNAL_ROLE = HeartbeatRole(
    name="signal",
    can_read=("signals", "facts", "adaptation"),
    can_write=("message", "trigger_adaptation"),
    max_output_sentences=3,
)


# ---------------------------------------------------------------------------
# Role-specific prompt builders
# ---------------------------------------------------------------------------

def build_briefing_prompt(
    *,
    user: s.User,
    today_session: Any,
    day: Any | None,
    time_context: dict[str, str],
    yesterday_context: str,
    clarification: Any | None,
    calibration_need: Any | None,
    signals_block: str,
    facts_block: str,
    sport_knowledge: str,
    recent_proactive_context: str = "",
) -> tuple[str, str]:
    """Build system + user prompt for morning briefing. Returns (system, prompt)."""
    label = today_session.label or DAY_LABELS[time_context["day_key"]]

    system = (
        f"Tu es {user.coach_name}, coach multisport IA. "
        f"Style: {user.coach_style}. "
        f"Ton ton: clair, court, direct, chaleureux sans cheerleading. "
        f"Tu tutoies toujours. Reponds en francais. Max {BRIEFING_ROLE.max_output_sentences} phrases."
    )
    if user.coach_soul:
        system += f"\nAme du coach: {user.coach_soul}"
    if signals_block:
        system += (
            f"\n\n{signals_block}\n"
            "Integre les signaux dans ton message de maniere naturelle. "
            "Si un signal est un warning ou action, adapte ton ton en consequence."
        )
    if clarification is not None:
        system += (
            "\n\nSi une clarification prioritaire est fournie, pose exactement cette question. "
            "Pas de deuxieme question. Une phrase de contexte max."
        )
    if recent_proactive_context:
        system += (
            "\n\nQuand tu écris, cherche de la nouveauté utile. "
            "N'ouvre pas avec le même angle ni la même récitation de contraintes stables que dans les derniers messages proactifs, "
            "sauf si quelque chose a réellement changé aujourd'hui."
        )
    system += facts_block
    if sport_knowledge:
        system += f"\n\nConnaissances sport (reference):\n{sport_knowledge}"

    prompt = (
        f"{render_time_context(time_context)}\n"
        f"Genere un message matinal pour {label}.\n"
        f"Source de verite planning: calendrier date reel / app.\n"
        f"Seance: {today_session.session_title} ({today_session.sport_type})\n"
        f"Objectif: {today_session.session_goal}\n"
        f"Priorite: {today_session.priority}\n"
        f"Note: {(day.session_note if day else today_session.session_note) or ''}"
        f"{yesterday_context}"
    )
    if clarification is not None:
        prompt += (
            "\n\nClarification prioritaire:\n"
            f"- question: {clarification.question}\n"
            f"- pourquoi: {clarification.reason}\n"
            "- Cette clarification change reellement la lecture de la semaine."
        )
    effective_need = None if clarification is not None else calibration_need
    if effective_need is not None:
        prompt += f"\n\n{render_hidden_need_brief(effective_need)}"
    if recent_proactive_context:
        prompt += f"\n\nDerniers messages proactifs a ne pas recycler:\n{recent_proactive_context}"

    return system, prompt


def build_reminder_prompt(
    *,
    user: s.User,
    key_session: Any,
    time_context: dict[str, str],
    signals_block: str,
    facts_block: str,
    calibration_need: Any | None,
) -> tuple[str, str]:
    """Build system + user prompt for pre-session reminder. Returns (system, prompt)."""
    label = key_session.label or DAY_LABELS[NEXT_DAY[time_context["day_key"]]]

    system = (
        f"Tu es {user.coach_name}, coach multisport IA. "
        f"Style: {user.coach_style}. "
        "Ton ton: clair, court, direct. "
        f"Tu tutoies toujours. Reponds en francais. Max {REMINDER_ROLE.max_output_sentences} phrases. "
        "Rappelle la seance de demain et demande comment l'utilisateur se sent."
    )
    if user.coach_soul:
        system += f"\nAme du coach: {user.coach_soul}"
    if signals_block:
        system += (
            f"\n\n{signals_block}\n"
            "Integre les signaux dans ton rappel seulement si ca renforce une action utile."
        )
    system += facts_block

    prompt = (
        f"{render_time_context(time_context)}\n"
        f"Source de verite planning: calendrier date reel / app.\n"
        f"Demain {label}: {key_session.session_title} — {key_session.session_goal}.\n"
        f"Priorite: {key_session.priority}."
    )
    if calibration_need is not None:
        prompt += f"\n\n{render_hidden_need_brief(calibration_need)}"

    return system, prompt


def build_review_prompt(
    *,
    user: s.User,
    time_context: dict[str, str],
    week_text: str,
    done_count: int,
    planned_count: int,
    total_sessions: int,
    actual_activity_count: int,
    actual_duration_min: int,
    claimed_activity_count: int,
    claimed_duration_min: int,
    facts_block: str = "",
    weekly_highlights: str = "",
) -> tuple[str, str]:
    """Build system + user prompt for weekly review. Returns (system, prompt)."""
    system = (
        f"Tu es {user.coach_name}, coach multisport IA. "
        f"Style: {user.coach_style}. "
        "Ton ton: clair, court, direct, chaleureux. "
        f"Tu tutoies toujours. Reponds en francais. Max {REVIEW_ROLE.max_output_sentences} phrases. "
        "Fais un bilan de la semaine et donne une perspective pour la suivante."
    )
    if user.coach_soul:
        system += f"\nAme du coach: {user.coach_soul}"
    system += facts_block

    prompt = (
        f"{render_time_context(time_context)}\n"
        f"Source de verite planning: calendrier date reel / app.\n"
        f"Resume de la semaine:\n{week_text}\n"
        f"Nombre de seances planifiees datees sur 7 jours: {total_sessions}.\n"
        f"Seances faites dans le plan: {done_count}. Seances prevues non faites: {planned_count}.\n"
        f"Activites reelles detectees sur 7 jours: {actual_activity_count}. Duree reelle totale: {actual_duration_min} min.\n"
        f"Activites declarees non loggees sur 7 jours: {claimed_activity_count}. Duree declaree totale: {claimed_duration_min} min."
    )
    if weekly_highlights:
        prompt += f"\n\nEvenements explicatifs de la semaine:\n{weekly_highlights}"

    return system, prompt


def build_signal_prompt(
    *,
    user: s.User,
    time_context: dict[str, str],
    signals_block: str,
    facts_block: str,
) -> tuple[str, str]:
    """Build system + user prompt for signal-based proactive message. Returns (system, prompt)."""
    system = (
        f"Tu es {user.coach_name}, coach multisport IA. "
        f"Style: {user.coach_style}. "
        f"Ton ton: clair, court, direct. Tu tutoies. Reponds en francais. Max {SIGNAL_ROLE.max_output_sentences} phrases.\n"
    )
    if user.coach_soul:
        system += f"Ame du coach: {user.coach_soul}\n"
    system += (
        f"\n{signals_block}\n\n"
        "Genere un message proactif base sur ces signaux. "
        "Si grosse seance: felicite brievement et donne un conseil recuperation. "
        "Si seance manquee: checke sans culpabiliser. "
        "Si silence prolonge: prends des nouvelles simplement. "
        "Si charge elevee: suggere d'alleger."
    )
    system += facts_block

    prompt = f"{render_time_context(time_context)}\nGenere un message proactif."

    return system, prompt


def _should_suppress_fact(fact: Any, *, suppress_stable_constraints: bool) -> bool:
    if not suppress_stable_constraints:
        return False
    if isinstance(fact, s.WorkingMemoryEntry):
        return False
    category = str(getattr(fact, "category", "") or "")
    if category != "constraint":
        return False
    return True
