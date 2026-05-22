from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from enum import StrEnum
from typing import Any, Sequence

from fitmas.domain.athlete.profile import AthleteProfileSnapshot
from fitmas.domain.coaching.calibration_status import CalibrationPhase, CalibrationStatus
from fitmas.domain.planning.contract import AvailabilityConfidence, AvailabilityState

DAY_LABELS = {
    "monday": "lundi",
    "tuesday": "mardi",
    "wednesday": "mercredi",
    "thursday": "jeudi",
    "friday": "vendredi",
    "saturday": "samedi",
    "sunday": "dimanche",
}

REST_SPORTS = {"rest", "off"}
KEY_SESSION_TYPES = {"tempo", "threshold", "vo2", "interval", "intervals", "race", "long_run", "long"}
HIGH_PRIORITY_KEYWORDS = ("cle", "clé", "qualite", "qualité", "fort", "important", "long")
FRESH_KEYWORDS = ("frais", "fraiche", "fraîche", "bien", "ok", "bonne", "bon")
HEAVY_KEYWORDS = ("lourd", "lourdes", "fatigue", "fatigué", "fatiguee", "entame", "entamé", "moyen")
EXHAUSTED_KEYWORDS = ("rince", "rincé", "crame", "cramé", "mort", "vide", "vidé", "explose", "explosé")
WEEK_SCOPE_KEYWORDS = ("semaine", "plusieurs jours", "jusqu", "jusque", "quelques jours", "deplacement", "déplacement", "voyage")
SESSION_SCOPE_KEYWORDS = ("ce soir", "ce matin", "aujourd", "juste ce soir", "ponctuel", "ce midi")


class CalibrationNeedType(StrEnum):
    AVAILABILITY_WINDOW = "availability_window"
    FATIGUE_STATE = "fatigue_state"
    CONSTRAINT_SCOPE = "constraint_scope"


class CalibrationNeedPriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class CalibrationNeedStatus(StrEnum):
    OPEN = "open"
    ANSWERED = "answered"
    EXPIRED = "expired"
    DISMISSED = "dismissed"


@dataclass(frozen=True, slots=True)
class CalibrationNeed:
    id: str
    need_type: CalibrationNeedType
    topic: str
    status: CalibrationNeedStatus
    why_now: str
    priority: CalibrationNeedPriority
    source: str
    channel_hint: str
    created_at: str | None = None
    expires_at: str | None = None
    last_prompted_at: str | None = None
    context: dict[str, Any] = field(default_factory=dict)
    allowed_answers: tuple[str, ...] = ()
    write_targets: tuple[str, ...] = ()
    followup_policy: str = "single_followup"

    def as_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "need_type": self.need_type.value,
            "topic": self.topic,
            "status": self.status.value,
            "why_now": self.why_now,
            "priority": self.priority.value,
            "source": self.source,
            "channel_hint": self.channel_hint,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "last_prompted_at": self.last_prompted_at,
            "context": dict(self.context),
            "allowed_answers": list(self.allowed_answers),
            "write_targets": list(self.write_targets),
            "followup_policy": self.followup_policy,
        }

    def as_memory_update(self) -> dict[str, Any]:
        return {
            "category": "calibration_need",
            "key": self.topic,
            "value": json.dumps(self.as_payload(), ensure_ascii=True),
            "source": self.source,
            "confidence": 0.95,
            "confirmed": True,
            "ttl": "short",
            "scope": "conversation",
            "affects": ["conversation", "heartbeat"],
            "expires_at": _naive_utc(_as_datetime(self.expires_at) or _default_need_expiry(self.need_type)),
        }

    def with_prompted_at(self, value: datetime) -> "CalibrationNeed":
        payload = self.as_payload()
        payload["last_prompted_at"] = _serialize_datetime(value)
        return need_from_payload(payload)


@dataclass(frozen=True, slots=True)
class CalibrationResolution:
    need_id: str
    resolved: bool
    normalized_value: dict[str, Any]
    confidence: float
    followup_needed: bool
    followup_reason: str | None = None
    raw_summary: str = ""


def find_open_calibration_need(
    memory_items: Sequence[Any],
    *,
    now: datetime | None = None,
    topic: str | None = None,
) -> CalibrationNeed | None:
    current = _utc_now(now)
    candidates: list[tuple[datetime, CalibrationNeed]] = []
    for row in memory_items:
        if str(_value(row, "category") or "") != "calibration_need":
            continue
        if topic and str(_value(row, "key") or "") != topic:
            continue
        if _is_inactive(row, now=current):
            continue
        try:
            payload = json.loads(str(_value(row, "value") or "{}"))
            need = need_from_payload(payload, row=row)
        except Exception:
            continue
        if need.status is not CalibrationNeedStatus.OPEN:
            continue
        updated_at = _as_datetime(_value(row, "updated_at")) or current
        candidates.append((updated_at, need))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def detect_calibration_need(
    *,
    profile: AthleteProfileSnapshot,
    calibration_status: CalibrationStatus,
    availability_state: AvailabilityState,
    scheduled_sessions: Sequence[Any],
    memory_items: Sequence[Any],
    today: date,
    source: str,
    channel_hint: str,
    preferred_types: Sequence[CalibrationNeedType],
    now: datetime | None = None,
) -> CalibrationNeed | None:
    current = _utc_now(now)
    existing = find_open_calibration_need(memory_items, now=current)
    if existing is not None:
        prompted_at = _as_datetime(existing.last_prompted_at)
        if prompted_at and current - prompted_at < timedelta(hours=20):
            return None
        return existing.with_prompted_at(current)

    if calibration_status.phase is CalibrationPhase.STABLE:
        return None

    for need_type in preferred_types:
        if need_type is CalibrationNeedType.AVAILABILITY_WINDOW:
            need = _build_availability_need(
                profile=profile,
                calibration_status=calibration_status,
                availability_state=availability_state,
                scheduled_sessions=scheduled_sessions,
                today=today,
                source=source,
                channel_hint=channel_hint,
                now=current,
            )
        elif need_type is CalibrationNeedType.FATIGUE_STATE:
            need = _build_fatigue_need(
                calibration_status=calibration_status,
                scheduled_sessions=scheduled_sessions,
                memory_items=memory_items,
                today=today,
                source=source,
                channel_hint=channel_hint,
                now=current,
            )
        else:
            need = None
        if need is not None:
            return need
    return None


def need_from_payload(payload: dict[str, Any], *, row: Any | None = None) -> CalibrationNeed:
    created_at = str(payload.get("created_at") or "").strip() or _serialize_datetime(_as_datetime(_value(row, "created_at")))
    expires_at = str(payload.get("expires_at") or "").strip() or _serialize_datetime(_as_datetime(_value(row, "expires_at")))
    last_prompted_at = str(payload.get("last_prompted_at") or "").strip() or _serialize_datetime(_as_datetime(_value(row, "updated_at")))
    need_type = CalibrationNeedType(str(payload.get("need_type") or CalibrationNeedType.AVAILABILITY_WINDOW.value))
    topic = str(payload.get("topic") or "").strip()
    return CalibrationNeed(
        id=str(payload.get("id") or f"{need_type.value}:{topic}"),
        need_type=need_type,
        topic=topic,
        status=CalibrationNeedStatus(str(payload.get("status") or CalibrationNeedStatus.OPEN.value)),
        why_now=str(payload.get("why_now") or "").strip(),
        priority=CalibrationNeedPriority(str(payload.get("priority") or CalibrationNeedPriority.MEDIUM.value)),
        source=str(payload.get("source") or "conversation").strip() or "conversation",
        channel_hint=str(payload.get("channel_hint") or "any").strip() or "any",
        created_at=created_at or None,
        expires_at=expires_at or None,
        last_prompted_at=last_prompted_at or None,
        context=dict(payload.get("context") or {}),
        allowed_answers=tuple(str(item) for item in (payload.get("allowed_answers") or [])),
        write_targets=tuple(str(item) for item in (payload.get("write_targets") or [])),
        followup_policy=str(payload.get("followup_policy") or "single_followup"),
    )


def render_hidden_need_brief(need: CalibrationNeed) -> str:
    lines = [
        "Doute utile a lever si et seulement si ca renforce vraiment ce message.",
        f"- type: {need.need_type.value}",
        f"- why_now: {need.why_now}",
    ]
    if need.context.get("day_label"):
        lines.append(f"- jour cible: {need.context['day_label']}")
    if need.context.get("session_title"):
        lines.append(f"- seance cible: {need.context['session_title']}")
    lines.extend(
        (
            "Si tu poses la question:",
            "- une seule question",
            "- formulation naturelle, pas formulaire",
            "- pas le mot calibration",
            "- pas de liste d'options sauf si necessaire",
        )
    )
    return "\n".join(lines)


def should_apply_calibration_resolution(resolution: CalibrationResolution | None, *, min_confidence: float = 0.85) -> bool:
    if resolution is None:
        return False
    if not resolution.resolved or resolution.followup_needed:
        return False
    return resolution.confidence >= min_confidence


def is_standalone_calibration_answer(text: str) -> bool:
    cleaned = (text or "").strip().lower()
    if not cleaned:
        return False
    normalized = cleaned.replace(",", " ").replace(".", " ").replace("?", " ")
    tokens = [token for token in normalized.split() if token]
    return len(tokens) <= 8


def looks_like_clarification_message(text: str) -> bool:
    cleaned = (text or "").strip()
    return "?" in cleaned and len(cleaned.splitlines()) <= 4


def fallback_resolve_calibration_need(user_text: str, need: CalibrationNeed) -> CalibrationResolution | None:
    text = (user_text or "").strip()
    if not text:
        return None
    normalized = text.lower()
    if need.need_type is CalibrationNeedType.AVAILABILITY_WINDOW:
        answer = _parse_availability_answer(normalized)
        if answer is None:
            return None
        windows = []
        hard_blocked = []
        if answer == "both":
            windows = ["morning", "evening"]
        elif answer == "morning":
            windows = ["morning"]
            hard_blocked = ["evening"]
        elif answer == "evening":
            windows = ["evening"]
            hard_blocked = ["morning"]
        else:
            hard_blocked = ["morning", "evening"]
        return CalibrationResolution(
            need_id=need.id,
            resolved=True,
            normalized_value={
                "day": need.context.get("day"),
                "windows": windows,
                "hard_blocked": hard_blocked,
            },
            confidence=0.93,
            followup_needed=False,
            raw_summary=text,
        )
    if need.need_type is CalibrationNeedType.FATIGUE_STATE:
        answer = _parse_fatigue_answer(normalized)
        if answer is None:
            return None
        return CalibrationResolution(
            need_id=need.id,
            resolved=True,
            normalized_value={
                "session_id": need.context.get("session_id"),
                "state": answer,
            },
            confidence=0.93,
            followup_needed=False,
            raw_summary=text,
        )
    if need.need_type is CalibrationNeedType.CONSTRAINT_SCOPE:
        scope = _parse_constraint_scope(normalized)
        if scope is None:
            return None
        return CalibrationResolution(
            need_id=need.id,
            resolved=True,
            normalized_value={"scope": scope},
            confidence=0.88,
            followup_needed=False,
            raw_summary=text,
        )
    return None


def build_resolution_memory_updates(need: CalibrationNeed, resolution: CalibrationResolution) -> list[dict[str, Any]]:
    updates: list[dict[str, Any]] = [
        {
            "category": "calibration_need",
            "key": need.topic,
            "action": "archive",
            "value": CalibrationNeedStatus.ANSWERED.value,
            "ttl": "short",
            "scope": "conversation",
        }
    ]

    if need.need_type is CalibrationNeedType.AVAILABILITY_WINDOW:
        day = str(resolution.normalized_value.get("day") or need.context.get("day") or "").strip()
        if not day:
            return updates
        label = str(need.context.get("day_label") or DAY_LABELS.get(day, day)).strip()
        windows = [str(value) for value in (resolution.normalized_value.get("windows") or [])]
        if not windows:
            value = f"{label.capitalize()}: aucun creneau fiable cette semaine."
        elif len(windows) == 2:
            value = f"{label.capitalize()}: matin ou soir possibles cette semaine."
        elif windows[0] == "morning":
            value = f"{label.capitalize()}: matin fiable cette semaine."
        else:
            value = f"{label.capitalize()}: soir fiable cette semaine."
        updates.append(
            {
                "category": "availability",
                "key": f"weekly_slot_{day}",
                "value": value,
                "source": "calibration",
                "confidence": resolution.confidence,
                "confirmed": True,
                "ttl": "short",
                "scope": "week",
                "affects": ["planning", "conversation", "heartbeat"],
            }
        )
        return updates

    if need.need_type is CalibrationNeedType.FATIGUE_STATE:
        session_id = resolution.normalized_value.get("session_id") or need.context.get("session_id") or "current"
        state = str(resolution.normalized_value.get("state") or "").strip()
        session_title = str(need.context.get("session_title") or "la seance").strip()
        if state == "fresh":
            value = f"Avant {session_title}: plutot frais."
        elif state == "heavy":
            value = f"Avant {session_title}: jambes lourdes."
        else:
            value = f"Avant {session_title}: rince."
        updates.append(
            {
                "category": "fatigue",
                "key": f"session_readiness_{session_id}",
                "value": value,
                "source": "calibration",
                "confidence": resolution.confidence,
                "confirmed": True,
                "ttl": "immediate",
                "scope": "day",
                "affects": ["planning", "conversation", "heartbeat"],
            }
        )
        return updates

    if need.need_type is CalibrationNeedType.CONSTRAINT_SCOPE:
        scope = str(resolution.normalized_value.get("scope") or "session_only").strip()
        if scope == "week":
            value = "Contrainte logistique: la semaine entiere est degradee."
        else:
            value = "Contrainte logistique: ponctuelle sur ce creneau."
        updates.append(
            {
                "category": "constraint",
                "key": "constraint_scope_active",
                "value": value,
                "source": "calibration",
                "confidence": resolution.confidence,
                "confirmed": True,
                "ttl": "short",
                "scope": "week",
                "affects": ["planning", "conversation", "heartbeat"],
            }
        )
    return updates


def fallback_ack_text(need: CalibrationNeed, resolution: CalibrationResolution) -> str:
    if need.need_type is CalibrationNeedType.AVAILABILITY_WINDOW:
        label = str(need.context.get("day_label") or "ce jour").strip()
        windows = [str(value) for value in (resolution.normalized_value.get("windows") or [])]
        if not windows:
            return f"Compris. Je traite {label} comme un jour fragile sans vrai creneau."
        if len(windows) == 2:
            return f"Compris. Je garde {label} comme jour flexible matin ou soir."
        if windows[0] == "morning":
            return f"Compris. Je prends {label} matin comme vrai point d'appui."
        return f"Compris. Je prends {label} soir comme vrai point d'appui."
    if need.need_type is CalibrationNeedType.FATIGUE_STATE:
        state = str(resolution.normalized_value.get("state") or "").strip()
        if state == "fresh":
            return "Compris. Je te lis plutot frais pour la suite."
        if state == "heavy":
            return "Compris. Jambes lourdes, donc je garde une marge."
        return "Compris. Je protege davantage la suite pour ne pas empiler."
    return "Compris. Je garde cette contrainte dans le cadre de la semaine."


def _build_availability_need(
    *,
    profile: AthleteProfileSnapshot,
    calibration_status: CalibrationStatus,
    availability_state: AvailabilityState,
    scheduled_sessions: Sequence[Any],
    today: date,
    source: str,
    channel_hint: str,
    now: datetime,
) -> CalibrationNeed | None:
    if availability_state.confidence is AvailabilityConfidence.CONFIRMED:
        return None
    for session in _upcoming_sessions(scheduled_sessions, today=today, max_days=4):
        day = str(_value(session, "day") or "").strip()
        if not day or day in profile.weekly_availability:
            continue
        if _as_date(_value(session, "scheduled_date")) == today:
            continue
        label = DAY_LABELS.get(day, day)
        topic = f"availability:{day}"
        return CalibrationNeed(
            id=f"{CalibrationNeedType.AVAILABILITY_WINDOW.value}:{topic}",
            need_type=CalibrationNeedType.AVAILABILITY_WINDOW,
            topic=topic,
            status=CalibrationNeedStatus.OPEN,
            why_now=f"Un vrai creneau pour {label} rend le plan moins fragile pendant la phase {calibration_status.phase.value}.",
            priority=CalibrationNeedPriority.MEDIUM,
            source=source,
            channel_hint=channel_hint,
            created_at=_serialize_datetime(now),
            expires_at=_serialize_datetime(_default_need_expiry(CalibrationNeedType.AVAILABILITY_WINDOW, now=now)),
            last_prompted_at=_serialize_datetime(now),
            context={
                "day": day,
                "day_label": label,
                "session_id": _as_int(_value(session, "id")),
                "session_title": str(_value(session, "session_title") or "").strip() or None,
            },
            allowed_answers=("morning", "evening", "both", "none"),
            write_targets=("working_memory.availability",),
            followup_policy="single_followup",
        )
    return None


def _build_fatigue_need(
    *,
    calibration_status: CalibrationStatus,
    scheduled_sessions: Sequence[Any],
    memory_items: Sequence[Any],
    today: date,
    source: str,
    channel_hint: str,
    now: datetime,
) -> CalibrationNeed | None:
    if any(str(_value(row, "category") or "") == "fatigue" and not _is_inactive(row, now=now) for row in memory_items):
        return None
    for session in _upcoming_sessions(scheduled_sessions, today=today, max_days=1):
        if not _is_key_session(session):
            continue
        session_title = str(_value(session, "session_title") or "la seance").strip()
        session_id = _as_int(_value(session, "id"))
        topic = f"fatigue:{session_id or str(_value(session, 'day') or 'next')}"
        return CalibrationNeed(
            id=f"{CalibrationNeedType.FATIGUE_STATE.value}:{topic}",
            need_type=CalibrationNeedType.FATIGUE_STATE,
            topic=topic,
            status=CalibrationNeedStatus.OPEN,
            why_now=f"La lecture de fatigue avant {session_title} affine l'intensite sans refaire tout le plan ({calibration_status.phase.value}).",
            priority=CalibrationNeedPriority.HIGH,
            source=source,
            channel_hint=channel_hint,
            created_at=_serialize_datetime(now),
            expires_at=_serialize_datetime(_default_need_expiry(CalibrationNeedType.FATIGUE_STATE, now=now)),
            last_prompted_at=_serialize_datetime(now),
            context={
                "day": str(_value(session, "day") or "").strip() or None,
                "day_label": DAY_LABELS.get(str(_value(session, "day") or "").strip(), None),
                "session_id": session_id,
                "session_title": session_title,
            },
            allowed_answers=("fresh", "heavy", "exhausted"),
            write_targets=("working_memory.fatigue",),
            followup_policy="single_followup",
        )
    return None


def _upcoming_sessions(
    scheduled_sessions: Sequence[Any],
    *,
    today: date,
    max_days: int,
) -> list[Any]:
    upcoming = []
    for session in scheduled_sessions:
        sport_type = str(_value(session, "sport_type") or "").lower()
        scheduled_date = _as_date(_value(session, "scheduled_date"))
        if sport_type in REST_SPORTS or scheduled_date is None:
            continue
        if scheduled_date < today or scheduled_date > today + timedelta(days=max_days):
            continue
        upcoming.append(session)
    upcoming.sort(key=lambda session: (_as_date(_value(session, "scheduled_date")) or today, int(_value(session, "id") or 0)))
    return upcoming


def _is_key_session(session: Any) -> bool:
    priority = str(_value(session, "priority") or "").lower()
    session_type = str(_value(session, "session_type") or "").lower()
    title = str(_value(session, "session_title") or "").lower()
    if session_type in KEY_SESSION_TYPES:
        return True
    return any(keyword in f"{priority} {title}" for keyword in HIGH_PRIORITY_KEYWORDS)


def _parse_availability_answer(text: str) -> str | None:
    if any(token in text for token in ("les deux", "matin et soir", "soir et matin", "les 2")):
        return "both"
    if any(token in text for token in ("aucun", "aucune", "aucun des deux", "ni l'un ni l'autre", "pas de creneau", "pas de créneau", "rien de fiable")):
        return "none"
    has_morning = "matin" in text
    has_evening = "soir" in text
    if has_morning and has_evening:
        return "both"
    if has_morning:
        return "morning"
    if has_evening:
        return "evening"
    return None


def _parse_fatigue_answer(text: str) -> str | None:
    if any(token in text for token in EXHAUSTED_KEYWORDS):
        return "exhausted"
    if any(token in text for token in HEAVY_KEYWORDS):
        return "heavy"
    if any(token in text for token in FRESH_KEYWORDS):
        return "fresh"
    return None


def _parse_constraint_scope(text: str) -> str | None:
    if any(token in text for token in WEEK_SCOPE_KEYWORDS):
        return "week"
    if any(token in text for token in SESSION_SCOPE_KEYWORDS):
        return "session_only"
    return None


def _default_need_expiry(need_type: CalibrationNeedType, *, now: datetime | None = None) -> datetime:
    current = _utc_now(now)
    if need_type is CalibrationNeedType.FATIGUE_STATE:
        return current + timedelta(hours=12)
    if need_type is CalibrationNeedType.CONSTRAINT_SCOPE:
        return current + timedelta(days=2)
    return current + timedelta(days=5)


def _as_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _value(row: Any, field: str) -> Any:
    if row is None:
        return None
    if isinstance(row, dict):
        return row.get(field)
    return getattr(row, field, None)


def _as_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return None


def _serialize_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    current = value
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat(timespec="minutes")


def _as_date(value: Any) -> date | None:
    parsed = _as_datetime(value)
    if parsed is not None:
        return parsed.date()
    if isinstance(value, date):
        return value
    return None


def _utc_now(now: datetime | None = None) -> datetime:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        return current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _naive_utc(value: datetime) -> datetime:
    current = value
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).replace(tzinfo=None)


def _is_inactive(row: Any, *, now: datetime | None = None) -> bool:
    if _value(row, "active") is False:
        return True
    expires_at = _as_datetime(_value(row, "expires_at"))
    if expires_at is None:
        return False
    return expires_at < _utc_now(now)
