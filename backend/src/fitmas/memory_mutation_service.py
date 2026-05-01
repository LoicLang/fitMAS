from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

from sqlalchemy.orm import Session

from fitmas import repository as repo, schema as s
from fitmas.llm import AvailabilityConstraintAction, HealthSignalAction, MemoryAction, PreferenceSignalAction
from fitmas.memory_routing import split_memory_payloads


@dataclass(frozen=True, slots=True)
class MemoryActionApplicationResult:
    applied_count: int
    blocked_count: int
    saved_keys: tuple[str, ...]


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

    The input is already a typed CoachDecision artifact. This service never
    inspects raw user text.
    """
    payloads: list[dict] = []
    blocked = 0
    for action in actions:
        payload = _payload_from_action(action, source=source, now=now)
        if payload is None:
            blocked += 1
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
            continue
        payloads.append(payload)

    profile_payloads, working_payloads = split_memory_payloads(payloads, now=now)
    saved_profile = repo.upsert_facts(db, user.id, profile_payloads)
    saved_working = repo.upsert_working_memory(db, user.id, working_payloads)
    saved_keys = tuple(
        f"{getattr(row, 'category', '')}:{getattr(row, 'key', '')}"
        for row in [*saved_profile, *saved_working]
    )

    for payload in payloads:
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

    return MemoryActionApplicationResult(
        applied_count=len(saved_profile) + len(saved_working),
        blocked_count=blocked,
        saved_keys=saved_keys,
    )


def _payload_from_action(action: MemoryAction, *, source: str, now: datetime | None) -> dict | None:
    if isinstance(action, HealthSignalAction):
        key_base = action.body_area or action.health_signal
        return {
            "category": "health",
            "key": f"health_{_slugify(key_base)}",
            "value": action.health_signal,
            "source": source,
            "confidence": action.confidence,
            "confirmed": False,
            "action": "upsert",
            "action_type": action.type,
        }
    if isinstance(action, AvailabilityConstraintAction):
        starts_on = _parse_date(action.starts_on)
        ends_on = _parse_date(action.ends_on)
        key = (
            f"availability_{action.starts_on}_{action.ends_on}"
            if action.starts_on and action.ends_on
            else f"availability_{_slugify(action.window_text)}"
        )
        payload = {
            "category": "availability",
            "key": key,
            "value": f"{action.availability}: {action.window_text}",
            "source": source,
            "confidence": action.confidence,
            "confirmed": False,
            "ttl": "short" if starts_on or ends_on else "medium",
            "action": "upsert",
            "action_type": action.type,
        }
        if ends_on is not None:
            payload["expires_at"] = datetime.combine(ends_on + timedelta(days=1), datetime.min.time())
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
) -> None:
    db.add(
        s.MemoryMutationEventRecord(
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
    )
    db.commit()


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
