from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Literal, Mapping

PlanReferenceKind = Literal["session", "date", "day"]

_SESSION_PREFIXES = (
    "session_id:",
    "session_id_",
    "session_id=",
    "session:",
    "session_",
    "session=",
    "id:",
    "id_",
    "id=",
)
_DATE_PREFIXES = ("date:", "date_")
_DAY_PREFIXES = ("day:", "day_")
_SESSION_ID_PATTERN = re.compile(r"\b(?:session\s*id|session|id)\s*[:#=]?\s*(\d+)\b", re.IGNORECASE)


def normalize_plan_ref(value: Any, *, preserve_unknown: bool = False) -> str | None:
    """Canonicalize typed planning refs emitted by LLM/schema artifacts.

    This intentionally does not parse free user text. It only accepts explicit
    machine-shaped refs, structured objects, or raw ISO dates.
    """

    if isinstance(value, Mapping):
        return _normalize_mapping_ref(value, preserve_unknown=preserve_unknown)
    if isinstance(value, datetime):
        return f"date:{value.date().isoformat()}"
    if isinstance(value, date):
        return f"date:{value.isoformat()}"

    text = _clean(value)
    if text is None:
        return None

    session_id = plan_session_ref_id(text)
    if session_id is not None:
        return f"session_id:{session_id}"
    session_ids = plan_session_ref_ids(text)
    if len(session_ids) == 1:
        return f"session_id:{session_ids[0]}"

    date_text = _prefixed_payload(text, _DATE_PREFIXES)
    if date_text is not None:
        return f"date:{date_text[:10]}" if is_iso_date(date_text) else (text if preserve_unknown else None)

    day_text = _prefixed_payload(text, _DAY_PREFIXES)
    if day_text is not None:
        if is_iso_date(day_text):
            return f"date:{day_text[:10]}"
        return f"day:{day_text}" if day_text else (text if preserve_unknown else None)

    if is_iso_date(text):
        return f"date:{text[:10]}"
    return text if preserve_unknown else None


def plan_ref_kind(value: Any) -> PlanReferenceKind | None:
    normalized = normalize_plan_ref(value, preserve_unknown=False)
    if normalized is None:
        return None
    if normalized.startswith("session_id:"):
        return "session"
    if normalized.startswith("date:"):
        return "date"
    if normalized.startswith("day:"):
        return "day"
    return None


def plan_ref_payload(value: Any) -> str:
    normalized = normalize_plan_ref(value, preserve_unknown=True)
    raw = str(normalized if normalized is not None else value or "").strip()
    for prefix in (*_SESSION_PREFIXES, *_DATE_PREFIXES, *_DAY_PREFIXES):
        if raw.startswith(prefix):
            return raw.removeprefix(prefix).strip()
    return raw


def plan_session_ref_id(value: Any) -> int | None:
    text = _clean(value)
    if text is None:
        return None
    payload = _prefixed_payload(text, _SESSION_PREFIXES)
    if payload is None or not payload.isdigit():
        return None
    try:
        session_id = int(payload)
    except ValueError:
        return None
    return session_id if session_id > 0 else None


def plan_session_ref_ids(value: Any) -> tuple[int, ...]:
    """Extract explicit session ids from a typed planning ref artifact.

    This is only for post-LLM structured refs such as RequestedPlanChange fields.
    It must not be used to understand raw user text.
    """

    text = _clean(value)
    if text is None:
        return ()
    direct = plan_session_ref_id(text)
    if direct is not None:
        return (direct,)
    ids: list[int] = []
    for match in _SESSION_ID_PATTERN.finditer(text):
        try:
            session_id = int(match.group(1))
        except ValueError:
            continue
        if session_id > 0 and session_id not in ids:
            ids.append(session_id)
    return tuple(ids)


def is_iso_date(value: Any) -> bool:
    text = _clean(value)
    if text is None or len(text) < 10:
        return False
    if len(text) > 10 and text[10] not in {"T", " "}:
        return False
    try:
        date.fromisoformat(text[:10])
    except ValueError:
        return False
    return True


def _normalize_mapping_ref(value: Mapping[str, Any], *, preserve_unknown: bool) -> str | None:
    session_id = value.get("session_id") or value.get("session")
    if session_id is not None:
        raw_id = _clean(session_id)
        if raw_id is not None and raw_id.isdigit() and int(raw_id) > 0:
            return f"session_id:{raw_id}"

    raw_date = value.get("date")
    if raw_date is not None:
        date_text = _clean(raw_date)
        if date_text is not None and is_iso_date(date_text):
            return f"date:{date_text[:10]}"
        return str(raw_date).strip() if preserve_unknown else None

    raw_day = value.get("day")
    if raw_day is not None:
        day_text = _clean(raw_day)
        if day_text is None:
            return None
        if is_iso_date(day_text):
            return f"date:{day_text[:10]}"
        return f"day:{day_text}"

    return None


def _prefixed_payload(text: str, prefixes: tuple[str, ...]) -> str | None:
    for prefix in prefixes:
        if text.startswith(prefix):
            return text.removeprefix(prefix).strip()
    return None


def _clean(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
