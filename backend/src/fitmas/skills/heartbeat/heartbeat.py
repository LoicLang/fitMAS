"""FitMAS Heartbeat — proactive coach messages.

Runs on a schedule and evaluates whether to send a message to the user.
Three trigger types:
  1. Morning briefing (07:30) — summary of today's session
  2. Pre-session reminder (18:00 the day before a key session)
  3. Weekly review (Sunday 20:00) — recap + next week preparation

Each trigger delegates to a role (heartbeat_roles.py) that defines:
- what data the role can read
- how to build its prompt
- output constraints (max sentences)

This module handles gating, data loading, LLM calls, and fallback generation.
"""
from __future__ import annotations

import logging
from datetime import timedelta, timezone as dt_timezone

from sqlalchemy.orm import Session

from fitmas import coach_voice, repository as repo, schema as s
from fitmas.activity_helpers import (
    activities_last_days as _activities_last_days,
    activities_on_local_date as _activities_on_local_date,
    claimed_activities_last_days as _claimed_activities_last_days,
    claimed_activities_on_local_date as _claimed_activities_on_local_date,
)
from fitmas.calibration_needs import CalibrationNeedType, looks_like_clarification_message
from fitmas.coach_reading_digest import CoachReadingDigest, build_coach_reading_facts
from fitmas.coach_state_bundle import build_coach_state_bundle
from fitmas.coach_messages import CoachDraft
from fitmas.db import SessionLocal
from fitmas.execution_clarification import build_execution_clarification
from fitmas.skills.heartbeat import evaluation as heartbeat_evaluation
from fitmas.skills.heartbeat.context import build_heartbeat_context_bundle
from fitmas.skills.heartbeat.roles import (
    BRIEFING_ROLE,
    DAY_LABELS,
    NEXT_DAY,
    build_briefing_prompt,
    build_reminder_prompt,
    build_review_prompt,
    build_signal_prompt,
    format_active_facts_for_prompt,
    get_active_fact_lines,
    select_calibration_need,
)
from fitmas.knowledge import load_sport_knowledge
from fitmas.llm_gateway import generate_heartbeat_text
from fitmas.llm_prompt_builder import detect_open_question
from fitmas.recent_reality import build_recent_reality_window
from fitmas.signals import collect_signals, format_signals_for_prompt
from fitmas.time_context import build_time_context, get_local_now

logger = logging.getLogger(__name__)

PROACTIVE_COOLDOWN_HOURS = heartbeat_evaluation.PROACTIVE_COOLDOWN_HOURS
RECENT_EXCHANGE_HOURS = heartbeat_evaluation.RECENT_EXCHANGE_HOURS
MAX_PROACTIVE_MESSAGES_PER_DAY = heartbeat_evaluation.MAX_PROACTIVE_MESSAGES_PER_DAY
MODULE_GUARD_WINDOW = heartbeat_evaluation.MODULE_GUARD_WINDOW
_LAST_PROACTIVE_GUARD_AT = heartbeat_evaluation.LAST_PROACTIVE_GUARD_AT


def _reserve_module_guard(user_id: int, *, now=None) -> None:
    heartbeat_evaluation.reserve_module_guard(user_id, now=now)


def _llm_generate(
    system: str,
    prompt: str,
    *,
    allow_no_send: bool = True,
    pipeline: str = "heartbeat",
) -> str | None:
    text = generate_heartbeat_text(system, prompt, allow_no_send=allow_no_send)
    # Chantier 1 - Etape D : log-only receipt-style detection sur les outputs
    # heartbeat (briefing / reminder / review / signal). Permet de mesurer le
    # taux de violation par pipeline avant de promouvoir en hard guard.
    if text and coach_voice.message_looks_receipt_style(text):
        logger.warning(
            "coach_voice.receipt_style pipeline=%s message=%r",
            pipeline,
            text[:160],
        )
    return text


# ---------------------------------------------------------------------------
# Morning briefing (BriefingRole)
# ---------------------------------------------------------------------------

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
        day = None
        calibration_need = select_calibration_need(
            db, user,
            preferred_types=(CalibrationNeedType.AVAILABILITY_WINDOW,),
            today=local_now.date(),
            source="heartbeat_morning",
        )

        # Yesterday-specific data — feeds YesterdayTruth in the bundle and
        # the execution clarification helper.
        yesterday_date = local_now.date() - timedelta(days=1)
        yesterday_sessions = repo.get_scheduled_sessions_for_date(
            db, user.id, target_date=yesterday_date,
        )
        yesterday_activities = _activities_on_local_date(db, user, target_date=yesterday_date)
        yesterday_claims = list(_claimed_activities_on_local_date(db, user, target_date=yesterday_date))
        clarification_session = next(
            (session for session in yesterday_sessions if session.sport_type != "rest"),
            None,
        )

        recent_sessions = repo.get_scheduled_sessions_between_dates(
            db, user.id,
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

        # Collect signals
        try:
            signals = collect_signals(db, user)
        except RuntimeError:
            logger.warning("Morning briefing proceeding without active plan-backed signals", exc_info=True)
            signals = []

        # Ground-truth execution counters for the week. Without this, the LLM
        # confabulates a weekly count (it once told the user "tu as sorti 4
        # seances cette semaine" when only 1 real workout had happened).
        try:
            recent_reality = build_recent_reality_window(
                today=local_now.date(),
                scheduled_sessions=recent_sessions,
                activities=recent_activities,
                claims=list(recent_claims),
            )
        except Exception:
            logger.warning("Morning briefing: failed to build recent reality window", exc_info=True)
            recent_reality = None

        # Structured truth bundle. Replaces the free-form yesterday_context
        # string + raw recent_reality counters in the prompt. Without this
        # the LLM was projecting weekly aggregates onto "hier" (incident
        # 2026-04-29: claimed yesterday was offplan while the activity was
        # actually linked to a planned session).
        bundle = build_heartbeat_context_bundle(
            today=local_now.date(),
            today_planned_session=today_session,
            yesterday_planned_sessions=yesterday_sessions,
            yesterday_activities=yesterday_activities,
            yesterday_claims=yesterday_claims,
            week_recent_reality=recent_reality or build_recent_reality_window(
                today=local_now.date(),
                scheduled_sessions=recent_sessions,
                activities=recent_activities,
                claims=list(recent_claims),
            ),
            week_activities=recent_activities,
            capability=BRIEFING_ROLE.capability,
        )

        # Build prompt via BriefingRole
        system, prompt = build_briefing_prompt(
            user=user,
            today_session=today_session,
            day=day,
            time_context=time_context,
            bundle=bundle,
            clarification=clarification,
            calibration_need=effective_calibration_need,
            signals_block=format_signals_for_prompt(signals),
            facts_block=format_active_facts_for_prompt(db, user),
            sport_knowledge=load_sport_knowledge({today_session.sport_type}, max_tokens=500),
            recent_proactive_context=_recent_proactive_context(db, user, limit=2),
            pending_open_question=_pending_open_question_for_user(db, user),
        )

        llm_msg = _llm_generate(system, prompt, pipeline="heartbeat_briefing")
        if llm_msg:
            memory_updates = []
            if effective_calibration_need is not None and looks_like_clarification_message(llm_msg):
                memory_updates.append(effective_calibration_need.as_memory_update())
            return CoachDraft(text=llm_msg, proactive=True, memory_updates=memory_updates)

        # Fallback
        if clarification is not None:
            return CoachDraft(text=clarification.question, proactive=True)
        label = today_session.label or DAY_LABELS[time_context["day_key"]]
        msg = (
            f"Bonjour. {label} — {today_session.session_title}.\n"
            f"{today_session.session_goal}. Priorite: {today_session.priority}."
        )
        yesterday_summary = _yesterday_fallback_summary(bundle.yesterday)
        if yesterday_summary:
            msg += f"\n{yesterday_summary}"
        fact_lines = get_active_fact_lines(db, user)
        if fact_lines:
            msg += "\nA noter: " + "; ".join(line.lstrip("- ") for line in fact_lines[:2]) + "."
        return CoachDraft(text=msg, proactive=True)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Pre-session reminder (ReminderRole)
# ---------------------------------------------------------------------------

def pre_session_reminder() -> CoachDraft | None:
    """Generate a reminder the evening before a key session."""
    db = SessionLocal()
    try:
        user = repo.get_user(db)

        gate = heartbeat_evaluation.evaluate_proactive_gate(
            db, user,
            require_recent_exchange_gap=True,
            recent_exchange_hours=RECENT_EXCHANGE_HOURS,
        )
        if not gate.allowed:
            logger.info("Pre-session reminder skipped — %s", str(gate.reason or "blocked").replace("_", " "))
            return None

        time_context = build_time_context(user.timezone)
        today_key = time_context["day_key"]
        tomorrow_date = get_local_now(user.timezone).date() + timedelta(days=1)
        tomorrow_sessions = [
            session for session in repo.get_scheduled_sessions_for_date(db, user.id, target_date=tomorrow_date)
            if session.sport_type != "rest"
        ]
        if not tomorrow_sessions:
            return None

        key_words = ("cle", "fort", "qualite", "bloc", "longue", "long")
        key_session = next(
            (
                session for session in tomorrow_sessions
                if any(w in (f"{session.priority} {session.session_title} {session.session_type}").lower() for w in key_words)
            ),
            None,
        )
        if key_session is None:
            logger.info("Tomorrow (%s) is not a key session — skipping reminder", NEXT_DAY[today_key])
            return None

        calibration_need = select_calibration_need(
            db, user,
            preferred_types=(CalibrationNeedType.FATIGUE_STATE,),
            today=get_local_now(user.timezone).date(),
            source="heartbeat_pre_session",
        )

        signals = collect_signals(db, user)

        # Build prompt via ReminderRole
        system, prompt = build_reminder_prompt(
            user=user,
            key_session=key_session,
            time_context=time_context,
            signals_block=format_signals_for_prompt(signals),
            facts_block=format_active_facts_for_prompt(db, user),
            calibration_need=calibration_need,
        )

        llm_msg = _llm_generate(system, prompt, pipeline="heartbeat_reminder")
        if llm_msg:
            memory_updates = []
            if calibration_need is not None and looks_like_clarification_message(llm_msg):
                memory_updates.append(calibration_need.as_memory_update())
            return CoachDraft(text=llm_msg, proactive=True, memory_updates=memory_updates)

        label = key_session.label or DAY_LABELS[NEXT_DAY[today_key]]
        msg = f"Demain c'est {key_session.session_title}. Tu te sens comment pour {label.lower()} ?"
        fact_lines = get_active_fact_lines(db, user)
        if fact_lines:
            msg += "\nA noter: " + "; ".join(line.lstrip("- ") for line in fact_lines[:2]) + "."
        return CoachDraft(text=msg, proactive=True)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Weekly review (ReviewRole)
# ---------------------------------------------------------------------------

def weekly_review() -> CoachDraft | None:
    """Generate a Sunday evening weekly review draft without side effects."""
    db = SessionLocal()
    try:
        user = repo.get_user(db)
        local_today = get_local_now(user.timezone).date()
        start_date = local_today - timedelta(days=6)
        scheduled_sessions = repo.get_scheduled_sessions(db, user.id, limit=120)
        activities = repo.get_activities(db, user.id, limit=500)
        planning_decision = repo.get_latest_planning_decision_record(db, user.id)
        coach_bundle = build_coach_state_bundle(
            db,
            user=user,
            today_date=local_today,
            scheduled_sessions=scheduled_sessions,
            activities=activities,
            planning_decision=planning_decision,
            recent_adaptations_limit=4,
            screen="review",
        )
        week_sessions = [
            session
            for session in scheduled_sessions
            if session.scheduled_date and start_date <= session.scheduled_date.date() <= local_today
        ]

        lines = []
        done_count = int(coach_bundle.week_summary.get("done") or 0)
        planned_count = int(coach_bundle.week_summary.get("remaining") or 0)
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
                elif session.completion_status == "planned":
                    status_marker = " (pas fait)"
                elif session.completion_status in ("skipped", "adapted"):
                    status_marker = f" ({session.completion_status})"
            lines.append(f"- {label}: {session.session_title}{status_marker}")
        week_text = "\n".join(lines)

        time_context = build_time_context(user.timezone)

        # Recent reality + deterministic facts, so weekly_review can name
        # offplan sorties (sport + day) without an extra LLM lens pre-pass.
        try:
            recent_reality = build_recent_reality_window(
                today=local_today,
                scheduled_sessions=week_sessions,
                activities=recent_activities,
                claims=list(recent_claims),
            )
        except Exception:
            logger.warning("Weekly review: failed to build recent reality window", exc_info=True)
            recent_reality = None

        try:
            facts = build_coach_reading_facts(
                db, user,
                today=local_today,
                recent_reality=recent_reality,
            )
            digest = CoachReadingDigest(facts=facts, lens=None)
        except Exception:
            logger.warning("Weekly review: failed to build deterministic reading facts", exc_info=True)
            digest = None

        # Build prompt via ReviewRole
        system, prompt = build_review_prompt(
            user=user,
            time_context=time_context,
            week_text=week_text,
            done_count=done_count,
            planned_count=planned_count,
            total_sessions=int(coach_bundle.week_summary.get("total_sessions") or len(week_sessions)),
            actual_activity_count=actual_activity_count,
            actual_duration_min=actual_duration_min,
            claimed_activity_count=claimed_activity_count,
            claimed_duration_min=claimed_duration_min,
            facts_block=format_active_facts_for_prompt(db, user),
            weekly_highlights=_weekly_review_highlights(db, user, start_date=start_date),
            digest=digest,
        )

        llm_msg = _llm_generate(system, prompt, allow_no_send=False, pipeline="heartbeat_review")
        if llm_msg:
            return CoachDraft(text=llm_msg, proactive=True)

        msg = "Fin de semaine. Le plan a tenu ses reperes. On prend de la marge pour la suite."
        return CoachDraft(text=msg, proactive=True)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Signal check (SignalRole)
# ---------------------------------------------------------------------------

def signal_check() -> CoachDraft | None:
    """Check signals and generate a proactive message if anything actionable is found."""
    db = SessionLocal()
    try:
        user = repo.get_user(db)

        gate = heartbeat_evaluation.evaluate_proactive_gate(
            db, user,
            require_recent_exchange_gap=True,
            recent_exchange_hours=RECENT_EXCHANGE_HOURS,
        )
        if not gate.allowed:
            logger.info("Signal check skipped — %s", str(gate.reason or "blocked").replace("_", " "))
            return None

        # Adaptive plan triggers
        try:
            from fitmas.adaptation import check_and_adapt_tsb, check_and_adapt_missed
            tsb_result = check_and_adapt_tsb(db, user)
            if tsb_result and tsb_result.decisions and tsb_result.message:
                return CoachDraft(text=tsb_result.message, proactive=True)
            missed_result = check_and_adapt_missed(db, user)
            if missed_result and missed_result.decisions and missed_result.message:
                return CoachDraft(text=missed_result.message, proactive=True)
        except Exception:
            logger.exception("Adaptation trigger check failed (non-blocking)")

        signals = collect_signals(db, user)
        if not signals:
            return None

        actionable = [s for s in signals if s["severity"] in ("warning", "action")]
        if not actionable:
            big_session = next((s for s in signals if s["kind"] == "big_session_done"), None)
            if not big_session:
                return None
            actionable = [big_session]

        time_context = build_time_context(user.timezone)

        # Build prompt via SignalRole
        system, prompt = build_signal_prompt(
            user=user,
            time_context=time_context,
            signals_block=format_signals_for_prompt(actionable),
            facts_block=format_active_facts_for_prompt(db, user),
        )

        llm_msg = _llm_generate(system, prompt, pipeline="heartbeat_signal")
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

        fact_lines = get_active_fact_lines(db, user)
        if fact_lines:
            msg += "\nA noter: " + "; ".join(line.lstrip("- ") for line in fact_lines[:2]) + "."

        return CoachDraft(text=msg, proactive=True)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Fallback summary (LLM outage path)
# ---------------------------------------------------------------------------

def _yesterday_fallback_summary(yesterday) -> str:
    """One-line plain-text summary of yesterday's truth for the LLM-outage
    fallback path. The LLM-driven prompt now consumes the structured bundle
    directly (see `build_briefing_prompt`); this helper only fires when the
    LLM call returned nothing."""
    if yesterday.status in ("rest", "no_plan_no_activity"):
        return ""
    chunks: list[str] = []
    if yesterday.activities:
        for activity in yesterday.activities:
            link = "lié au plan" if activity.linked_to_plan else "hors plan"
            chunks.append(f"{activity.sport} {activity.duration_min}min ({link})")
    if not chunks and yesterday.planned_sessions:
        for session in yesterday.planned_sessions:
            chunks.append(f"{session.sport} prévu — pas de trace")
    if not chunks:
        return ""
    return f"Hier ({yesterday.day_label}): " + ", ".join(chunks) + "."


def _weekly_review_highlights(db: Session, user: s.User, *, start_date) -> str:
    turns = repo.get_recent_conversation_turns(db, user.id, limit=40)
    keywords = (
        "malade",
        "maladie",
        "virus",
        "grippe",
        "fievre",
        "fièvre",
        "rince",
        "fatigu",
        "pas dispo",
        "indispo",
        "repos complet",
        "je peux pas",
        "je ne peux pas",
    )
    highlights: list[str] = []
    for turn in reversed(turns):
        created_at = getattr(turn, "created_at", None)
        if created_at is None or created_at.date() < start_date:
            continue
        user_message = str(getattr(turn, "user_message", "") or "").strip()
        assistant_message = str(getattr(turn, "assistant_message", "") or "").strip()
        lowered_user = user_message.lower()
        if user_message and any(keyword in lowered_user for keyword in keywords):
            highlights.append(f"- utilisateur: {user_message}")
        elif getattr(turn, "response_mode", "") == "health_adaptation" and assistant_message:
            highlights.append(f"- coach: {assistant_message}")
        if len(highlights) >= 3:
            break
    return "\n".join(highlights)


RECENT_PROACTIVE_TTL_HOURS = 48


def _recent_proactive_context(
    db: Session,
    user: s.User,
    *,
    limit: int = 2,
    ttl_hours: int = RECENT_PROACTIVE_TTL_HOURS,
) -> str:
    """Recent proactive messages, bounded by TTL to avoid stale chiffres injection.

    Bug 2026-05-02: without TTL filter, an old briefing from a previous week
    resurfaced in today's prompt, and the LLM copied its weekly stats as if
    they applied to the current week. The cutoff ensures only proactives
    recent enough to be relevant context can leak in.

    TTL = 48h covers "yesterday + today" for novelty avoidance (don't recycle
    the same opening formula day-to-day) while excluding any briefing >2 days
    old whose chiffres semaine could leak.
    """
    local_now = get_local_now(user.timezone)
    utc_cutoff = (local_now - timedelta(hours=ttl_hours)).astimezone(dt_timezone.utc).replace(tzinfo=None)
    rows = (
        db.query(s.CoachMessage)
        .filter(
            s.CoachMessage.user_id == user.id,
            s.CoachMessage.role == "agent",
            s.CoachMessage.proactive.is_(True),
            s.CoachMessage.created_at >= utc_cutoff,
        )
        .order_by(s.CoachMessage.created_at.desc(), s.CoachMessage.id.desc())
        .limit(limit)
        .all()
    )
    if not rows:
        return ""
    return "\n".join(
        f"- {str(row.text or '').strip()}"
        for row in reversed(rows)
        if str(row.text or "").strip()
    )


def _pending_open_question_for_user(db: Session, user: s.User) -> str | None:
    """If the latest agent message ended on an open question and the user has
    not since written anything, surface that question for the next proactive
    turn. Without this the briefing tends to silently drop unanswered prompts
    ("imprevu" pathology — coach asks then changes subject the next morning)."""
    latest_agent = (
        db.query(s.CoachMessage)
        .filter(s.CoachMessage.user_id == user.id, s.CoachMessage.role == "agent")
        .order_by(s.CoachMessage.created_at.desc(), s.CoachMessage.id.desc())
        .first()
    )
    if latest_agent is None:
        return None
    question = detect_open_question(str(latest_agent.text or ""))
    if not question:
        return None
    latest_user = (
        db.query(s.CoachMessage)
        .filter(s.CoachMessage.user_id == user.id, s.CoachMessage.role == "user")
        .order_by(s.CoachMessage.created_at.desc(), s.CoachMessage.id.desc())
        .first()
    )
    if latest_user is not None and latest_user.created_at and latest_agent.created_at:
        if latest_user.created_at >= latest_agent.created_at:
            return None
    return question
