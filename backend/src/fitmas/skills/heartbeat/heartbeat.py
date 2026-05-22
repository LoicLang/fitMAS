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
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field, is_dataclass, replace
from datetime import date, datetime, timedelta, timezone as dt_timezone
from typing import Any, Iterator

from sqlalchemy.orm import Session

from fitmas import repository as repo, schema as s
from fitmas.domain.coaching import coach_voice
from fitmas.domain.execution.helpers import (
    activities_last_days as _activities_last_days,
    activities_on_local_date as _activities_on_local_date,
    claimed_activities_last_days as _claimed_activities_last_days,
    claimed_activities_on_local_date as _claimed_activities_on_local_date,
)
from fitmas.domain.coaching.calibration_needs import CalibrationNeedType, looks_like_clarification_message
from fitmas.domain.coaching.coach_reading_digest import CoachReadingDigest, build_coach_reading_facts
from fitmas.domain.coaching.coach_state import build_coach_state_bundle
from fitmas.app.telegram.delivery import CoachDraft, DraftPendingConfirmation
from fitmas.core.db import SessionLocal
import fitmas.llm.reply_backend as reply_backend
from fitmas.domain.execution.clarification import build_execution_clarification
from fitmas.decision.grounding import ReplyGroundingPacket, plan_window_facts_from_sessions
from fitmas.skills.heartbeat import evaluation as heartbeat_evaluation
from fitmas.skills.heartbeat import reply_composer as heartbeat_reply
from fitmas.skills.heartbeat.context import build_heartbeat_context_bundle
from fitmas.skills.heartbeat.reply_context import (
    build_briefing_reply_context,
    build_reminder_reply_context,
    build_review_reply_context,
    build_signal_reply_context,
)
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
from fitmas.llm.gateway import generate_heartbeat_text, generate_heartbeat_text_with_debug, request_text
from fitmas.llm.prompts.conversation_builder import detect_open_question
from fitmas.domain.planning.mutation_permissions import default_confirmation_expiry, serialize_plan_patch_confirmation
from fitmas.domain.planning.plan_patch import PlanPatch, PlanPatchValidation, plan_patch_from_mutation_decisions, validate_plan_patch
from fitmas.domain.execution.recent_reality import build_recent_reality_window
from fitmas.domain.coaching.signals import collect_signals, format_signals_for_prompt
from fitmas.skills.heartbeat.tool_loop import (
    generate_heartbeat_text_with_tools_debug,
    heartbeat_read_tools_enabled,
)
from fitmas.core.time_context import build_time_context, get_local_now
from fitmas.tools.contract import ToolContext

logger = logging.getLogger(__name__)

PROACTIVE_COOLDOWN_HOURS = heartbeat_evaluation.PROACTIVE_COOLDOWN_HOURS
RECENT_EXCHANGE_HOURS = heartbeat_evaluation.RECENT_EXCHANGE_HOURS
MAX_PROACTIVE_MESSAGES_PER_DAY = heartbeat_evaluation.MAX_PROACTIVE_MESSAGES_PER_DAY
MODULE_GUARD_WINDOW = heartbeat_evaluation.MODULE_GUARD_WINDOW
_LAST_PROACTIVE_GUARD_AT = heartbeat_evaluation.LAST_PROACTIVE_GUARD_AT


@dataclass
class HeartbeatDebugTrace:
    kind: str
    pipeline: str | None = None
    gate: dict[str, Any] | None = None
    context: dict[str, Any] = field(default_factory=dict)
    prompt: dict[str, Any] = field(default_factory=dict)
    llm: dict[str, Any] = field(default_factory=dict)
    tools: dict[str, Any] = field(default_factory=dict)
    judge: dict[str, Any] = field(default_factory=dict)
    judges: list[dict[str, Any]] = field(default_factory=list)
    decision: dict[str, Any] = field(default_factory=dict)
    final: dict[str, Any] = field(default_factory=lambda: {"message": None})

    def to_dict(self) -> dict[str, Any]:
        context = _debug_jsonable(self.context)
        tools = _debug_jsonable(self.tools)
        final = _debug_jsonable(self.final)
        judges = _debug_jsonable(self.judges or ([self.judge] if self.judge else []))
        return {
            "kind": self.kind,
            "pipeline": self.pipeline,
            "gate": self.gate,
            "context": context,
            "prompt": self.prompt,
            "llm": self.llm,
            "tools": tools,
            "judge": self.judge,
            "judges": judges,
            "decision": self.decision,
            "final": final,
            "flow": {
                "truth": _debug_flow_truth(context),
                "draft": self.llm,
                "composer": final.get("composer") or {},
                "judges": judges,
                "decision": self.decision,
                "final": final,
            },
        }


_DEBUG_TRACE: ContextVar[HeartbeatDebugTrace | None] = ContextVar("heartbeat_debug_trace", default=None)
_PENDING_CONFIRMATION: ContextVar[DraftPendingConfirmation | None] = ContextVar(
    "heartbeat_pending_confirmation",
    default=None,
)

_READONLY_CLAIM_JUDGE_SYSTEM = (
    "Tu es un juge de securite FitMAS. Tu lis uniquement un message heartbeat "
    "deja genere par l'assistant. Ce heartbeat est read-only : aucun changement "
    "de planning n'a ete commit sur ce tour, aucun event de mutation n'existe.\n\n"
    "Reponds exactement ALLOW ou BLOCK.\n"
    "BLOCK si le message affirme ou implique fortement qu'une action planning "
    "a deja ete faite par FitMAS: j'ai ajuste le planning, j'ai bascule, "
    "j'ai remplace, c'est pose/cale/verrouille, regarde ton app parce que "
    "le planning a change.\n"
    "BLOCK aussi si le heartbeat read-only annonce un planning futur comme deja "
    "decide sans confirmation ni event: on place X lundi, on pose la semaine, "
    "on garde/remplace/decale X, on allege Y, on recentre sur Z. Meme au futur, "
    "si la phrase sonne comme une decision appliquee ou un plan fixe, BLOCK.\n"
    "Exemples BLOCK: 'Pour la semaine prochaine, on replace les deux seances "
    "manquees sur lundi et mercredi', 'on garde mercredi libre mais on le "
    "remplace par du running', 'demain on bascule tout en course'.\n"
    "ALLOW si c'est une proposition, une question, une intention future, une "
    "orientation de coaching, une observation, ou une action faite par le user. "
    "Les marqueurs de proposition explicites sont par exemple: je propose, "
    "on peut, si tu veux, si tu confirmes, tu veux qu'on, il faudra."
)

def _reserve_module_guard(user_id: int, *, now=None) -> None:
    heartbeat_evaluation.reserve_module_guard(user_id, now=now)


@contextmanager
def capture_debug_trace(kind: str) -> Iterator[HeartbeatDebugTrace]:
    trace = HeartbeatDebugTrace(kind=kind)
    token = _DEBUG_TRACE.set(trace)
    try:
        yield trace
    finally:
        _DEBUG_TRACE.reset(token)


def _trace() -> HeartbeatDebugTrace | None:
    return _DEBUG_TRACE.get()


def _take_pending_confirmation() -> DraftPendingConfirmation | None:
    pending = _PENDING_CONFIRMATION.get()
    _PENDING_CONFIRMATION.set(None)
    return pending


def _debug_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _debug_jsonable(asdict(value))
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _debug_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_debug_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _debug_flow_truth(context: dict[str, Any]) -> dict[str, Any]:
    preferred_keys = (
        "time_context",
        "heartbeat_bundle",
        "local_today",
        "tomorrow_sessions",
        "scheduled_sessions",
        "activities",
    )
    selected = {key: context[key] for key in preferred_keys if key in context}
    return selected or context


def _trace_gate(gate: Any) -> None:
    trace = _trace()
    if trace is None:
        return
    trace.gate = {
        "allowed": bool(getattr(gate, "allowed", False)),
        "reason": getattr(gate, "reason", None),
    }


def _trace_context(name: str, value: Any) -> None:
    trace = _trace()
    if trace is not None:
        trace.context[name] = value


def _trace_decision(action: str, reason: str) -> None:
    trace = _trace()
    if trace is not None:
        trace.decision = {"action": action, "reason": reason}


def _trace_final(message: str | None) -> None:
    trace = _trace()
    if trace is not None:
        trace.final["message"] = message


def _trace_judge(name: str, payload: dict[str, Any]) -> None:
    trace = _trace()
    if trace is None:
        return
    entry = {"name": name, **payload}
    trace.judge = payload
    trace.judges.append(entry)


def _heartbeat_tool_context(
    db: Session,
    user: s.User,
    *,
    now: datetime | None = None,
    scheduled_sessions: list[Any] | tuple[Any, ...] | None = None,
    activities: list[Any] | tuple[Any, ...] | None = None,
) -> ToolContext:
    return ToolContext(
        pipeline="heartbeat",
        user_id=user.id,
        timezone_name=user.timezone,
        db=db,
        now=now or get_local_now(user.timezone),
        scheduled_sessions=tuple(scheduled_sessions if scheduled_sessions is not None else repo.get_scheduled_sessions(db, user.id, limit=120)),
        activities=tuple(activities if activities is not None else repo.get_activities(db, user.id, limit=200)),
        active_facts=tuple(repo.get_active_facts(db, user.id, limit=60)),
    )


def _llm_generate(
    system: str,
    prompt: str,
    *,
    allow_no_send: bool = True,
    pipeline: str = "heartbeat",
    tool_context: ToolContext | None = None,
    factual_grounding: ReplyGroundingPacket | None = None,
    heartbeat_reply_context: heartbeat_reply.HeartbeatReplyContext | None = None,
) -> str | None:
    _PENDING_CONFIRMATION.set(None)
    trace = _trace()
    use_tools = heartbeat_read_tools_enabled(tool_context)
    if trace is not None:
        trace.pipeline = pipeline
        trace.prompt = {"system": system, "user": prompt}
        generation = (
            generate_heartbeat_text_with_tools_debug(
                system,
                prompt,
                allow_no_send=allow_no_send,
                tool_context=tool_context,
            )
            if use_tools
            else generate_heartbeat_text_with_debug(system, prompt, allow_no_send=allow_no_send)
        )
        if isinstance(generation, dict):
            text = generation.get("text")
            pending_confirmation = _pending_confirmation_from_tool_generation(
                generation,
                text=str(text or ""),
                pipeline=pipeline,
            )
            _PENDING_CONFIRMATION.set(pending_confirmation)
            trace.llm = {
                "raw_text": generation.get("raw_text"),
                "text": text,
                "reason": generation.get("reason"),
                "allow_no_send": generation.get("allow_no_send", allow_no_send),
            }
            if generation.get("tools") is not None:
                trace.tools = generation.get("tools") or {}
            if pending_confirmation is not None:
                trace.final["pending_confirmation"] = {
                    "mutation_type": pending_confirmation.mutation_type,
                    "summary": pending_confirmation.summary,
                    "reason": pending_confirmation.reason,
                }
        else:
            text = generation.text
            trace.llm = {
                "raw_text": generation.raw_text,
                "text": text,
                "reason": generation.reason,
                "allow_no_send": generation.allow_no_send,
            }
    else:
        if use_tools:
            generation = generate_heartbeat_text_with_tools_debug(
                system,
                prompt,
                allow_no_send=allow_no_send,
                tool_context=tool_context,
            )
            text = str(generation.get("text") or "").strip() or None
            _PENDING_CONFIRMATION.set(
                _pending_confirmation_from_tool_generation(
                    generation,
                    text=str(text or ""),
                    pipeline=pipeline,
                )
            )
        else:
            text = generate_heartbeat_text(system, prompt, allow_no_send=allow_no_send)
    if text and heartbeat_reply_context is not None:
        composer_context = replace(heartbeat_reply_context, draft=text)
        trace = _trace()
        if trace is not None:
            composer_system, composer_prompt = heartbeat_reply.build_heartbeat_reply_prompt(composer_context)
            trace.final["composer"] = {
                "draft": text,
                "input": {
                    "system": composer_system,
                    "user": composer_prompt,
                },
            }
        composed = heartbeat_reply.compose_heartbeat_reply(
            composer_context,
            request_text_fn=request_text,
        )
        trace = _trace()
        if composed is None:
            logger.warning("heartbeat.composer_blocked pipeline=%s message=%r", pipeline, text[:160])
            _trace_judge("heartbeat_composer", {"blocked": True, "reason": "heartbeat_composer_blocked"})
            _PENDING_CONFIRMATION.set(None)
            return None
        if trace is not None:
            trace.final.setdefault("composer", {"draft": text})
            trace.final["composer"]["output"] = composed
            trace.final["composer"]["text"] = composed
        text = composed
    # Chantier 1 - Etape D : log-only receipt-style detection sur les outputs
    # heartbeat (briefing / reminder / review / signal). Permet de mesurer le
    # taux de violation par pipeline avant de promouvoir en hard guard.
    if text and coach_voice.message_looks_receipt_style(text):
        logger.warning(
            "coach_voice.receipt_style pipeline=%s message=%r",
            pipeline,
            text[:160],
        )
    if text and pipeline.startswith("heartbeat") and _heartbeat_readonly_judge_blocks(text, pipeline=pipeline):
        logger.warning(
            "coach_voice.readonly_commit_claim pipeline=%s message=%r",
            pipeline,
            text[:160],
        )
        _PENDING_CONFIRMATION.set(None)
        return None
    if text and factual_grounding is not None:
        verified = reply_backend.verify_factual_reply(
            text,
            grounding=factual_grounding,
            pipeline_capability=pipeline,
            request_text_fn=request_text,
        )
        if verified is None:
            logger.warning("heartbeat.factual_verifier_blocked pipeline=%s message=%r", pipeline, text[:160])
            _trace_judge("factual_verifier", {"blocked": True, "reason": "factual_verifier_blocked"})
            _PENDING_CONFIRMATION.set(None)
            return None
        _trace_judge("factual_verifier", {"blocked": False, "reason": "allow", "changed": verified != text})
        text = verified
    return text


def _pending_confirmation_from_tool_generation(
    generation: dict[str, Any],
    *,
    text: str,
    pipeline: str,
) -> DraftPendingConfirmation | None:
    normalized_text = coach_voice.normalize_for_voice_guard(text)
    if "confirm" not in normalized_text:
        return None
    candidate = generation.get("candidate_plan_patch")
    if not isinstance(candidate, dict):
        return None
    raw_patch = candidate.get("patch")
    if not isinstance(raw_patch, dict):
        return None
    validation = candidate.get("validation")
    if not isinstance(validation, dict):
        return None
    status = str(validation.get("status") or "").strip()
    if status not in {"valid", "warning", "requires_confirmation"}:
        return None
    try:
        patch = PlanPatch.model_validate(raw_patch)
    except Exception:
        logger.warning("heartbeat.pending_plan_patch_invalid pipeline=%s", pipeline, exc_info=True)
        return None
    summary = str(candidate.get("summary") or validation.get("summary") or "ajustement proactif a confirmer").strip()
    return DraftPendingConfirmation(
        impact_level="high",
        reason=f"{pipeline}_validated_plan_patch",
        mutation_type="plan_patch",
        summary=summary,
        source_text=text,
        decision_json=serialize_plan_patch_confirmation(patch),
        expires_at=default_confirmation_expiry(),
    )


def _heartbeat_readonly_judge_blocks(text: str, *, pipeline: str) -> bool:
    prompt = (
        f"Pipeline: {pipeline}\n\n"
        "events_committed: []\n"
        "capability: read_only\n\n"
        "Message heartbeat a juger:\n"
        f"{text.strip()}\n\n"
        "Decision:"
    )
    try:
        decision = request_text(system=_READONLY_CLAIM_JUDGE_SYSTEM, prompt=prompt, max_tokens=8)
    except Exception:
        logger.exception("heartbeat.readonly_claim_judge_error pipeline=%s", pipeline)
        _trace_judge("read_only_claim", {"decision": None, "blocked": True, "reason": "judge_error"})
        return True
    normalized = coach_voice.normalize_for_voice_guard(decision or "")
    if normalized.startswith("allow"):
        _trace_judge("read_only_claim", {"decision": decision, "blocked": False, "reason": "allow"})
        return False
    if normalized.startswith("block"):
        _trace_judge("read_only_claim", {"decision": decision, "blocked": True, "reason": "block"})
        return True
    logger.warning(
        "heartbeat.readonly_claim_judge_invalid pipeline=%s decision=%r",
        pipeline,
        decision,
    )
    _trace_judge("read_only_claim", {"decision": decision, "blocked": True, "reason": "invalid_judge_response"})
    return True


# ---------------------------------------------------------------------------
# Morning briefing (BriefingRole)
# ---------------------------------------------------------------------------

def morning_briefing() -> CoachDraft | None:
    """Generate the morning briefing message for today, aware of yesterday's status."""
    db = SessionLocal()
    try:
        user = repo.get_user(db)

        gate = heartbeat_evaluation.evaluate_proactive_gate(db, user)
        _trace_gate(gate)
        if not gate.allowed:
            logger.info("Morning briefing skipped — %s", str(gate.reason or "blocked").replace("_", " "))
            _trace_decision("no_send", str(gate.reason or "gate_blocked"))
            _trace_final(None)
            return None

        time_context = build_time_context(user.timezone)
        _trace_context("time_context", time_context)
        local_now = get_local_now(user.timezone)
        today_session = repo.get_today_scheduled_session(db, user.id, timezone_name=user.timezone)
        if not today_session:
            _trace_decision("no_send", "no_today_session")
            _trace_final(None)
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
        future_sessions = repo.get_scheduled_sessions_between_dates(
            db,
            user.id,
            start_date=local_now.date(),
            end_date=local_now.date() + timedelta(days=6),
            limit=21,
        )
        tool_scheduled_sessions = repo.get_scheduled_sessions(db, user.id, limit=120)
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
            future_scheduled_sessions=future_sessions,
            capability=BRIEFING_ROLE.capability,
        )
        _trace_context("heartbeat_bundle", bundle)
        active_fact_lines = get_active_fact_lines(db, user)
        facts_block = (
            "\n\nFaits actifs a prendre en compte:\n" + "\n".join(active_fact_lines)
            if active_fact_lines
            else ""
        )
        reply_context = build_briefing_reply_context(
            bundle=bundle,
            time_context=time_context,
            active_fact_lines=active_fact_lines,
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
            facts_block=facts_block,
            sport_knowledge=load_sport_knowledge({today_session.sport_type}, max_tokens=500),
            recent_proactive_context=_recent_proactive_context(db, user, limit=2),
            pending_open_question=_pending_open_question_for_user(db, user),
        )

        llm_msg = _llm_generate(
            system,
            prompt,
            pipeline="heartbeat_briefing",
            tool_context=_heartbeat_tool_context(
                db,
                user,
                now=local_now,
                scheduled_sessions=tool_scheduled_sessions,
                activities=recent_activities,
            ),
            factual_grounding=ReplyGroundingPacket(
                local_date=local_now.date(),
                timezone_name=getattr(user, "timezone", None),
                plan_window=plan_window_facts_from_sessions(future_sessions),
            ),
            heartbeat_reply_context=reply_context,
        )
        if llm_msg:
            memory_updates = []
            if effective_calibration_need is not None and looks_like_clarification_message(llm_msg):
                memory_updates.append(effective_calibration_need.as_memory_update())
            _trace_decision("send", "llm_message")
            _trace_final(llm_msg)
            return CoachDraft(
                text=llm_msg,
                proactive=True,
                memory_updates=memory_updates,
                pending_confirmation=_take_pending_confirmation(),
            )

        # Fallback
        if clarification is not None:
            _trace_decision("send", "fallback_after_llm_no_message")
            _trace_final(clarification.question)
            return CoachDraft(text=clarification.question, proactive=True)
        label = today_session.label or DAY_LABELS[time_context["day_key"]]
        msg = (
            f"Bonjour. {label} — {today_session.session_title}.\n"
            f"{today_session.session_goal}. Priorite: {today_session.priority}."
        )
        yesterday_summary = _yesterday_fallback_summary(bundle.yesterday)
        if yesterday_summary:
            msg += f"\n{yesterday_summary}"
        if active_fact_lines:
            msg += "\nA noter: " + "; ".join(line.lstrip("- ") for line in active_fact_lines[:2]) + "."
        _trace_decision("send", "fallback_after_llm_no_message")
        _trace_final(msg)
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
        _trace_gate(gate)
        if not gate.allowed:
            logger.info("Pre-session reminder skipped — %s", str(gate.reason or "blocked").replace("_", " "))
            _trace_decision("no_send", str(gate.reason or "gate_blocked"))
            _trace_final(None)
            return None

        time_context = build_time_context(user.timezone)
        _trace_context("time_context", time_context)
        today_key = time_context["day_key"]
        tomorrow_date = get_local_now(user.timezone).date() + timedelta(days=1)
        tomorrow_sessions = [
            session for session in repo.get_scheduled_sessions_for_date(db, user.id, target_date=tomorrow_date)
            if session.sport_type != "rest"
        ]
        _trace_context("tomorrow_sessions", tomorrow_sessions)
        if not tomorrow_sessions:
            _trace_decision("no_send", "no_tomorrow_session")
            _trace_final(None)
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
            _trace_decision("no_send", "no_key_session")
            _trace_final(None)
            return None

        calibration_need = select_calibration_need(
            db, user,
            preferred_types=(CalibrationNeedType.FATIGUE_STATE,),
            today=get_local_now(user.timezone).date(),
            source="heartbeat_pre_session",
        )

        signals = collect_signals(db, user)
        active_fact_lines = get_active_fact_lines(db, user)
        facts_block = (
            "\n\nFaits actifs a prendre en compte:\n" + "\n".join(active_fact_lines)
            if active_fact_lines
            else ""
        )
        reply_context = build_reminder_reply_context(
            key_session=key_session,
            time_context=time_context,
            active_fact_lines=active_fact_lines,
        )

        # Build prompt via ReminderRole
        system, prompt = build_reminder_prompt(
            user=user,
            key_session=key_session,
            time_context=time_context,
            signals_block=format_signals_for_prompt(signals),
            facts_block=facts_block,
            calibration_need=calibration_need,
        )

        llm_msg = _llm_generate(
            system,
            prompt,
            pipeline="heartbeat_reminder",
            tool_context=_heartbeat_tool_context(
                db,
                user,
                now=get_local_now(user.timezone),
            ),
            heartbeat_reply_context=reply_context,
        )
        if llm_msg:
            memory_updates = []
            if calibration_need is not None and looks_like_clarification_message(llm_msg):
                memory_updates.append(calibration_need.as_memory_update())
            _trace_decision("send", "llm_message")
            _trace_final(llm_msg)
            return CoachDraft(
                text=llm_msg,
                proactive=True,
                memory_updates=memory_updates,
                pending_confirmation=_take_pending_confirmation(),
            )

        label = key_session.label or DAY_LABELS[NEXT_DAY[today_key]]
        msg = f"Demain c'est {key_session.session_title}. Tu te sens comment pour {label.lower()} ?"
        if active_fact_lines:
            msg += "\nA noter: " + "; ".join(line.lstrip("- ") for line in active_fact_lines[:2]) + "."
        _trace_decision("send", "fallback_after_llm_no_message")
        _trace_final(msg)
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
        _trace_context("local_today", local_today)
        start_date = local_today - timedelta(days=6)
        scheduled_sessions = repo.get_scheduled_sessions(db, user.id, limit=120)
        activities = repo.get_activities(db, user.id, limit=500)
        _trace_context("scheduled_sessions", scheduled_sessions)
        _trace_context("activities", activities[:20])
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

        active_fact_lines = get_active_fact_lines(db, user)
        facts_block = (
            "\n\nFaits actifs a prendre en compte:\n" + "\n".join(active_fact_lines)
            if active_fact_lines
            else ""
        )
        weekly_highlights = _weekly_review_highlights(db, user, start_date=start_date)
        reply_context = build_review_reply_context(
            week_sessions=week_sessions,
            time_context=time_context,
            done_count=done_count,
            planned_count=planned_count,
            total_sessions=int(coach_bundle.week_summary.get("total_sessions") or len(week_sessions)),
            actual_activity_count=actual_activity_count,
            actual_duration_min=actual_duration_min,
            claimed_activity_count=claimed_activity_count,
            claimed_duration_min=claimed_duration_min,
            active_fact_lines=active_fact_lines,
            weekly_highlights=weekly_highlights,
        )

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
            facts_block=facts_block,
            weekly_highlights=weekly_highlights,
            digest=digest,
        )

        llm_msg = _llm_generate(
            system,
            prompt,
            allow_no_send=False,
            pipeline="heartbeat_review",
            tool_context=_heartbeat_tool_context(
                db,
                user,
                now=get_local_now(user.timezone),
                scheduled_sessions=scheduled_sessions,
                activities=activities,
            ),
            heartbeat_reply_context=reply_context,
        )
        if llm_msg:
            _trace_decision("send", "llm_message")
            _trace_final(llm_msg)
            return CoachDraft(text=llm_msg, proactive=True, pending_confirmation=_take_pending_confirmation())

        msg = "Fin de semaine. Le plan a tenu ses reperes. On prend de la marge pour la suite."
        _trace_decision("send", "fallback_after_llm_no_message")
        _trace_final(msg)
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
        _trace_gate(gate)
        if not gate.allowed:
            logger.info("Signal check skipped — %s", str(gate.reason or "blocked").replace("_", " "))
            _trace_decision("no_send", str(gate.reason or "gate_blocked"))
            _trace_final(None)
            return None

        # Adaptive plan triggers
        try:
            from fitmas.adaptation import check_and_adapt_tsb, check_and_adapt_missed
            tsb_result = check_and_adapt_tsb(db, user)
            if tsb_result and tsb_result.decisions and tsb_result.message:
                draft = _adaptation_plan_patch_confirmation_draft(
                    db,
                    user=user,
                    result=tsb_result,
                    reason="heartbeat_tsb_adaptation",
                )
                if draft is not None:
                    _trace_decision("send", "tsb_adaptation_confirmation")
                    _trace_final(draft.text)
                    return draft
            missed_result = check_and_adapt_missed(db, user)
            if missed_result and missed_result.decisions and missed_result.message:
                draft = _adaptation_plan_patch_confirmation_draft(
                    db,
                    user=user,
                    result=missed_result,
                    reason="heartbeat_missed_session_adaptation",
                )
                if draft is not None:
                    _trace_decision("send", "missed_session_adaptation_confirmation")
                    _trace_final(draft.text)
                    return draft
        except Exception:
            logger.exception("Adaptation trigger check failed (non-blocking)")

        signals = collect_signals(db, user)
        _trace_context("signals", signals)
        if not signals:
            _trace_decision("no_send", "no_signals")
            _trace_final(None)
            return None

        actionable = [s for s in signals if s["severity"] in ("warning", "action")]
        if not actionable:
            big_session = next((s for s in signals if s["kind"] == "big_session_done"), None)
            if not big_session:
                _trace_decision("no_send", "no_actionable_signal")
                _trace_final(None)
                return None
            actionable = [big_session]
        _trace_context("actionable_signals", actionable)

        time_context = build_time_context(user.timezone)
        _trace_context("time_context", time_context)
        active_fact_lines = get_active_fact_lines(db, user)
        facts_block = (
            "\n\nFaits actifs a prendre en compte:\n" + "\n".join(active_fact_lines)
            if active_fact_lines
            else ""
        )
        reply_context = build_signal_reply_context(
            actionable_signals=actionable,
            time_context=time_context,
            active_fact_lines=active_fact_lines,
        )

        # Build prompt via SignalRole
        system, prompt = build_signal_prompt(
            user=user,
            time_context=time_context,
            signals_block=format_signals_for_prompt(actionable),
            facts_block=facts_block,
        )

        llm_msg = _llm_generate(
            system,
            prompt,
            pipeline="heartbeat_signal",
            tool_context=_heartbeat_tool_context(
                db,
                user,
                now=get_local_now(user.timezone),
            ),
            heartbeat_reply_context=reply_context,
        )
        if llm_msg:
            _trace_decision("send", "llm_message")
            _trace_final(llm_msg)
            return CoachDraft(text=llm_msg, proactive=True, pending_confirmation=_take_pending_confirmation())

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

        if active_fact_lines:
            msg += "\nA noter: " + "; ".join(line.lstrip("- ") for line in active_fact_lines[:2]) + "."

        _trace_decision("send", "fallback_after_llm_no_message")
        _trace_final(msg)
        return CoachDraft(text=msg, proactive=True)
    finally:
        db.close()


def _adaptation_plan_patch_confirmation_draft(
    db: Session,
    *,
    user: s.User,
    result: Any,
    reason: str,
) -> CoachDraft | None:
    message = str(getattr(result, "message", "") or "").strip()
    patch = plan_patch_from_mutation_decisions(
        getattr(result, "decisions", ()) or (),
        coach_message=message or "Je te propose un ajustement de planning.",
        confirmation_reason=reason,
    )
    if not patch.operations:
        return None
    validation = validate_plan_patch(
        db,
        plan_id=0,
        patch=patch,
        scheduled_sessions=repo.get_scheduled_sessions(db, user.id, limit=120),
        timezone_name=user.timezone,
    )
    if validation.status == "blocked":
        logger.info(
            "heartbeat.plan_patch_candidate_blocked user=%s reason=%s summary=%s",
            user.id,
            reason,
            validation.summary,
        )
        return None
    summary = _heartbeat_plan_patch_confirmation_summary(validation)
    text = _heartbeat_confirmation_message(message, summary)
    return CoachDraft(
        text=text,
        proactive=True,
        pending_confirmation=DraftPendingConfirmation(
            impact_level="high",
            reason=reason,
            mutation_type="plan_patch",
            summary=summary,
            source_text=text,
            decision_json=serialize_plan_patch_confirmation(patch),
            expires_at=default_confirmation_expiry(),
        ),
    )


def _heartbeat_plan_patch_confirmation_summary(validation: PlanPatchValidation) -> str:
    first = validation.operation_results[0] if validation.operation_results else None
    if first is not None:
        if first.warning_messages:
            return first.warning_messages[0]
        if first.suggested_fix:
            return first.suggested_fix
        if first.block_reason:
            return first.block_reason
    return validation.summary or "ajustement proactif a confirmer"


def _heartbeat_confirmation_message(message: str, summary: str) -> str:
    base = str(message or "").strip()
    normalized = coach_voice.normalize_for_voice_guard(base)
    if not base:
        return f"Je peux te proposer cet ajustement: {summary}. Tu confirmes ?"
    if "confirm" in normalized:
        return base
    proposal_markers = ("propose", "peux", "peut", "si tu veux", "si tu confirmes")
    if any(marker in normalized for marker in proposal_markers):
        return f"{base.rstrip(' .?!')} — tu confirmes ?"
    return f"Je peux te proposer cet ajustement: {summary}. Tu confirmes ?"


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
