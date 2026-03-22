"""FitMAS Heartbeat — proactive coach messages.

Runs on a schedule and evaluates whether to send a message to the user.
Three trigger types:
  1. Morning briefing (07:30) — summary of today's session
  2. Pre-session reminder (18:00 the day before a key session)
  3. Weekly review (Sunday 20:00) — recap + next week preparation
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from fitmas import repository as repo, schema as s
from fitmas.activity_claims import extract_claims_from_facts
from fitmas.coach_messages import CoachDraft
from fitmas.db import SessionLocal
from fitmas.signals import collect_signals, format_signals_for_prompt
from fitmas.time_context import DAY_LABELS_FR, build_time_context, get_local_now, get_timezone, hours_since, render_time_context

logger = logging.getLogger(__name__)

# Minimum hours between proactive coach messages
PROACTIVE_COOLDOWN_HOURS = 6
# Minimum hours since last user exchange before sending a pre-session reminder
RECENT_EXCHANGE_HOURS = 2
MAX_PROACTIVE_MESSAGES_PER_DAY = 2
MODULE_GUARD_WINDOW = timedelta(minutes=2)
_LAST_PROACTIVE_GUARD_AT: dict[int, datetime] = {}

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


def _get_today_key(timezone_name: str | None) -> str:
    return build_time_context(timezone_name)["day_key"]


def _check_module_guard(user_id: int, *, now: datetime | None = None) -> bool:
    current = now or datetime.now(timezone.utc)
    last_guard_at = _LAST_PROACTIVE_GUARD_AT.get(user_id)
    if not last_guard_at:
        return True
    if current - last_guard_at < MODULE_GUARD_WINDOW:
        logger.info("Module guard active for user %s", user_id)
        return False
    return True


def _reserve_module_guard(user_id: int, *, now: datetime | None = None) -> None:
    _LAST_PROACTIVE_GUARD_AT[user_id] = now or datetime.now(timezone.utc)


def _check_daily_cap(db: Session, user: s.User, max_messages: int = MAX_PROACTIVE_MESSAGES_PER_DAY) -> bool:
    local_now = get_local_now(user.timezone)
    local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    utc_midnight = local_midnight.astimezone(timezone.utc).replace(tzinfo=None)
    sent_today = (
        db.query(s.CoachMessage)
        .filter(
            s.CoachMessage.user_id == user.id,
            s.CoachMessage.role == "agent",
            s.CoachMessage.proactive.is_(True),
            s.CoachMessage.created_at >= utc_midnight,
        )
        .count()
    )
    if sent_today >= max_messages:
        logger.info("Daily proactive cap reached for user %s: %d/%d", user.id, sent_today, max_messages)
        return False
    return True


def _check_cooldown(db: Session, user_id: int, cooldown_hours: float = PROACTIVE_COOLDOWN_HOURS) -> bool:
    """Return True if enough time has passed since the last proactive agent message."""
    last_agent_msg = (
        db.query(s.CoachMessage)
        .filter(
            s.CoachMessage.user_id == user_id,
            s.CoachMessage.role == "agent",
            s.CoachMessage.proactive.is_(True),
        )
        .order_by(s.CoachMessage.created_at.desc())
        .first()
    )
    if not last_agent_msg or not last_agent_msg.created_at:
        return True  # no previous message, ok to send
    elapsed = hours_since(last_agent_msg.created_at)
    if elapsed is None:
        return True
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
    elapsed = hours_since(last_user_msg.created_at)
    if elapsed is None:
        return False
    return elapsed < hours


NO_SEND_TOKEN = "NO_SEND"

# Instruction injected into every heartbeat prompt so the LLM can opt out
NO_SEND_INSTRUCTION = (
    "\n\nSi tu estimes qu'il n'y a rien d'utile ou de pertinent a dire "
    "en ce moment, reponds exactement NO_SEND (rien d'autre). "
    "Mieux vaut se taire que parler pour rien."
)


def _llm_generate(system: str, prompt: str, *, allow_no_send: bool = True) -> str | None:
    """Call the LLM for heartbeat messages.

    Returns None on failure or if the LLM responds with NO_SEND.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    final_system = system
    if allow_no_send:
        final_system += NO_SEND_INSTRUCTION

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            system=final_system,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()

        # Check for NO_SEND token (exact match or wrapped in markup)
        cleaned = text.replace("*", "").replace("`", "").replace("#", "").strip()
        if cleaned.upper() == NO_SEND_TOKEN:
            logger.info("LLM opted out with NO_SEND")
            return None

        # NO_SEND + short ack (<100 chars) → also suppress
        if NO_SEND_TOKEN in text.upper() and len(text) < 100:
            logger.info("LLM opted out with NO_SEND + short ack")
            return None

        # NO_SEND + real content → strip token, deliver content
        if NO_SEND_TOKEN in text.upper():
            text = text.replace(NO_SEND_TOKEN, "").replace("no_send", "").strip()
            if not text:
                return None

        return text
    except Exception:
        logger.exception("Heartbeat LLM call failed")
        return None


def morning_briefing() -> CoachDraft | None:
    """Generate the morning briefing message for today, aware of yesterday's status."""
    db = SessionLocal()
    try:
        user = repo.get_user(db)

        # Cooldown: don't spam if we sent something recently
        if not _check_module_guard(user.id):
            logger.info("Morning briefing skipped — module guard active")
            return None
        if not _check_cooldown(db, user.id, cooldown_hours=PROACTIVE_COOLDOWN_HOURS):
            logger.info("Morning briefing skipped — cooldown active")
            return None
        if not _check_daily_cap(db, user):
            logger.info("Morning briefing skipped — daily cap reached")
            return None

        plan = repo.get_active_plan(db, user.id)
        time_context = build_time_context(user.timezone)
        local_now = get_local_now(user.timezone)
        today_key = time_context["day_key"]
        day = repo.get_day_plan(db, plan.id, today_key)
        if not day:
            return None

        label = DAY_LABELS[today_key]

        # Check yesterday's completion
        yesterday_key, yesterday_status = repo.get_yesterday_status(db, plan.id, today_key)
        yesterday_label = DAY_LABELS.get(yesterday_key or "", "")
        yesterday_day = repo.get_day_plan(db, plan.id, yesterday_key) if yesterday_key else None

        yesterday_context = ""
        yesterday_activities = _activities_on_local_date(db, user, target_date=local_now.date() - timedelta(days=1))
        yesterday_claims = _claimed_activities_on_local_date(db, user, target_date=local_now.date() - timedelta(days=1))
        if yesterday_day and yesterday_day.sport_type != "rest":
            if yesterday_status == "done":
                yesterday_context = f"\nHier ({yesterday_label}): {yesterday_day.session_title} — fait. Bien."
            elif yesterday_activities:
                sports = ", ".join(sorted({activity.sport_type for activity in yesterday_activities}))
                total_duration = sum(activity.duration_min or 0 for activity in yesterday_activities)
                yesterday_context = (
                    f"\nHier ({yesterday_label}): seance prevue non validee, "
                    f"mais activite reelle detectee ({sports}, {total_duration} min)."
                )
            elif yesterday_claims:
                sports = ", ".join(sorted({claim.sport_type or 'sport inconnu' for claim in yesterday_claims}))
                total_duration = sum(claim.duration_min or 0 for claim in yesterday_claims)
                yesterday_context = (
                    f"\nHier ({yesterday_label}): seance prevue non validee, "
                    f"mais activite declaree non loggee detectee ({sports}, {total_duration} min)."
                )
            elif yesterday_status == "planned":
                yesterday_context = (
                    f"\nHier ({yesterday_label}): {yesterday_day.session_title} — "
                    f"pas marque comme fait. A noter."
                )
            elif yesterday_status in ("skipped", "adapted"):
                yesterday_context = f"\nHier ({yesterday_label}): adapte/saute. On avance."

        # Collect signals for richer context
        signals = collect_signals(db, user)
        signals_block = format_signals_for_prompt(signals)

        # Try LLM-generated briefing
        system = (
            f"Tu es {user.coach_name}, coach multisport IA. "
            f"Style: {user.coach_style}. "
            f"Ton ton: clair, court, direct, chaleureux sans cheerleading. "
            "Tu tutoies toujours. Reponds en francais. Max 3-4 phrases."
        )
        if user.coach_soul:
            system += f"\nAme du coach: {user.coach_soul}"
        if signals_block:
            system += (
                f"\n\n{signals_block}\n"
                "Integre les signaux dans ton message de maniere naturelle. "
                "Si un signal est un warning ou action, adapte ton ton en consequence."
            )

        prompt = (
            f"{render_time_context(time_context)}\n"
            f"Genere un message matinal pour {label}.\n"
            f"Seance: {day.session_title} ({day.sport_type})\n"
            f"Objectif: {day.session_goal}\n"
            f"Priorite: {day.priority}\n"
            f"Note: {day.session_note}"
            f"{yesterday_context}"
        )
        llm_msg = _llm_generate(system, prompt)
        if llm_msg:
            _reserve_module_guard(user.id)
            return CoachDraft(text=llm_msg, proactive=True)

        # Fallback: structured message
        msg = f"Bonjour. {label} — {day.session_title}.\n{day.session_goal}. Priorite: {day.priority}."
        if yesterday_context:
            msg += f"\n{yesterday_context.strip()}"
        _reserve_module_guard(user.id)
        return CoachDraft(text=msg, proactive=True)
    finally:
        db.close()


def pre_session_reminder() -> CoachDraft | None:
    """Generate a reminder the evening before a key session."""
    db = SessionLocal()
    try:
        user = repo.get_user(db)

        # Cooldown: don't send if recent proactive message
        if not _check_module_guard(user.id):
            logger.info("Pre-session reminder skipped — module guard active")
            return None
        if not _check_cooldown(db, user.id, cooldown_hours=PROACTIVE_COOLDOWN_HOURS):
            logger.info("Pre-session reminder skipped — cooldown active")
            return None
        if not _check_daily_cap(db, user):
            logger.info("Pre-session reminder skipped — daily cap reached")
            return None

        # Skip if user just talked to the coach
        if _had_recent_exchange(db, user.id, hours=RECENT_EXCHANGE_HOURS):
            logger.info("Pre-session reminder skipped — recent exchange")
            return None

        plan = repo.get_active_plan(db, user.id)
        time_context = build_time_context(user.timezone)
        today_key = time_context["day_key"]
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
        signals = collect_signals(db, user)
        signals_block = format_signals_for_prompt(signals)
        if signals_block:
            system += (
                f"\n\n{signals_block}\n"
                "Integre les signaux dans ton rappel seulement si ca renforce une action utile."
            )
        prompt = (
            f"{render_time_context(time_context)}\n"
            f"Demain {label}: {day.session_title} — {day.session_goal}.\n"
            f"Priorite: {day.priority}."
        )
        llm_msg = _llm_generate(system, prompt)
        if llm_msg:
            _reserve_module_guard(user.id)
            return CoachDraft(text=llm_msg, proactive=True)

        msg = f"Demain c'est {day.session_title}. Tu te sens comment pour {label.lower()} ?"
        _reserve_module_guard(user.id)
        return CoachDraft(text=msg, proactive=True)
    finally:
        db.close()


def weekly_review() -> CoachDraft | None:
    """Generate a Sunday evening weekly review draft without side effects."""
    db = SessionLocal()
    try:
        user = repo.get_user(db)
        plan = repo.get_active_plan(db, user.id)

        # Build week summary with completion statuses
        lines = []
        done_count = 0
        planned_count = 0
        recent_activities = _activities_last_days(db, user, days=7)
        actual_activity_count = len(recent_activities)
        actual_duration_min = sum(activity.duration_min or 0 for activity in recent_activities)
        recent_claims = _claimed_activities_last_days(db, user, days=7)
        claimed_activity_count = len(recent_claims)
        claimed_duration_min = sum(claim.duration_min or 0 for claim in recent_claims)
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
            f"{render_time_context(build_time_context(user.timezone))}\n"
            f"Resume de la semaine:\n{week_text}\n"
            f"Intention: {plan.intention}\n"
            f"Seances faites dans le plan: {done_count}. Seances prevues non faites: {planned_count}.\n"
            f"Activites reelles detectees sur 7 jours: {actual_activity_count}. Duree reelle totale: {actual_duration_min} min.\n"
            f"Activites declarees non loggees sur 7 jours: {claimed_activity_count}. Duree declaree totale: {claimed_duration_min} min."
        )
        llm_msg = _llm_generate(system, prompt, allow_no_send=False)
        if llm_msg:
            _reserve_module_guard(user.id)
            return CoachDraft(text=llm_msg, proactive=True)

        msg = "Fin de semaine. Le plan a tenu ses reperes. On prend de la marge pour la suite."
        _reserve_module_guard(user.id)
        return CoachDraft(text=msg, proactive=True)
    finally:
        db.close()


def signal_check() -> CoachDraft | None:
    """Check signals and generate a proactive message if anything actionable is found.

    This is meant to run a few times per day (e.g. after Strava sync) to catch
    post-activity feedback and silence detection outside of the morning briefing.
    """
    db = SessionLocal()
    try:
        user = repo.get_user(db)

        if not _check_module_guard(user.id):
            logger.info("Signal check skipped — module guard active")
            return None
        if not _check_cooldown(db, user.id, cooldown_hours=PROACTIVE_COOLDOWN_HOURS):
            logger.info("Signal check skipped — cooldown active")
            return None
        if not _check_daily_cap(db, user):
            logger.info("Signal check skipped — daily cap reached")
            return None

        if _had_recent_exchange(db, user.id, hours=RECENT_EXCHANGE_HOURS):
            logger.info("Signal check skipped — recent exchange")
            return None

        signals = collect_signals(db, user)
        if not signals:
            return None

        # Only act on warning/action severity signals
        actionable = [s for s in signals if s["severity"] in ("warning", "action")]
        if not actionable:
            # Info signals (streak, big session) — only send if big_session_done
            big_session = next((s for s in signals if s["kind"] == "big_session_done"), None)
            if not big_session:
                return None
            actionable = [big_session]

        signals_block = format_signals_for_prompt(actionable)
        time_context = build_time_context(user.timezone)

        system = (
            f"Tu es {user.coach_name}, coach multisport IA. "
            f"Style: {user.coach_style}. "
            f"Ton ton: clair, court, direct. Tu tutoies. Reponds en francais. Max 2-3 phrases.\n"
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

        prompt = f"{render_time_context(time_context)}\nGenere un message proactif."
        llm_msg = _llm_generate(system, prompt)
        if llm_msg:
            _reserve_module_guard(user.id)
            return CoachDraft(text=llm_msg, proactive=True)

        # Fallback
        first = actionable[0]
        if first["kind"] == "big_session_done":
            msg = f"Belle seance. {first['data'].get('title', 'Beau travail')}. Pense a bien recuperer."
        elif first["kind"] == "silence_3_days":
            msg = "Ca fait quelques jours. Comment ca va de ton cote ?"
        elif first["kind"] == "missed_key_session":
            msg = f"La seance de {first['data'].get('day', 'hier')} n'a pas ete faite. On ajuste ou on la replace ?"
        elif first["kind"] == "high_cumulative_load":
            msg = "Semaine chargee. Pense a lever le pied sur les prochaines seances."
        else:
            msg = "Je garde un oeil sur ta semaine. On en reparle."

        _reserve_module_guard(user.id)
        return CoachDraft(text=msg, proactive=True)
    finally:
        db.close()


def _activities_last_days(db: Session, user: s.User, *, days: int) -> list[s.Activity]:
    cutoff = get_local_now(user.timezone).date() - timedelta(days=max(0, days - 1))
    timezone = get_timezone(user.timezone)
    matched: list[s.Activity] = []
    for activity in repo.get_activities(db, user.id, limit=160):
        if activity.started_at is None:
            continue
        started_at = activity.started_at
        if started_at.tzinfo is None:
            local_date = started_at.date()
        else:
            local_date = started_at.astimezone(timezone).date()
        if local_date >= cutoff:
            matched.append(activity)
    return matched


def _activities_on_local_date(db: Session, user: s.User, *, target_date: date) -> list[s.Activity]:
    timezone = get_timezone(user.timezone)
    matched: list[s.Activity] = []
    for activity in repo.get_activities(db, user.id, limit=120):
        if activity.started_at is None:
            continue
        started_at = activity.started_at
        if started_at.tzinfo is None:
            local_date = started_at.date()
        else:
            local_date = started_at.astimezone(timezone).date()
        if local_date == target_date:
            matched.append(activity)
    return matched


def _claimed_activities_on_local_date(db: Session, user: s.User, *, target_date: date):
    facts = repo.get_active_facts(db, user.id, limit=48)
    return extract_claims_from_facts(facts, target_date=target_date)


def _claimed_activities_last_days(db: Session, user: s.User, *, days: int):
    cutoff = get_local_now(user.timezone).date() - timedelta(days=max(0, days - 1))
    facts = repo.get_active_facts(db, user.id, limit=64)
    return [claim for claim in extract_claims_from_facts(facts) if claim.resolved_date_iso and date.fromisoformat(claim.resolved_date_iso) >= cutoff]
