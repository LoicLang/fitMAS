"""Operations plane — separated from the coaching tool plane.

Endpoints for debugging, manual triggers, and administrative actions.
All endpoints are prefixed with /ops/ and require debug mode.
These serve the operator/developer, not the LLM or the user.
"""
from __future__ import annotations

import json
import logging
from datetime import timedelta
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from fitmas import repository as repo, schema as s
from fitmas.app.api.payloads import IncomingMessage
from fitmas.app.api.support import ensure_debug_enabled
from fitmas.coach_messages import persist_draft
from fitmas.conversation_contract import (
    ConversationPipelineDependencies,
    ConversationTurnInput,
    ConversationUserNotFoundError,
)
from fitmas.db import get_db
from fitmas.skills.heartbeat.runtime_adapter import heartbeat_runtime_payload, run_heartbeat_endpoint, run_heartbeat_trigger
from fitmas.telegram_channel import resolve_chat_id, send_text_message

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ops", tags=["ops"])


# ---------------------------------------------------------------------------
# Conversation debug
# ---------------------------------------------------------------------------

@router.post("/conversation/debug")
def trigger_conversation_debug(payload: IncomingMessage, db: Session = Depends(get_db)) -> dict:
    """Run a normal conversation turn and expose the persisted debug flow."""
    ensure_debug_enabled()
    user = repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")

    from fitmas.app.api import routes_messages as api_messages
    from fitmas.conversation_pipeline import run_conversation_turn

    client_message_key = str(payload.client_message_key or "").strip() or f"ops-debug:{uuid4()}"
    try:
        reply = run_conversation_turn(
            ConversationTurnInput(
                text=payload.text,
                client_message_key=client_message_key,
                source=payload.source or "ops_debug",
            ),
            db=db,
            dependencies=ConversationPipelineDependencies(
                extract_facts=api_messages.extract_facts,
                check_and_adapt_health_facts=api_messages.check_and_adapt_health_facts,
                plan_turn=api_messages.plan_conversation_turn,
            ),
        )
    except ConversationUserNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    row = repo.get_conversation_turn_by_client_message_key(db, user.id, client_message_key)
    return {
        "kind": "conversation",
        "triggered": True,
        "client_message_key": client_message_key,
        "message": reply.assistant_message.text,
        "reply": reply.model_dump(mode="json"),
        "debug": _conversation_debug_payload(db, row) if row is not None else None,
    }


def _conversation_debug_payload(db: Session, row: s.ConversationTurnRecord) -> dict:
    context = _json_loads_object(row.context_json)
    decision = _json_loads_object(row.decision_json)
    memory_writes = _json_loads_list(row.memory_writes_json)
    pending_record = _conversation_pending_confirmation_record(db, row)
    mutation_events = _conversation_plan_mutation_events(db, row)
    turn = {
        "id": row.id,
        "response_mode": row.response_mode,
        "mutation_type": row.mutation_type,
        "mutation_applied": row.mutation_applied,
        "pending_confirmation": row.pending_confirmation,
        "pending_confirmation_id": row.pending_confirmation_id,
        "pending_confirmation_record": pending_record,
        "plan_mutation_events": mutation_events,
        "day_updated": row.day_updated,
        "client_message_key": row.client_message_key,
        "source": row.source,
    }
    final_reply = context.get("final_reply") if isinstance(context.get("final_reply"), dict) else {}
    composer = _conversation_flow_composer(row, decision, final_reply)
    flow_decision = {
        "response_mode": row.response_mode,
        "mutation_type": row.mutation_type,
        "mutation_applied": row.mutation_applied,
        "pending_confirmation": row.pending_confirmation,
        "pending_confirmation_id": row.pending_confirmation_id,
        "decision_json": decision,
        "decide_none": context.get("decide_none"),
    }
    return {
        "kind": "conversation",
        "turn": turn,
        "context": context,
        "decision_json": decision,
        "memory_writes": memory_writes,
        "flow": {
            "truth": _conversation_flow_truth(context),
            "draft": _conversation_flow_draft(decision, final_reply),
            "composer": composer,
            "runtime": turn,
            "decision": flow_decision,
            "final": {"message": row.assistant_message},
        },
    }


def _conversation_flow_truth(context: dict) -> dict:
    keys = (
        "turn_plan",
        "grounding",
        "planning_contract",
        "availability_state",
        "week_mission",
        "recent_reality",
        "week_context",
        "selected_fact_keys",
    )
    return {key: context[key] for key in keys if key in context}


def _conversation_flow_draft(decision: dict, final_reply: dict) -> dict:
    draft = dict(decision)
    if final_reply.get("draft"):
        draft["fitmas_message"] = final_reply.get("draft")
    return draft


def _conversation_flow_composer(
    row: s.ConversationTurnRecord,
    decision: dict,
    final_reply: dict,
) -> dict:
    if final_reply:
        return final_reply
    draft = str(decision.get("fitmas_message") or decision.get("coach_message") or "").strip()
    base = {
        "draft": draft,
        "output": row.assistant_message,
        "composed": False,
    }
    if row.pending_confirmation:
        return {
            **base,
            "capability": "pending_confirmation",
            "source": "runtime_pending_confirmation",
        }
    if row.mutation_applied or str(row.response_mode or "").endswith("_applied"):
        return {
            **base,
            "capability": "mutation_result",
            "source": "runtime_mutation_result",
        }
    if row.response_mode == "legacy_decision_contract_disabled":
        return {
            **base,
            "capability": "legacy_decision_contract_disabled",
            "source": "runtime_no_mutation",
        }
    if str(row.response_mode or "").endswith("_blocked"):
        return {
            **base,
            "capability": "mutation_blocked",
            "source": "runtime_mutation_result",
        }
    return {}


def _conversation_pending_confirmation_record(
    db: Session,
    row: s.ConversationTurnRecord,
) -> dict | None:
    if row.pending_confirmation_id is None:
        return None
    pending = (
        db.query(s.PendingMutationConfirmation)
        .filter(
            s.PendingMutationConfirmation.id == row.pending_confirmation_id,
            s.PendingMutationConfirmation.user_id == row.user_id,
        )
        .first()
    )
    if pending is None:
        return None
    return {
        "id": pending.id,
        "status": pending.status,
        "impact_level": pending.impact_level,
        "reason": pending.reason,
        "mutation_type": pending.mutation_type,
        "summary": pending.summary,
        "source_text": pending.source_text,
        "decision": _json_loads_object(pending.decision_json),
        "created_at": _isoformat_or_none(pending.created_at),
        "expires_at": _isoformat_or_none(pending.expires_at),
        "resolved_at": _isoformat_or_none(pending.resolved_at),
    }


def _conversation_plan_mutation_events(
    db: Session,
    row: s.ConversationTurnRecord,
) -> list[dict]:
    exact_rows = (
        db.query(s.PlanMutationEventRecord)
        .filter(
            s.PlanMutationEventRecord.user_id == row.user_id,
            s.PlanMutationEventRecord.conversation_turn_id == row.id,
        )
        .order_by(s.PlanMutationEventRecord.id.desc())
        .all()
    )
    if exact_rows:
        return [_serialize_plan_mutation_event(event, correlation="conversation_turn_id") for event in exact_rows]
    if not row.mutation_applied:
        return []
    lower_bound = row.created_at - timedelta(minutes=2) if row.created_at is not None else None
    query = db.query(s.PlanMutationEventRecord).filter(
        s.PlanMutationEventRecord.user_id == row.user_id,
        s.PlanMutationEventRecord.source == "conversation",
    )
    if lower_bound is not None:
        query = query.filter(s.PlanMutationEventRecord.created_at >= lower_bound)
    if row.created_at is not None:
        query = query.filter(s.PlanMutationEventRecord.created_at <= row.created_at + timedelta(seconds=5))
    events = query.order_by(s.PlanMutationEventRecord.id.desc()).limit(5).all()
    return [_serialize_plan_mutation_event(event, correlation="recent_conversation_event") for event in events]


def _serialize_plan_mutation_event(event: s.PlanMutationEventRecord, *, correlation: str) -> dict:
    return {
        "id": event.id,
        "source": event.source,
        "trigger_type": event.trigger_type,
        "command_type": event.command_type,
        "target_session_ids": _json_loads_list(event.target_session_ids_json),
        "before": _json_loads_object(event.before_snapshot_json),
        "after": _json_loads_object(event.after_snapshot_json),
        "reason": _json_loads_object(event.reason_json),
        "impact": _json_loads_object(event.impact_json),
        "user_visible_summary": event.user_visible_summary,
        "explained_to_user": event.explained_to_user,
        "conversation_turn_id": event.conversation_turn_id,
        "created_at": _isoformat_or_none(event.created_at),
        "correlation": correlation,
    }


def _isoformat_or_none(value) -> str | None:
    return value.isoformat() if value is not None else None


def _json_loads_object(raw_value: str | None) -> dict:
    try:
        loaded = json.loads(raw_value or "{}")
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _json_loads_list(raw_value: str | None) -> list:
    try:
        loaded = json.loads(raw_value or "[]")
    except Exception:
        return []
    return loaded if isinstance(loaded, list) else []


# ---------------------------------------------------------------------------
# Signal inspection
# ---------------------------------------------------------------------------

@router.get("/signals")
def get_signals(db: Session = Depends(get_db)) -> dict:
    """Inspect currently active signals for the user."""
    ensure_debug_enabled()
    user = repo.get_user_optional(db)
    if user is None:
        return {"signals": []}
    from fitmas.signals import collect_signals
    return {"signals": collect_signals(db, user)}


# ---------------------------------------------------------------------------
# Heartbeat triggers
# ---------------------------------------------------------------------------

@router.post("/heartbeat/{kind}")
def trigger_heartbeat(
    kind: str,
    send: bool = True,
    dump: bool = False,
    db: Session = Depends(get_db),
) -> dict:
    """Manually trigger a heartbeat generation and optional delivery."""
    ensure_debug_enabled()

    user = repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")

    import fitmas.skills.heartbeat.heartbeat as heartbeat

    handlers = {
        "morning": heartbeat.morning_briefing,
        "pre_session": heartbeat.pre_session_reminder,
        "signal_check": heartbeat.signal_check,
        "weekly_review": heartbeat.weekly_review,
    }
    handler = handlers.get(kind)
    if handler is None:
        raise HTTPException(status_code=400, detail=f"Unsupported heartbeat kind: {kind}")

    trace = None
    runtime_result = None
    if dump:
        with heartbeat.capture_debug_trace(kind) as captured:
            draft = handler()
            trace = captured
    else:
        runtime_result = run_heartbeat_endpoint(
            kind,
            handler,
            user_id=user.id,
            delivery_channel="ops",
        )
        draft = runtime_result.draft if runtime_result is not None else handler()
    if not draft:
        payload = {"kind": kind, "triggered": False, "sent": False, "reason": "no_op"}
        if runtime_result is not None:
            payload["runtime"] = heartbeat_runtime_payload(runtime_result)
        if dump and trace is not None:
            if not trace.decision:
                trace.decision = {"action": "no_send", "reason": "no_op"}
            trace.final = {"message": None}
            payload["debug"] = trace.to_dict()
        return payload

    sent = False
    delivery_error = None
    if send:
        chat_id = resolve_chat_id(db, user=user)
        if not chat_id:
            delivery_error = "missing_telegram_chat_id"
        else:
            try:
                sent = send_text_message(chat_id=chat_id, text=draft.text, parse_mode=draft.parse_mode)
                if sent:
                    persist_draft(user.id, draft, db=db)
            except Exception as exc:
                logger.exception("Failed to send debug heartbeat to Telegram")
                delivery_error = str(exc)

    payload = {
        "kind": kind,
        "triggered": True,
        "sent": sent,
        "delivery_error": delivery_error,
        "message": draft.text,
    }
    if runtime_result is not None:
        payload["runtime"] = heartbeat_runtime_payload(runtime_result)
    if dump and trace is not None:
        if not trace.decision:
            trace.decision = {"action": "send", "reason": "draft_generated"}
        if not trace.final.get("message"):
            trace.final = {"message": draft.text}
        payload["debug"] = trace.to_dict()
    return payload


# ---------------------------------------------------------------------------
# Memory inspection
# ---------------------------------------------------------------------------

@router.get("/memory")
def get_memory_state(db: Session = Depends(get_db)) -> dict:
    """Inspect current memory state: facts, working memory, patterns."""
    ensure_debug_enabled()
    user = repo.get_user_optional(db)
    if user is None:
        return {"facts": [], "working_memory": [], "patterns": []}

    items = repo.get_active_memory_items(
        db, user.id,
        profile_limit=50,
        working_limit=50,
        include_patterns=True,
        pattern_limit=20,
        total_limit=100,
    )
    return {
        "total_items": len(items),
        "items": [
            {
                "category": getattr(item, "category", None),
                "key": getattr(item, "key", None),
                "value": getattr(item, "value", None),
                "urgency": getattr(item, "urgency", None),
                "ttl": getattr(item, "ttl", None),
                "source": getattr(item, "source", "profile"),
            }
            for item in items
        ],
    }


# ---------------------------------------------------------------------------
# Mutation log inspection
# ---------------------------------------------------------------------------

@router.get("/mutations/recent")
def get_recent_mutations(limit: int = 10, db: Session = Depends(get_db)) -> dict:
    """Inspect recent adaptation events / mutation log."""
    ensure_debug_enabled()
    user = repo.get_user_optional(db)
    if user is None:
        return {"events": []}

    events = repo.get_recent_adaptation_events(db, user.id, limit=limit)
    return {
        "total": len(events),
        "events": [
            {
                "id": event.id,
                "created_at": str(event.created_at) if hasattr(event, "created_at") else None,
                "data": event.event_data if hasattr(event, "event_data") else str(event),
            }
            for event in events
        ],
    }


# ---------------------------------------------------------------------------
# Tool usage stats
# ---------------------------------------------------------------------------

@router.get("/tool-stats")
def get_tool_stats(db: Session = Depends(get_db)) -> dict:
    """Return tool usage statistics from recent conversation turns."""
    ensure_debug_enabled()
    user = repo.get_user_optional(db)
    if user is None:
        return {"turns": 0, "tool_usage": {}}

    turns = repo.get_recent_conversation_turns(db, user.id, limit=50)
    tool_counts: dict[str, int] = {}
    for turn in turns:
        ctx = getattr(turn, "context", None) or {}
        if isinstance(ctx, dict):
            for key in ctx:
                if key.startswith("tool_"):
                    tool_counts[key] = tool_counts.get(key, 0) + 1

    return {"turns": len(turns), "tool_usage": tool_counts}


# ---------------------------------------------------------------------------
# Reset (destructive — kept from api_debug.py)
# ---------------------------------------------------------------------------

@router.post("/reset")
def reset(db: Session = Depends(get_db)) -> dict[str, str]:
    """Reset all user data. Destructive operation."""
    ensure_debug_enabled()
    db.query(s.WatchItem).delete()
    db.query(s.ChangeNote).delete()
    db.query(s.DayPlan).delete()
    db.query(s.WeeklyPlan).delete()
    db.query(s.CoachMessage).delete()
    db.query(s.Activity).delete()
    db.query(s.UserFact).delete()
    db.query(s.UserSport).delete()
    db.query(s.UserPreference).delete()
    db.query(s.UserConstraint).delete()
    db.query(s.User).delete()
    db.commit()
    return {"status": "reset ok"}
