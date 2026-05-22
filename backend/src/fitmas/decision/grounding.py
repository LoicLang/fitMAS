"""Shared grounding contracts for final coach speech.

This module never interprets raw user text. It only resolves typed LLM
artifacts and DB/session objects into compact facts that final composers and
verifiers can compare against.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Mapping, Sequence


DAY_LABELS_FR = {
    0: "lundi",
    1: "mardi",
    2: "mercredi",
    3: "jeudi",
    4: "vendredi",
    5: "samedi",
    6: "dimanche",
}
WEEKDAY_VALUES = {
    "monday": 0,
    "lundi": 0,
    "tuesday": 1,
    "mardi": 1,
    "wednesday": 2,
    "mercredi": 2,
    "thursday": 3,
    "jeudi": 3,
    "friday": 4,
    "vendredi": 4,
    "saturday": 5,
    "samedi": 5,
    "sunday": 6,
    "dimanche": 6,
}
RELATIVE_DAY_DELTAS = {
    "yesterday": -1,
    "hier": -1,
    "today": 0,
    "aujourd'hui": 0,
    "aujourd hui": 0,
    "tomorrow": 1,
    "demain": 1,
}
REST_SPORTS = {"rest", "off"}
REST_SESSION_TYPES = {"rest", "recovery", "mobility", "off"}
CLOSED_STATUSES = {"done", "skipped", "cancelled", "canceled"}


@dataclass(frozen=True, slots=True)
class ResolvedTemporalReference:
    role: str
    kind: str
    value: str
    resolved_date: date
    day_label: str


@dataclass(frozen=True, slots=True)
class PlanWindowFact:
    session_id: int | None
    scheduled_date: date
    day_label: str
    sport: str
    title: str = ""
    duration_min: int | None = None
    intensity: str = ""
    completion_status: str = "planned"
    slot_kind: str = "training"


@dataclass(frozen=True, slots=True)
class ReplyGroundingPacket:
    local_date: date | None = None
    timezone_name: str | None = None
    temporal_references: Mapping[str, tuple[ResolvedTemporalReference, ...]] = field(default_factory=dict)
    plan_window: tuple[PlanWindowFact, ...] = ()
    extra_facts: tuple[str, ...] = ()


def resolve_temporal_intents(
    temporal_references: Sequence[Mapping[str, Any]] | None,
    *,
    local_date: date,
) -> dict[str, tuple[ResolvedTemporalReference, ...]]:
    """Resolve typed temporal references emitted by the LLM planner."""
    grouped: dict[str, list[ResolvedTemporalReference]] = {}
    for raw in temporal_references or ():
        resolved = _resolve_temporal_reference(raw, local_date=local_date)
        if resolved is None:
            continue
        grouped.setdefault(resolved.role, []).append(resolved)
    return {role: tuple(items) for role, items in grouped.items()}


def plan_window_facts_from_sessions(
    sessions: Sequence[Any] | None,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> tuple[PlanWindowFact, ...]:
    facts: list[PlanWindowFact] = []
    for session in sessions or ():
        scheduled = _as_date(_value(session, "scheduled_date"))
        if scheduled is None:
            continue
        if start_date is not None and scheduled < start_date:
            continue
        if end_date is not None and scheduled > end_date:
            continue
        sport = str(_value(session, "sport_type") or "").strip().lower()
        session_type = str(_value(session, "session_type") or "").strip().lower()
        status = str(_value(session, "completion_status") or "planned").strip().lower()
        facts.append(
            PlanWindowFact(
                session_id=_int(_value(session, "id")),
                scheduled_date=scheduled,
                day_label=DAY_LABELS_FR.get(scheduled.weekday(), scheduled.isoformat()),
                sport=sport,
                title=str(_value(session, "session_title") or "").strip(),
                duration_min=_int(_value(session, "duration_min")),
                intensity=str(_value(session, "intensity") or "").strip().lower(),
                completion_status=status,
                slot_kind=_slot_kind(
                    sport=sport,
                    session_type=session_type,
                    completion_status=status,
                ),
            )
        )
    return tuple(sorted(facts, key=lambda item: (item.scheduled_date, item.session_id or 0)))


def render_grounding_packet_for_prompt(packet: ReplyGroundingPacket | None) -> tuple[str, ...]:
    if packet is None:
        return ()
    lines: list[str] = []
    if packet.local_date is not None:
        day_label = DAY_LABELS_FR.get(packet.local_date.weekday(), packet.local_date.isoformat())
        suffix = f" timezone={packet.timezone_name}" if packet.timezone_name else ""
        lines.append(f"LocalDate: {packet.local_date.isoformat()} ({day_label}){suffix}")
    if packet.temporal_references:
        lines.append("TemporalRefs:")
        for role in sorted(packet.temporal_references):
            for ref in packet.temporal_references[role]:
                lines.append(
                    f"- {role}: {ref.kind}={ref.value} -> "
                    f"{ref.resolved_date.isoformat()} ({ref.day_label})"
                )
    if packet.plan_window:
        lines.append("PlanWindow:")
        for fact in packet.plan_window:
            lines.append("- " + _format_plan_window_fact(fact))
    if packet.extra_facts:
        lines.append("ExtraFacts:")
        lines.extend(f"- {fact}" for fact in packet.extra_facts if str(fact).strip())
    return tuple(lines)


def _resolve_temporal_reference(
    raw: Mapping[str, Any],
    *,
    local_date: date,
) -> ResolvedTemporalReference | None:
    kind = str(raw.get("kind") or "").strip().lower()
    value = str(raw.get("value") or "").strip().lower()
    role = str(raw.get("role") or "context").strip().lower() or "context"
    if not kind or not value:
        return None
    resolved: date | None = None
    if kind == "relative_day":
        delta = RELATIVE_DAY_DELTAS.get(value)
        if delta is not None:
            resolved = local_date + timedelta(days=delta)
    elif kind == "weekday":
        weekday = WEEKDAY_VALUES.get(value)
        if weekday is not None:
            delta = weekday - local_date.weekday()
            if delta < 0:
                delta += 7
            resolved = local_date + timedelta(days=delta)
    elif kind == "date":
        try:
            resolved = date.fromisoformat(value[:10])
        except ValueError:
            resolved = None
    if resolved is None:
        return None
    return ResolvedTemporalReference(
        role=role,
        kind=kind,
        value=value,
        resolved_date=resolved,
        day_label=DAY_LABELS_FR.get(resolved.weekday(), resolved.isoformat()),
    )


def _format_plan_window_fact(fact: PlanWindowFact) -> str:
    pieces = [
        f"{fact.scheduled_date.isoformat()} ({fact.day_label})",
        f"id={fact.session_id}" if fact.session_id is not None else "id=unknown",
        fact.sport or "sport",
    ]
    if fact.title:
        pieces.append(f'"{fact.title}"')
    if fact.duration_min is not None:
        pieces.append(f"{fact.duration_min}min")
    if fact.intensity:
        pieces.append(f"intensity={fact.intensity}")
    pieces.append(f"[{fact.completion_status}]")
    pieces.append(f"slot={fact.slot_kind}")
    return " ".join(pieces)


def _slot_kind(*, sport: str, session_type: str, completion_status: str) -> str:
    if completion_status in CLOSED_STATUSES:
        return "closed"
    if sport in REST_SPORTS or session_type in REST_SESSION_TYPES:
        return "free_flexible"
    return "training"


def _value(obj: Any, key: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, Mapping):
        return obj.get(key)
    return getattr(obj, key, None)


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
