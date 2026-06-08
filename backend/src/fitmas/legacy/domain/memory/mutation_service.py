from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Iterable

from sqlalchemy.orm import Session

from fitmas.legacy.core import orm as s
from fitmas.legacy.decision.command_actions import (
    AvailabilityConstraintAction,
    HealthSignalAction,
    MemoryAction,
    PreferenceSignalAction,
)
from fitmas.legacy.domain.memory import repository as memory_repo
from fitmas.legacy.domain.memory.routing import split_memory_payloads


@dataclass(frozen=True, slots=True)
class MemoryActionApplicationResult:
    applied_count: int
    blocked_count: int
    saved_keys: tuple[str, ...]
    event_ids: tuple[int, ...] = ()


def apply_memory_actions_for_user(
    db: Session,
    *,
    user: s.User,
    actions: Iterable[MemoryAction],
    source: str = "conversation",
    conversation_turn_id: int | None = None,
    now: datetime | None = None,
) -> MemoryActionApplicationResult:
    """Apply LLM-produced memory actions through bounded storage.

    The input is already a typed command artifact. This service never
    inspects raw user text.
    """
    payloads: list[dict] = []
    availability_resolutions: list[AvailabilityConstraintAction] = []
    event_ids: list[int] = []
    blocked = 0
    for action in actions:
        payload = _payload_from_action(action, source=source, now=now)
        if payload is None:
            blocked += 1
            event_ids.append(
                _add_event(
                    db,
                    user=user,
                    action_type=str(getattr(action, "type", "")),
                    target_type="memory",
                    target_key="",
                    status="blocked",
                    reason="invalid_action",
                    payload=_dump_action(action),
                    source=source,
                    conversation_turn_id=conversation_turn_id,
                )
            )
            continue
        payloads.append(payload)
        if isinstance(action, AvailabilityConstraintAction) and action.availability == "available":
            availability_resolutions.append(action)

    profile_payloads, working_payloads = split_memory_payloads(payloads, now=now)
    saved_profile = memory_repo.upsert_facts(db, user.id, profile_payloads)
    saved_working = memory_repo.upsert_working_memory(db, user.id, working_payloads)
    saved_keys = tuple(
        f"{getattr(row, 'category', '')}:{getattr(row, 'key', '')}"
        for row in [*saved_profile, *saved_working]
    )

    for payload in payloads:
        event_ids.append(
            _add_event(
                db,
                user=user,
                action_type=str(payload.get("action_type") or "memory_action"),
                target_type=str(payload.get("category") or "memory"),
                target_key=str(payload.get("key") or ""),
                status="applied",
                reason="",
                payload=payload,
                source=source,
                conversation_turn_id=conversation_turn_id,
            )
        )

    for action in availability_resolutions:
        event_ids.extend(
            _resolve_overlapping_unavailability(
                db,
                user=user,
                action=action,
                source=source,
                conversation_turn_id=conversation_turn_id,
                now=now,
            )
        )

    return MemoryActionApplicationResult(
        applied_count=len(saved_profile) + len(saved_working),
        blocked_count=blocked,
        saved_keys=saved_keys,
        event_ids=tuple(event_ids),
    )


def _payload_from_action(action: MemoryAction, *, source: str, now: datetime | None) -> dict | None:
    if isinstance(action, HealthSignalAction):
        key_base = action.body_area or action.health_signal
        status = action.status if action.status != "unknown" else "open"
        severity = action.severity if action.severity != "unknown" else "medium"
        signal_kind = action.signal_kind if action.signal_kind != "other" else "health"
        return {
            "category": "health",
            "key": f"health_{_slugify(key_base)}",
            "value": action.health_signal,
            "source": source,
            "confidence": action.confidence,
            "confirmed": False,
            "status": status,
            "severity": severity,
            "signal_kind": signal_kind,
            "resolved_at": now if status == "resolved" else None,
            "resolution_reason": action.evidence if status == "resolved" else "",
            "action": "upsert",
            "action_type": action.type,
        }
    if isinstance(action, AvailabilityConstraintAction):
        starts_on = _parse_date(action.starts_on)
        ends_on = _parse_date(action.ends_on)
        sport_type = _normalize_sport(getattr(action, "sport_type", None))
        key = _availability_key(action, starts_on=starts_on, ends_on=ends_on, sport_type=sport_type)
        payload = {
            "category": "availability",
            "key": key,
            "value": f"{action.availability}: {action.window_text}",
            "source": source,
            "confidence": action.confidence,
            "confirmed": False,
            "ttl": "short" if starts_on or ends_on else "medium",
            "status": "open",
            "severity": "high" if action.availability == "unavailable" else "medium",
            "signal_kind": f"availability_{action.availability}",
            "action": "upsert",
            "action_type": action.type,
        }
        if sport_type:
            payload["sport_type"] = sport_type
        scope = str(getattr(action, "scope", "") or "").strip()
        if scope:
            payload["scope"] = scope
        if starts_on is not None:
            payload["valid_from"] = datetime.combine(starts_on, datetime.min.time())
        if ends_on is not None:
            payload["expires_at"] = datetime.combine(ends_on + timedelta(days=1), datetime.min.time())
            payload["valid_until"] = payload["expires_at"]
        return payload
    if isinstance(action, PreferenceSignalAction):
        return {
            "category": "preference",
            "key": f"preference_{action.polarity}_{_slugify(_strip_preference_prefix(action.preference))}",
            "value": action.preference,
            "source": source,
            "confidence": action.confidence,
            "confirmed": False,
            "ttl": "long",
            "action": "upsert",
            "action_type": action.type,
        }
    return None


def _resolve_overlapping_unavailability(
    db: Session,
    *,
    user: s.User,
    action: AvailabilityConstraintAction,
    source: str,
    conversation_turn_id: int | None,
    now: datetime | None,
) -> tuple[int, ...]:
    starts_on = _parse_date(action.starts_on)
    ends_on = _parse_date(action.ends_on) or starts_on
    sport_type = _normalize_sport(getattr(action, "sport_type", None))
    if starts_on is None or ends_on is None:
        return ()
    resolved_at = now or datetime.now(UTC).replace(tzinfo=None)
    resolved_rows: list[s.UserFact | s.WorkingMemoryEntry] = []
    for row in [
        *_active_unavailability_rows(db, s.UserFact, user_id=user.id),
        *_active_unavailability_rows(db, s.WorkingMemoryEntry, user_id=user.id),
    ]:
        if not _availability_row_matches_sport(row, sport_type=sport_type):
            continue
        if not _availability_row_overlaps(row, starts_on=starts_on, ends_on=ends_on):
            continue
        row.active = False
        row.status = "resolved"
        row.resolved_at = resolved_at
        row.resolution_reason = "availability_available_overlap"
        resolved_rows.append(row)

    if not resolved_rows:
        return ()
    db.commit()
    event_ids: list[int] = []
    for row in resolved_rows:
        event_ids.append(
            _add_event(
                db,
                user=user,
                action_type="resolve_availability_unavailable",
                target_type="availability",
                target_key=str(getattr(row, "key", "")),
                status="applied",
                reason="availability_available_overlap",
                payload={
                    "category": "availability",
                    "key": getattr(row, "key", ""),
                    "resolved_by": _availability_key(action, starts_on=starts_on, ends_on=ends_on, sport_type=sport_type),
                },
                source=source,
                conversation_turn_id=conversation_turn_id,
            )
        )
    return tuple(event_ids)


def _active_unavailability_rows(db: Session, model, *, user_id: int):
    return (
        db.query(model)
        .filter(
            model.user_id == user_id,
            model.category == "availability",
            model.active.is_(True),
            model.signal_kind == "availability_unavailable",
        )
        .all()
    )


def _availability_row_matches_sport(row: s.UserFact | s.WorkingMemoryEntry, *, sport_type: str | None) -> bool:
    key = str(getattr(row, "key", "") or "")
    if key.startswith("unavailable_"):
        parts = key.split("_")
        row_sport = _normalize_sport(parts[1] if len(parts) >= 4 else None)
        return row_sport == sport_type
    return sport_type is None


def _availability_row_overlaps(row: s.UserFact | s.WorkingMemoryEntry, *, starts_on, ends_on) -> bool:
    row_start = _as_date(getattr(row, "valid_from", None) or getattr(row, "observed_at", None))
    row_end = _availability_end_date(getattr(row, "valid_until", None) or getattr(row, "expires_at", None))
    if row_start is None or row_end is None:
        return True
    return row_start <= ends_on and starts_on <= row_end


def _availability_end_date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        # Memory valid_until/expires_at is often stored as the exclusive
        # next-day midnight boundary. Inclusive end-of-day values should keep
        # their calendar day.
        end = value.date()
        if value.time() == time.min:
            return end - timedelta(days=1)
        return end
    return _as_date(value)


def _as_date(value):
    if value is None:
        return None
    if hasattr(value, "date"):
        return value.date()
    return _parse_date(str(value))


def _add_event(
    db: Session,
    *,
    user: s.User,
    action_type: str,
    target_type: str,
    target_key: str,
    status: str,
    reason: str,
    payload: dict,
    source: str,
    conversation_turn_id: int | None,
) -> int:
    record = s.MemoryMutationEventRecord(
        user_id=user.id,
        source=source,
        action_type=action_type,
        target_type=target_type,
        target_key=target_key,
        status=status,
        reason=reason,
        payload_json=json.dumps(payload, ensure_ascii=True, sort_keys=True, default=str),
        conversation_turn_id=conversation_turn_id,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return int(record.id)


def _dump_action(action: object) -> dict:
    if hasattr(action, "model_dump"):
        return action.model_dump(mode="json")
    return {}


def _parse_date(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None


def _availability_key(
    action: AvailabilityConstraintAction,
    *,
    starts_on,
    ends_on,
    sport_type: str | None,
) -> str:
    if action.availability == "unavailable" and sport_type and starts_on is not None and ends_on is not None:
        return f"unavailable_{sport_type}_{starts_on.isoformat()}_{ends_on.isoformat()}"
    if starts_on is not None and ends_on is not None:
        return f"availability_{starts_on.isoformat()}_{ends_on.isoformat()}"
    return f"availability_{_slugify(action.window_text)}"


def _normalize_sport(value: str | None) -> str | None:
    sport = _slugify(value or "")
    if sport in {"", "unknown", "general", "all", "rest", "off"}:
        return None
    aliases = {
        "swim": "swimming",
        "natation": "swimming",
        "piscine": "swimming",
        "run": "running",
        "course": "running",
        "course_a_pied": "running",
        "velo": "cycling",
        "bike": "cycling",
        "biking": "cycling",
        "renfo": "strength",
        "muscu": "strength",
        "musculation": "strength",
        "escalade": "climbing",
    }
    if sport in aliases:
        return aliases[sport]
    return sport


def _strip_preference_prefix(value: str) -> str:
    lowered = value.strip().lower()
    for prefix in ("prefere les ", "prefere le ", "prefere la ", "prefere ", "preference "):
        if lowered.startswith(prefix):
            return lowered[len(prefix):]
    return lowered


def _slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").lower()
    chars = [char if char.isalnum() else "_" for char in ascii_value]
    slug = "_".join(part for part in "".join(chars).split("_") if part)
    return slug[:96] or "unknown"
