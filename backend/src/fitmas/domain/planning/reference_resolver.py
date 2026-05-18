from __future__ import annotations

from datetime import date, datetime, timedelta
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
        source, target = self._promote_role_refs(requested_change.kind, source=source, target=target)
        return ResolvedPlanChange(
            requested_change=requested_change,
            source=source,
            target=target,
            warnings=self._warnings(kind=requested_change.kind, source=source, target=target),
        )

    def _parse_ref(self, raw_ref: str | None) -> PlanChangeReference:
        raw = str(raw_ref or "").strip()
        if not raw:
            return PlanChangeReference(kind="unknown", raw=raw_ref, session_id=None, date=None)
        if raw.startswith(("session_id:", "session_", "session:", "id:")):
            return self._session_ref(raw)
        if raw.startswith(("date:", "date_")):
            return self._date_ref(raw)
        if _is_iso_date(raw):
            return self._date_ref(f"date:{raw}")
        if raw.startswith("day:"):
            return self._day_ref(raw)
        return PlanChangeReference(kind="unknown", raw=raw, session_id=None, date=None)

    def _session_ref(self, raw: str) -> PlanChangeReference:
        try:
            session_id = int(_ref_payload(raw))
        except (IndexError, TypeError, ValueError):
            return PlanChangeReference(kind="unknown", raw=raw, session_id=None, date=None)
        if not any(_session_id(session) == session_id for session in _scheduled_sessions(self._context)):
            return PlanChangeReference(kind="unknown", raw=raw, session_id=session_id, date=None)
        return PlanChangeReference(kind="session", raw=raw, session_id=session_id, date=None)

    def _date_ref(self, raw: str) -> PlanChangeReference:
        try:
            resolved_date = date.fromisoformat(_ref_payload(raw)[:10])
        except (IndexError, ValueError):
            return PlanChangeReference(kind="unknown", raw=raw, session_id=None, date=None)
        return PlanChangeReference(kind="date", raw=raw, session_id=None, date=resolved_date)

    def _day_ref(self, raw: str) -> PlanChangeReference:
        day_name = _ref_payload(raw).lower()
        if _is_iso_date(day_name):
            return self._date_ref(f"date:{day_name}")
        if day_name not in _DAY_INDEX:
            return PlanChangeReference(kind="unknown", raw=raw, session_id=None, date=None)
        today = _today(self._context)
        if today is None:
            return PlanChangeReference(kind="unknown", raw=raw, session_id=None, date=None)
        delta = (_DAY_INDEX[day_name] - today.weekday()) % 7
        return PlanChangeReference(kind="date", raw=raw, session_id=None, date=today + timedelta(days=delta))

    def _promote_role_refs(
        self,
        kind: str,
        *,
        source: PlanChangeReference,
        target: PlanChangeReference,
    ) -> tuple[PlanChangeReference, PlanChangeReference]:
        if kind in {"move", "lighten", "replace", "swap"}:
            source = self._date_ref_to_session_ref(source)
        if kind == "swap":
            target = self._date_ref_to_session_ref(target)
        return source, target

    def _date_ref_to_session_ref(self, ref: PlanChangeReference) -> PlanChangeReference:
        if ref.kind != "date" or ref.date is None:
            return ref
        matches = tuple(
            session for session in _scheduled_sessions(self._context) if _session_date(session) == ref.date
        )
        if len(matches) != 1:
            return ref
        session_id = _session_id(matches[0])
        if session_id is None:
            return ref
        return PlanChangeReference(kind="session", raw=ref.raw, session_id=session_id, date=ref.date)

    def _warnings(
        self,
        *,
        kind: str,
        source: PlanChangeReference,
        target: PlanChangeReference,
    ) -> tuple[str, ...]:
        warnings: list[str] = []
        if source.raw and source.kind == "unknown":
            _append_once(warnings, "unresolved_source_ref")
        if target.raw and target.kind == "unknown":
            _append_once(warnings, "unresolved_target_ref")
        if kind in {"move", "lighten", "replace", "swap"} and source.raw and source.kind != "session":
            _append_once(warnings, "unresolved_source_ref")
        if kind == "swap" and target.raw and target.kind != "session":
            _append_once(warnings, "unresolved_target_ref")
        if kind in {"move", "create"} and target.raw and target.kind != "date":
            _append_once(warnings, "unresolved_target_ref")
        return tuple(warnings)


def _scheduled_sessions(context: Any) -> tuple[Any, ...]:
    return tuple(getattr(getattr(context, "plan", None), "scheduled_sessions", ()) or ())


def _session_id(session: Any) -> int | None:
    raw = _value(session, "id")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _session_date(session: Any) -> date | None:
    raw = _value(session, "scheduled_date")
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _append_once(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def _today(context: Any) -> date | None:
    raw = getattr(getattr(context, "local_time", None), "today_iso", None)
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _is_iso_date(raw: str) -> bool:
    if len(raw) < 10:
        return False
    if len(raw) > 10 and raw[10] not in {"T", " "}:
        return False
    try:
        date.fromisoformat(raw[:10])
    except ValueError:
        return False
    return True


def _ref_payload(raw: str) -> str:
    if ":" in raw:
        return raw.split(":", 1)[1].strip()
    if "_" in raw:
        return raw.split("_", 1)[1].strip()
    return raw


def _value(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)
