from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterable

from sqlalchemy.orm import Session

from fitmas import repository as repo, schema as s
from fitmas.decision.command_actions import ExecutionUpdateAction
from fitmas.time_context import get_local_now


@dataclass(frozen=True, slots=True)
class ExecutionActionApplicationResult:
    applied_count: int
    blocked_count: int
    updated_session_ids: tuple[int, ...]
    event_ids: tuple[int, ...] = ()


def apply_execution_actions_for_user(
    db: Session,
    *,
    user: s.User,
    actions: Iterable[ExecutionUpdateAction],
    source: str = "conversation",
    conversation_turn_id: int | None = None,
    now: datetime | None = None,
) -> ExecutionActionApplicationResult:
    """Apply LLM-produced execution updates after DB target resolution.

    The resolver works on typed LLM artifacts (`target_ref`, `sport_type`,
    status), never on raw user text.
    """
    applied = 0
    blocked = 0
    updated_ids: list[int] = []
    event_ids: list[int] = []
    for action in actions:
        status = _session_status_from_action(action)
        if status is None:
            blocked += 1
            event_ids.append(
                _add_event(db, user=user, action=action, status="blocked", reason="unsupported_status", source=source, conversation_turn_id=conversation_turn_id)
            )
            continue

        resolution = _resolve_target_session(db, user=user, action=action, now=now)
        if resolution.reason != "ok" or resolution.session is None:
            blocked += 1
            event_ids.append(
                _add_event(db, user=user, action=action, status="blocked", reason=resolution.reason, source=source, conversation_turn_id=conversation_turn_id)
            )
            continue

        updated = repo.set_scheduled_session_status(db, resolution.session.id, status)
        if updated is None:
            blocked += 1
            event_ids.append(
                _add_event(db, user=user, action=action, status="blocked", reason="target_missing", source=source, conversation_turn_id=conversation_turn_id)
            )
            continue

        applied += 1
        updated_ids.append(updated.id)
        event_ids.append(
            _add_event(db, user=user, action=action, status="applied", reason="", source=source, conversation_turn_id=conversation_turn_id, target_session_id=updated.id)
        )

    return ExecutionActionApplicationResult(
        applied_count=applied,
        blocked_count=blocked,
        updated_session_ids=tuple(updated_ids),
        event_ids=tuple(event_ids),
    )


@dataclass(frozen=True, slots=True)
class _SessionResolution:
    session: s.ScheduledSession | None
    reason: str


def _resolve_target_session(
    db: Session,
    *,
    user: s.User,
    action: ExecutionUpdateAction,
    now: datetime | None,
) -> _SessionResolution:
    if action.target_session_id is not None:
        session = repo.get_scheduled_session(db, user.id, action.target_session_id)
        return _SessionResolution(session, "ok" if session is not None else "target_missing")

    target_date = _target_date_from_ref(action.target_ref, user=user, now=now)
    if target_date is None:
        return _SessionResolution(None, "unresolved_target_date")

    candidates = repo.get_scheduled_sessions_for_date(db, user.id, target_date=target_date)
    if action.sport_type:
        sport = _normalize_token(action.sport_type)
        candidates = [session for session in candidates if _normalize_token(session.sport_type) == sport]
    if len(candidates) == 1:
        return _SessionResolution(candidates[0], "ok")
    if not candidates:
        return _SessionResolution(None, "target_missing")
    return _SessionResolution(None, "ambiguous_target")


def _session_status_from_action(action: ExecutionUpdateAction) -> str | None:
    if action.status == "completed" or action.completed is True:
        return "done"
    if action.status == "not_completed" or action.completed is False:
        return "skipped"
    return None


def _target_date_from_ref(target_ref: str, *, user: s.User, now: datetime | None) -> date | None:
    local_now = get_local_now(user.timezone, now=now)
    normalized = _normalize_token(target_ref)
    iso_candidate = normalized.removeprefix("date:").strip()
    try:
        return date.fromisoformat(iso_candidate)
    except ValueError:
        pass
    if "hier" in normalized or "yesterday" in normalized:
        return local_now.date() - timedelta(days=1)
    if "aujourd" in normalized or "today" in normalized:
        return local_now.date()
    if "demain" in normalized or "tomorrow" in normalized:
        return local_now.date() + timedelta(days=1)
    return None


def _add_event(
    db: Session,
    *,
    user: s.User,
    action: ExecutionUpdateAction,
    status: str,
    reason: str,
    source: str,
    conversation_turn_id: int | None,
    target_session_id: int | None = None,
) -> int:
    payload = action.model_dump(mode="json")
    if target_session_id is not None:
        payload["target_session_id"] = target_session_id
    record = s.MemoryMutationEventRecord(
        user_id=user.id,
        source=source,
        action_type=action.type,
        target_type="scheduled_session",
        target_key=str(target_session_id or ""),
        status=status,
        reason=reason,
        payload_json=json.dumps(payload, ensure_ascii=True, sort_keys=True),
        conversation_turn_id=conversation_turn_id,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return int(record.id)


def _normalize_token(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    return normalized.encode("ascii", "ignore").decode("ascii").lower()
