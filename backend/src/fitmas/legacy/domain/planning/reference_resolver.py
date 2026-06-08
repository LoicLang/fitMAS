from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from fitmas.legacy.decision import RequestedPlanChange
from fitmas.legacy.domain.planning.models import PlanChangeReference, ResolvedPlanChange
from fitmas.legacy.domain.planning.reference_tokens import is_iso_date, normalize_plan_ref, plan_ref_payload

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
_RELATIVE_DAY_OFFSET = {
    "today": 0,
    "aujourd'hui": 0,
    "tomorrow": 1,
    "demain": 1,
    "yesterday": -1,
    "hier": -1,
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
        if raw.startswith("sport_window:"):
            return self._sport_window_ref(raw)
        if raw.startswith("availability_window:"):
            return self._availability_window_ref(raw)
        normalized = normalize_plan_ref(raw, preserve_unknown=False)
        if normalized is None:
            return PlanChangeReference(kind="unknown", raw=raw, session_id=None, date=None)
        if normalized.startswith("session_id:"):
            return self._session_ref(normalized)
        if normalized.startswith("date:"):
            return self._date_ref(normalized)
        if normalized.startswith("day:"):
            return self._day_ref(normalized)
        return PlanChangeReference(kind="unknown", raw=raw, session_id=None, date=None)

    def _session_ref(self, raw: str) -> PlanChangeReference:
        try:
            session_id = int(plan_ref_payload(raw))
        except (IndexError, TypeError, ValueError):
            return PlanChangeReference(kind="unknown", raw=raw, session_id=None, date=None)
        if not any(_session_id(session) == session_id for session in _scheduled_sessions(self._context)):
            return PlanChangeReference(kind="unknown", raw=raw, session_id=session_id, date=None)
        return PlanChangeReference(kind="session", raw=raw, session_id=session_id, date=None)

    def _date_ref(self, raw: str) -> PlanChangeReference:
        try:
            resolved_date = date.fromisoformat(plan_ref_payload(raw)[:10])
        except (IndexError, ValueError):
            return PlanChangeReference(kind="unknown", raw=raw, session_id=None, date=None)
        return PlanChangeReference(kind="date", raw=raw, session_id=None, date=resolved_date)

    def _day_ref(self, raw: str) -> PlanChangeReference:
        day_name = plan_ref_payload(raw).lower()
        if is_iso_date(day_name):
            return self._date_ref(f"date:{day_name}")
        if day_name in _RELATIVE_DAY_OFFSET:
            today = _today(self._context)
            if today is None:
                return PlanChangeReference(kind="unknown", raw=raw, session_id=None, date=None)
            return PlanChangeReference(
                kind="date",
                raw=raw,
                session_id=None,
                date=today + timedelta(days=_RELATIVE_DAY_OFFSET[day_name]),
            )
        if day_name not in _DAY_INDEX:
            return PlanChangeReference(kind="unknown", raw=raw, session_id=None, date=None)
        today = _today(self._context)
        if today is None:
            return PlanChangeReference(kind="unknown", raw=raw, session_id=None, date=None)
        delta = (_DAY_INDEX[day_name] - today.weekday()) % 7
        return PlanChangeReference(kind="date", raw=raw, session_id=None, date=today + timedelta(days=delta))

    def _sport_window_ref(self, raw: str) -> PlanChangeReference:
        _, _, payload = raw.partition(":")
        sport_type, starts_on, ends_on = _parse_sport_window_payload(payload)
        if sport_type is None or starts_on is None or ends_on is None:
            return PlanChangeReference(kind="unknown", raw=raw, session_id=None, date=None)
        return PlanChangeReference(
            kind="sport_window",
            raw=raw,
            session_id=None,
            date=None,
            sport_type=sport_type,
            starts_on=starts_on,
            ends_on=ends_on,
        )

    def _availability_window_ref(self, raw: str) -> PlanChangeReference:
        _, _, payload = raw.partition(":")
        availability, scope, starts_on, ends_on = _parse_availability_window_payload(payload)
        if availability is None or scope is None or starts_on is None or ends_on is None:
            return PlanChangeReference(kind="unknown", raw=raw, session_id=None, date=None)
        return PlanChangeReference(
            kind="availability_window",
            raw=raw,
            session_id=None,
            date=None,
            availability=availability,
            scope=scope,
            starts_on=starts_on,
            ends_on=ends_on,
        )

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
        if (
            kind in {"move", "lighten", "swap"}
            or (kind == "replace" and source.kind != "sport_window")
        ) and source.raw and source.kind != "session":
            _append_once(warnings, "unresolved_source_ref")
        if kind == "swap" and target.raw and target.kind != "session":
            _append_once(warnings, "unresolved_target_ref")
        if kind in {"move", "create"} and target.raw and target.kind != "date":
            _append_once(warnings, "unresolved_target_ref")
        if kind == "constraint_window" and source.raw and source.kind != "availability_window":
            _append_once(warnings, "unresolved_source_ref")
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


def _parse_sport_window_payload(payload: str) -> tuple[str | None, date | None, date | None]:
    parts = [part.strip() for part in str(payload or "").split(":")]
    if len(parts) != 3:
        return None, None, None
    sport_type, raw_start, raw_end = parts
    if not sport_type:
        return None, None, None
    try:
        starts_on = date.fromisoformat(raw_start[:10])
        ends_on = date.fromisoformat(raw_end[:10])
    except ValueError:
        return None, None, None
    if ends_on < starts_on:
        return None, None, None
    return sport_type, starts_on, ends_on


def _parse_availability_window_payload(payload: str) -> tuple[str | None, str | None, date | None, date | None]:
    parts = [part.strip() for part in str(payload or "").split(":")]
    if len(parts) == 3:
        raw_availability = "unavailable"
        raw_scope, raw_start, raw_end = parts
    elif len(parts) == 4:
        raw_availability, raw_scope, raw_start, raw_end = parts
    else:
        return None, None, None, None
    availability = _availability_status(raw_availability)
    scope = _availability_window_scope(raw_scope)
    if availability is None or scope is None:
        return None, None, None, None
    try:
        starts_on = date.fromisoformat(raw_start[:10])
        ends_on = date.fromisoformat(raw_end[:10])
    except ValueError:
        return None, None, None, None
    if ends_on < starts_on:
        return None, None, None, None
    return availability, scope, starts_on, ends_on


def _availability_status(value: str) -> str | None:
    status = str(value or "").strip().lower()
    if status in {"unavailable", "limited"}:
        return status
    return None


def _availability_window_scope(value: str) -> str | None:
    scope = str(value or "").strip().lower()
    if scope in {"general", "time", "location"}:
        return scope
    if scope in {"travel", "trip", "journey", "deplacement", "déplacement"}:
        return "location"
    if scope in {"day", "week", "planning", "plan"}:
        return "general"
    return None


def _value(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)
