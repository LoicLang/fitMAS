from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fitmas.decision import RequestedPlanChange
from fitmas.domain.planning.models import PlanChangeReference, ResolvedPlanChange

_DAY_INDEX = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
    "lundi": 0,
    "mardi": 1,
    "mercredi": 2,
    "jeudi": 3,
    "vendredi": 4,
    "samedi": 5,
    "dimanche": 6,
}


class ReferenceResolver:
    def __init__(self, context: Any):
        self._context = context

    def resolve(self, requested_change: RequestedPlanChange) -> ResolvedPlanChange:
        source = self._parse_ref(requested_change.source_ref)
        target = self._parse_ref(requested_change.target_ref)
        return ResolvedPlanChange(
            requested_change=requested_change,
            source=source,
            target=target,
            warnings=self._warnings(source=source, target=target),
        )

    def _parse_ref(self, raw_ref: str | None) -> PlanChangeReference:
        raw = str(raw_ref or "").strip()
        if not raw:
            return PlanChangeReference(kind="unknown", raw=raw_ref, session_id=None, date=None)
        if raw.startswith("session_id:"):
            return self._session_ref(raw)
        if raw.startswith("date:"):
            return self._date_ref(raw)
        if raw.startswith("day:"):
            return self._day_ref(raw)
        return PlanChangeReference(kind="unknown", raw=raw, session_id=None, date=None)

    def _session_ref(self, raw: str) -> PlanChangeReference:
        try:
            session_id = int(raw.split(":", 1)[1])
        except (IndexError, TypeError, ValueError):
            return PlanChangeReference(kind="unknown", raw=raw, session_id=None, date=None)
        if not any(_session_id(session) == session_id for session in _scheduled_sessions(self._context)):
            return PlanChangeReference(kind="unknown", raw=raw, session_id=session_id, date=None)
        return PlanChangeReference(kind="session", raw=raw, session_id=session_id, date=None)

    def _date_ref(self, raw: str) -> PlanChangeReference:
        try:
            resolved_date = date.fromisoformat(raw.split(":", 1)[1][:10])
        except (IndexError, ValueError):
            return PlanChangeReference(kind="unknown", raw=raw, session_id=None, date=None)
        return PlanChangeReference(kind="date", raw=raw, session_id=None, date=resolved_date)

    def _day_ref(self, raw: str) -> PlanChangeReference:
        day_name = raw.split(":", 1)[1].strip().lower()
        if day_name not in _DAY_INDEX:
            return PlanChangeReference(kind="unknown", raw=raw, session_id=None, date=None)
        today = _today(self._context)
        if today is None:
            return PlanChangeReference(kind="unknown", raw=raw, session_id=None, date=None)
        delta = (_DAY_INDEX[day_name] - today.weekday()) % 7
        return PlanChangeReference(kind="date", raw=raw, session_id=None, date=today + timedelta(days=delta))

    def _warnings(self, *, source: PlanChangeReference, target: PlanChangeReference) -> tuple[str, ...]:
        warnings: list[str] = []
        if source.raw and source.kind == "unknown":
            warnings.append("unresolved_source_ref")
        if target.raw and target.kind == "unknown":
            warnings.append("unresolved_target_ref")
        return tuple(warnings)


def _scheduled_sessions(context: Any) -> tuple[Any, ...]:
    return tuple(getattr(getattr(context, "plan", None), "scheduled_sessions", ()) or ())


def _session_id(session: Any) -> int | None:
    raw = _value(session, "id")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _today(context: Any) -> date | None:
    raw = getattr(getattr(context, "local_time", None), "today_iso", None)
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _value(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)
