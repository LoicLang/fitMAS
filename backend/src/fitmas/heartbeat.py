"""FitMAS Heartbeat — proactive coach messages.

Runs on a schedule and evaluates whether to send a message to the user.
Three trigger types:
  1. Morning briefing (07:30) — summary of today's session
  2. Pre-session reminder (18:00 the day before a key session)
  3. Weekly review (Sunday 20:00) — recap + next week preparation
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from fitmas import heartbeat_evaluation, repository as repo, schema as s
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
from fitmas.db import SessionLocal
from fitmas.execution_clarification import build_execution_clarification
from fitmas.execution_evidence import classify_execution_evidence
from fitmas.fact_memory import fact_is_current
from fitmas.knowledge import load_sport_knowledge
from fitmas.llm_gateway import generate_heartbeat_text
from fitmas.planning_contract import build_availability_state
from fitmas.signals import collect_signals, format_signals_for_prompt
from fitmas.time_context import DAY_LABELS_FR, build_time_context, get_local_now, hours_since, render_time_context

logger = logging.getLogger(__name__)

PROACTIVE_COOLDOWN_HOURS = heartbeat_evaluation.PROACTIVE_COOLDOWN_HOURS
RECENT_EXCHANGE_HOURS = heartbeat_evaluation.RECENT_EXCHANGE_HOURS
MAX_PROACTIVE_MESSAGES_PER_DAY = heartbeat_evaluation.MAX_PROACTIVE_MESSAGES_PER_DAY
MODULE_GUARD_WINDOW = heartbeat_evaluation.MODULE_GUARD_WINDOW
_LAST_PROACTIVE_GUARD_AT = heartbeat_evaluation.LAST_PROACTIVE_GUARD_AT

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


def _get_today_key(timezone_name: str | None) -> str:
    return build_time_context(timezone_name)["day_key"]


def _check_module_guard(user_id: int, *, now: datetime | None = None) -> bool:
    return heartbeat_evaluation.check_module_guard(user_id, now=now)


def _reserve_module_guard(user_id: int, *, now: datetime | None = None) -> None:
    heartbeat_evaluation.reserve_module_guard(user_id, now=now)


def _check_daily_cap(db: Session, user: s.User, max_messages: int = MAX_PROACTIVE_MESSAGES_PER_DAY) -> bool:
    return heartbeat_evaluation.check_daily_cap(db, user, max_messages=max_messages)


def _check_cooldown(db: Session, user_id: int, cooldown_hours: float = PROACTIVE_COOLDOWN_HOURS) -> bool:
    return heartbeat_evaluation.check_cooldown(db, user_id, cooldown_hours=cooldown_hours)


def _had_recent_exchange(db: Session, user_id: int, hours: float = RECENT_EXCHANGE_HOURS) -> bool:
    return heartbeat_evaluation.had_recent_exchange(db, user_id, hours=hours)


def _llm_generate(system: str, prompt: str, *, allow_no_send: bool = True) -> str | None:
    """Call the LLM for heartbeat messages via llm_gateway."""
    return generate_heartbeat_text(system, prompt, allow_no_send=allow_no_send)


HEARTBEAT_FACT_CATEGORIES = ("health", "fatigue", "constraint")


def _get_active_fact_lines(db: Session, user: s.User) -> list[str]:
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
    return [f"- [{f.category}] {f.value}" for f in relevant[:5]]


def _format_active_facts_for_prompt(db: Session, user: s.User) -> str:
    """Return a prompt block with active health/fatigue/constraint facts, or empty string."""
    lines = _get_active_fact_lines(db, user)
    if not lines:
        return ""
    return "\n\nFaits actifs a prendre en compte:\n" + "\n".join(lines)


def _select_calibration_need(
    db: Session,
    user: s.User,
    *,
    preferred_types: tuple[CalibrationNeedType, ...],
    today: date,
    source: str,
) -> object | None:
    memory_items = repo.get_active_memory_items(
        db,
        user.id,
        profile_limit=24,
        working_limit=24,
        include_patterns=True,
        pattern_limit=8,
        total_limit=48,
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


def morning_briefing() -> CoachDraft | None:
    """Generate the morning briefing message for today, aware of yesterday's status."""
    db = SessionLocal()
    try:
        user = repo.get_user(db)

        gate = heartbeat_evaluation.evaluate_proactive_gate(db, user)
        if not gate.allowed:
            logger.info("Morning briefing skipped — %s", str(gate.reason or "blocked").replace("_", " "))
            return None

        time_context = build_time_context(user.timezone)
        local_now = get_local_now(user.timezone)
        today_session = repo.get_today_scheduled_session(db, user.id, timezone_name=user.timezone)
        if not today_session:
            return None
        plan = repo.get_active_plan_optional(db, user.id)
        day = None
        if plan is not None:
            _, day = repo.get_current_week_day_plan_for_session(db, user=user, session=today_session)
        calibration_need = _select_calibration_need(
            db,
            user,
            preferred_types=(CalibrationNeedType.AVAILABILITY_WINDOW,),
            today=local_now.date(),
            source="heartbeat_morning",
        )

        label = today_session.label or DAY_LABELS[time_context["day_key"]]

        # Check yesterday's completion
        yesterday_date = local_now.date() - timedelta(days=1)
        yesterday_sessions = repo.get_scheduled_sessions_for_date(db, user.id, target_date=yesterday_date)
        yesterday_key = PREV_DAY[time_context["day_key"]]
        yesterday_day = repo.get_day_plan(db, plan.id, yesterday_key) if plan else None

        yesterday_context = ""
        clarification_session = None
        yesterday_activities = _activities_on_local_date(db, user, target_date=yesterday_date)
        yesterday_claims = _claimed_activities_on_local_date(db, user, target_date=yesterday_date)
        if yesterday_sessions:
            yesterday_label = yesterday_sessions[0].label or yesterday_date.isoformat()
            non_rest_sessions = [session for session in yesterday_sessions if session.sport_type != "rest"]
            pending_sessions = [session for session in non_rest_sessions if session.completion_status == "planned"]
            adapted_sessions = [
                session for session in non_rest_sessions if session.completion_status in ("skipped", "adapted")
            ]
            titles = ", ".join(session.session_title for session in non_rest_sessions[:2])
            primary_session = non_rest_sessions[0] if non_rest_sessions else None
            clarification_session = primary_session
            evidence = classify_execution_evidence(
                planned_session=primary_session,
                activities=yesterday_activities,
                claims=list(yesterday_claims),
            )

            if evidence.display_status == "confirmed_done":
                yesterday_context = f"\nHier ({yesterday_label}): {titles} — fait confirme."
            elif evidence.display_status == "offplan_done" and yesterday_activities:
                sports = ", ".join(sorted({activity.sport_type for activity in yesterday_activities}))
                total_duration = sum(activity.duration_min or 0 for activity in yesterday_activities)
                yesterday_context = (
                    f"\nHier ({yesterday_label}): seance prevue non validee, "
                    f"mais activite reelle detectee ({sports}, {total_duration} min)."
                )
            elif evidence.display_status == "claimed_done" and yesterday_claims:
                sports = ", ".join(sorted({claim.sport_type or 'sport inconnu' for claim in yesterday_claims}))
                total_duration = sum(claim.duration_min or 0 for claim in yesterday_claims)
                yesterday_context = (
                    f"\nHier ({yesterday_label}): seance prevue non validee, "
                    f"mais activite declaree non loggee detectee ({sports}, {total_duration} min)."
                )
            elif evidence.display_status == "uncertain":
                yesterday_context = (
                    f"\nHier ({yesterday_label}): {titles} — statut a verifier, "
                    "pas de trace assez forte pour dire que c'etait fait."
                )
            elif pending_sessions:
                yesterday_context = (
                    f"\nHier ({yesterday_label}): {titles} — "
                    f"pas marque comme fait. A noter."
                )
            elif adapted_sessions:
                yesterday_context = f"\nHier ({yesterday_label}): adapte/saute. On avance."
        elif yesterday_day and yesterday_day.sport_type != "rest":
            yesterday_label = yesterday_day.label or DAY_LABELS.get(yesterday_key, yesterday_key)
            clarification_session = yesterday_day
            evidence = classify_execution_evidence(
                planned_session=yesterday_day,
                activities=yesterday_activities,
                claims=list(yesterday_claims),
            )
            if evidence.display_status == "confirmed_done":
                yesterday_context = f"\nHier ({yesterday_label}): {yesterday_day.session_title} — fait confirme."
            elif evidence.display_status == "offplan_done" and yesterday_activities:
                sports = ", ".join(sorted({activity.sport_type for activity in yesterday_activities}))
                total_duration = sum(activity.duration_min or 0 for activity in yesterday_activities)
                yesterday_context = (
                    f"\nHier ({yesterday_label}): seance prevue non validee, "
                    f"mais activite reelle detectee ({sports}, {total_duration} min)."
                )
            elif evidence.display_status == "claimed_done" and yesterday_claims:
                sports = ", ".join(sorted({claim.sport_type or 'sport inconnu' for claim in yesterday_claims}))
                total_duration = sum(claim.duration_min or 0 for claim in yesterday_claims)
                yesterday_context = (
                    f"\nHier ({yesterday_label}): seance prevue non validee, "
                    f"mais activite declaree non loggee detectee ({sports}, {total_duration} min)."
                )
            elif evidence.display_status == "uncertain":
                yesterday_context = (
                    f"\nHier ({yesterday_label}): {yesterday_day.session_title} — statut a verifier, "
                    "pas de trace assez forte pour dire que c'etait fait."
                )
            elif yesterday_day.completion_status == "planned":
                yesterday_context = (
                    f"\nHier ({yesterday_label}): {yesterday_day.session_title} — "
                    f"pas marque comme fait. A noter."
                )
            elif yesterday_day.completion_status in ("skipped", "adapted"):
                yesterday_context = f"\nHier ({yesterday_label}): adapte/saute. On avance."

        recent_sessions = repo.get_scheduled_sessions_between_dates(
            db,
            user.id,
            start_date=local_now.date() - timedelta(days=13),
            end_date=local_now.date(),
            limit=42,
        )
        recent_activities = repo.get_activities(db, user.id, limit=120)
        recent_claims = _claimed_activities_last_days(db, user, days=14)
        clarification = build_execution_clarification(
            today=local_now.date(),
            target_session=clarification_session,
            target_date=yesterday_date,
            scheduled_sessions=recent_sessions,
            activities=recent_activities,
            claims=list(recent_claims),
        )
        effective_calibration_need = None if clarification is not None else calibration_need

        # Collect signals for richer context
        try:
            signals = collect_signals(db, user)
        except RuntimeError:
            logger.warning("Morning briefing proceeding without active plan-backed signals", exc_info=True)
            signals = []
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
        if clarification is not None:
            system += (
                "\n\nSi une clarification prioritaire est fournie, pose exactement cette question. "
                "Pas de deuxieme question. Une phrase de contexte max."
            )
        system += _format_active_facts_for_prompt(db, user)
        sport_knowledge = load_sport_knowledge({today_session.sport_type}, max_tokens=500)
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
        if effective_calibration_need is not None:
            prompt += f"\n\n{render_hidden_need_brief(effective_calibration_need)}"
        llm_msg = _llm_generate(system, prompt)
        if llm_msg:
            memory_updates = []
            if effective_calibration_need is not None and looks_like_clarification_message(llm_msg):
                memory_updates.append(effective_calibration_need.as_memory_update())
            return CoachDraft(text=llm_msg, proactive=True, memory_updates=memory_updates)

        # Fallback: structured message
        if clarification is not None:
            return CoachDraft(text=clarification.question, proactive=True)
        msg = (
            f"Bonjour. {label} — {today_session.session_title}.\n"
            f"{today_session.session_goal}. Priorite: {today_session.priority}."
        )
        if yesterday_context:
            msg += f"\n{yesterday_context.strip()}"
        fact_lines = _get_active_fact_lines(db, user)
        if fact_lines:
            msg += "\nA noter: " + "; ".join(line.lstrip("- ") for line in fact_lines[:2]) + "."
        return CoachDraft(text=msg, proactive=True)
    finally:
        db.close()


def pre_session_reminder() -> CoachDraft | None:
    """Generate a reminder the evening before a key session."""
    db = SessionLocal()
    try:
        user = repo.get_user(db)

        gate = heartbeat_evaluation.evaluate_proactive_gate(
            db,
            user,
            require_recent_exchange_gap=True,
            recent_exchange_hours=RECENT_EXCHANGE_HOURS,
        )
        if not gate.allowed:
            logger.info("Pre-session reminder skipped — %s", str(gate.reason or "blocked").replace("_", " "))
            return None

        time_context = build_time_context(user.timezone)
        today_key = time_context["day_key"]
        tomorrow_key = NEXT_DAY[today_key]
        tomorrow_date = get_local_now(user.timezone).date() + timedelta(days=1)
        tomorrow_sessions = [
            session
            for session in repo.get_scheduled_sessions_for_date(db, user.id, target_date=tomorrow_date)
            if session.sport_type != "rest"
        ]
        if not tomorrow_sessions:
            return None

        # Only remind before key/important sessions
        key_words = ("cle", "fort", "qualite", "bloc", "longue", "long")
        key_session = next(
            (
                session
                for session in tomorrow_sessions
                if any(w in (f"{session.priority} {session.session_title} {session.session_type}").lower() for w in key_words)
            ),
            None,
        )
        if key_session is None:
            logger.info("Tomorrow (%s) is not a key session — skipping reminder", tomorrow_key)
            return None
        calibration_need = _select_calibration_need(
            db,
            user,
            preferred_types=(CalibrationNeedType.FATIGUE_STATE,),
            today=get_local_now(user.timezone).date(),
            source="heartbeat_pre_session",
        )

        label = key_session.label or DAY_LABELS[NEXT_DAY[today_key]]

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
        system += _format_active_facts_for_prompt(db, user)
        prompt = (
            f"{render_time_context(time_context)}\n"
            f"Source de verite planning: calendrier date reel / app.\n"
            f"Demain {label}: {key_session.session_title} — {key_session.session_goal}.\n"
            f"Priorite: {key_session.priority}."
        )
        if calibration_need is not None:
            prompt += f"\n\n{render_hidden_need_brief(calibration_need)}"
        llm_msg = _llm_generate(system, prompt)
        if llm_msg:
            memory_updates = []
            if calibration_need is not None and looks_like_clarification_message(llm_msg):
                memory_updates.append(calibration_need.as_memory_update())
            return CoachDraft(text=llm_msg, proactive=True, memory_updates=memory_updates)

        msg = f"Demain c'est {key_session.session_title}. Tu te sens comment pour {label.lower()} ?"
        fact_lines = _get_active_fact_lines(db, user)
        if fact_lines:
            msg += "\nA noter: " + "; ".join(line.lstrip("- ") for line in fact_lines[:2]) + "."
        return CoachDraft(text=msg, proactive=True)
    finally:
        db.close()


def weekly_review() -> CoachDraft | None:
    """Generate a Sunday evening weekly review draft without side effects."""
    db = SessionLocal()
    try:
        user = repo.get_user(db)
        local_today = get_local_now(user.timezone).date()
        start_date = local_today - timedelta(days=6)
        week_sessions = repo.get_scheduled_sessions_between_dates(
            db,
            user.id,
            start_date=start_date,
            end_date=local_today,
            limit=42,
        )

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
        for session in week_sessions:
            label = session.label or DAY_LABELS.get(session.day, session.day)
            status_marker = ""
            if session.sport_type != "rest":
                if session.completion_status == "done":
                    status_marker = " ✅"
                    done_count += 1
                elif session.completion_status == "planned":
                    status_marker = " (pas fait)"
                    planned_count += 1
                elif session.completion_status in ("skipped", "adapted"):
                    status_marker = f" ({session.completion_status})"
            lines.append(f"- {label}: {session.session_title}{status_marker}")
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
            f"Source de verite planning: calendrier date reel / app.\n"
            f"Resume de la semaine:\n{week_text}\n"
            f"Nombre de seances planifiees datees sur 7 jours: {len(week_sessions)}.\n"
            f"Seances faites dans le plan: {done_count}. Seances prevues non faites: {planned_count}.\n"
            f"Activites reelles detectees sur 7 jours: {actual_activity_count}. Duree reelle totale: {actual_duration_min} min.\n"
            f"Activites declarees non loggees sur 7 jours: {claimed_activity_count}. Duree declaree totale: {claimed_duration_min} min."
        )
        llm_msg = _llm_generate(system, prompt, allow_no_send=False)
        if llm_msg:
            return CoachDraft(text=llm_msg, proactive=True)

        msg = "Fin de semaine. Le plan a tenu ses reperes. On prend de la marge pour la suite."
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

        gate = heartbeat_evaluation.evaluate_proactive_gate(
            db,
            user,
            require_recent_exchange_gap=True,
            recent_exchange_hours=RECENT_EXCHANGE_HOURS,
        )
        if not gate.allowed:
            logger.info("Signal check skipped — %s", str(gate.reason or "blocked").replace("_", " "))
            return None

        # Adaptive plan: check TSB and missed cascade triggers
        try:
            from fitmas.adaptation import check_and_adapt_tsb, check_and_adapt_missed
            tsb_result = check_and_adapt_tsb(db, user)
            if tsb_result and tsb_result.applied and tsb_result.message:
                return CoachDraft(text=tsb_result.message, proactive=True)
            missed_result = check_and_adapt_missed(db, user)
            if missed_result and missed_result.applied and missed_result.message:
                return CoachDraft(text=missed_result.message, proactive=True)
        except Exception:
            logger.exception("Adaptation trigger check failed (non-blocking)")

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
        system += _format_active_facts_for_prompt(db, user)

        prompt = f"{render_time_context(time_context)}\nGenere un message proactif."
        llm_msg = _llm_generate(system, prompt)
        if llm_msg:
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

        fact_lines = _get_active_fact_lines(db, user)
        if fact_lines:
            msg += "\nA noter: " + "; ".join(line.lstrip("- ") for line in fact_lines[:2]) + "."

        return CoachDraft(text=msg, proactive=True)
    finally:
        db.close()
