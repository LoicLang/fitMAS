from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Sequence

_SHOULDER_MARKERS = ("epaule", "shoulder", "coiffe")
_KNEE_MARKERS = ("genou", "knee", "rotule")
_LOW_BACK_MARKERS = ("dos", "lomb", "back")
_LEG_FATIGUE_MARKERS = ("jambes", "mollet", "quad", "ischio", "leg fatigue", "jambe lourde")
_ACHILLES_MARKERS = ("achille", "achilles")
_FATIGUE_MARKERS = ("fatigue", "courbature", "crame", "cramé", "epuise", "épuisé", "reprise", "relance", "restart")
_RUN_MARKERS = ("course", "run", "trail", "footing")
_SWIM_MARKERS = ("natation", "swim", "piscine")
_KEY_PRIORITIES = {"high", "key", "important"}


@dataclass(frozen=True, slots=True)
class StrengthSignals:
    recent_completion_band: str
    recent_load_band: str
    fatigue_flag: bool
    health_flags: tuple[str, ...]
    available_time_band: str
    protected_sport: str | None


def derive_strength_signals(
    *,
    session: Any,
    watch_items: Sequence[dict[str, Any]] | Sequence[Any] = (),
    recent_reality: Any | None = None,
    active_facts: Sequence[dict[str, Any]] | Sequence[Any] = (),
    nearby_sessions: Sequence[dict[str, Any]] | Sequence[Any] = (),
) -> StrengthSignals:
    combined = _combined_text(session=session, watch_items=watch_items, active_facts=active_facts)
    return StrengthSignals(
        recent_completion_band=_recent_completion_band(recent_reality),
        recent_load_band=_recent_load_band(recent_reality),
        fatigue_flag=_fatigue_flag(combined=combined, active_facts=active_facts),
        health_flags=_health_flags(combined=combined),
        available_time_band=_available_time_band(duration_min=_value(session, "duration_min")),
        protected_sport=_protected_sport(
            session=session,
            combined=combined,
            nearby_sessions=nearby_sessions,
        ),
    )


def _combined_text(
    *,
    session: Any,
    watch_items: Sequence[dict[str, Any]] | Sequence[Any],
    active_facts: Sequence[dict[str, Any]] | Sequence[Any],
) -> str:
    parts = [
        _clean_text(_value(session, "session_goal")),
        _clean_text(_value(session, "session_note")),
        _clean_text(_value(session, "session_description")),
        *[_clean_text(_value(item, "title")) for item in watch_items],
        *[_clean_text(_value(item, "detail")) for item in watch_items],
        *[_clean_text(_value(fact, "key")) for fact in active_facts],
        *[_clean_text(_value(fact, "value")) for fact in active_facts],
    ]
    return " ".join(part for part in parts if part).lower()


def _recent_completion_band(recent_reality: Any | None) -> str:
    planned_sessions = _int(_value(recent_reality, "planned_sessions_7d")) or 0
    compliance = _float(_value(recent_reality, "compliance_confirmed")) or 1.0
    missed_streak_days = _int(_value(recent_reality, "missed_streak_days")) or 0
    if planned_sessions >= 3 and compliance < 0.6:
        return "low"
    if planned_sessions >= 2 and missed_streak_days >= 2:
        return "low"
    return "ok"


def _recent_load_band(recent_reality: Any | None) -> str:
    planned_tss = _float(_value(recent_reality, "planned_tss_7d")) or 0.0
    planned_sessions = _int(_value(recent_reality, "planned_sessions_7d")) or 0
    load_ratio = _float(_value(recent_reality, "load_ratio")) or 1.0
    if planned_tss >= 80 and load_ratio < 0.7:
        return "low"
    if planned_sessions >= 3 and load_ratio < 0.65:
        return "low"
    return "ok"


def _fatigue_flag(*, combined: str, active_facts: Sequence[dict[str, Any]] | Sequence[Any]) -> bool:
    if any(marker in combined for marker in _FATIGUE_MARKERS):
        return True
    return any(str(_value(fact, "category") or "").lower() == "fatigue" for fact in active_facts)


def _health_flags(*, combined: str) -> tuple[str, ...]:
    flags: list[str] = []
    if any(marker in combined for marker in _SHOULDER_MARKERS):
        flags.append("shoulder_pain")
    if any(marker in combined for marker in _KNEE_MARKERS):
        flags.append("knee_pain")
    if any(marker in combined for marker in _LOW_BACK_MARKERS):
        flags.append("low_back_risk")
    if any(marker in combined for marker in _LEG_FATIGUE_MARKERS):
        flags.append("leg_fatigue")
    if any(marker in combined for marker in _ACHILLES_MARKERS):
        flags.append("achilles_pain")
    return tuple(flags)


def _available_time_band(*, duration_min: Any) -> str:
    duration = max(20, _int(duration_min) or 30)
    return "short" if duration <= 25 else "normal"


def _protected_sport(
    *,
    session: Any,
    combined: str,
    nearby_sessions: Sequence[dict[str, Any]] | Sequence[Any],
) -> str | None:
    if any(marker in combined for marker in _SWIM_MARKERS):
        return "swimming"
    if any(marker in combined for marker in _RUN_MARKERS):
        return "running"

    session_id = _int(_value(session, "id"))
    session_date = _as_date(_value(session, "scheduled_date"))
    if session_date is None:
        return None

    candidates: list[tuple[int, int, int, str]] = []
    for nearby in nearby_sessions:
        if session_id is not None and _int(_value(nearby, "id")) == session_id:
            continue
        sport_type = str(_value(nearby, "sport_type") or "").lower()
        if sport_type not in {"running", "swimming"}:
            continue
        nearby_date = _as_date(_value(nearby, "scheduled_date"))
        if nearby_date is None:
            continue
        delta_days = (nearby_date - session_date).days
        if abs(delta_days) > 1:
            continue
        priority_score = 2 if str(_value(nearby, "priority") or "").strip().lower() in _KEY_PRIORITIES else 1
        load_score = _int(_value(nearby, "load_score")) or 0
        candidates.append((abs(delta_days), 0 if delta_days >= 0 else 1, -(priority_score * 10 + load_score), sport_type))

    if not candidates:
        return None
    candidates.sort()
    return candidates[0][3]


def _value(obj: Any, key: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            return None
    return None
