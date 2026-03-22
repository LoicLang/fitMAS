from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from fitmas.execution_context import build_today_execution_context
from fitmas.fact_memory import select_relevant_facts
from fitmas.time_context import get_local_now, get_timezone
from fitmas.tool_contract import ToolContext, ToolResult, ToolSpec


def build_tool_registry() -> dict[str, ToolSpec]:
    specs = (
        ToolSpec(
            name="get_today_context",
            description="Retourne le contexte d'execution du jour: prevu, reel, ecart et activites recentes.",
            input_schema={"type": "object", "properties": {}, "required": []},
            allowed_pipelines=("conversation",),
            handler=_get_today_context,
        ),
        ToolSpec(
            name="get_plan_window",
            description="Retourne les seances planifiees sur une fenetre de dates.",
            input_schema={
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Date debut ISO YYYY-MM-DD."},
                    "end_date": {"type": "string", "description": "Date fin ISO YYYY-MM-DD."},
                    "limit": {"type": "integer", "description": "Nombre max de seances a retourner."},
                },
                "required": [],
            },
            allowed_pipelines=("conversation", "planning"),
            handler=_get_plan_window,
        ),
        ToolSpec(
            name="get_recent_activities",
            description="Retourne les activites recentes sur N jours.",
            input_schema={
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "Nombre de jours a couvrir."},
                    "limit": {"type": "integer", "description": "Nombre max d'activites a retourner."},
                },
                "required": [],
            },
            allowed_pipelines=("conversation", "planning"),
            handler=_get_recent_activities,
        ),
        ToolSpec(
            name="get_activity_highlights",
            description="Retourne quelques highlights activite: plus longue sortie, plus grande distance, plus rapide.",
            input_schema={
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "Fenetre recente en jours pour calculer les highlights."},
                },
                "required": [],
            },
            allowed_pipelines=("conversation",),
            handler=_get_activity_highlights,
        ),
        ToolSpec(
            name="get_relevant_facts",
            description="Retourne la memoire utile la plus pertinente selon un affect.",
            input_schema={
                "type": "object",
                "properties": {
                    "affects": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Liste d'affects vises, ex: conversation, planning, heartbeat.",
                    },
                    "limit": {"type": "integer", "description": "Nombre max de facts."},
                },
                "required": [],
            },
            allowed_pipelines=("conversation", "planning", "heartbeat"),
            handler=_get_relevant_facts,
        ),
    )
    return {spec.name: spec for spec in specs}


def list_tools_for_pipeline(pipeline: str) -> list[dict[str, Any]]:
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "input_schema": dict(spec.input_schema),
        }
        for spec in build_tool_registry().values()
        if pipeline in spec.allowed_pipelines
    ]


def _get_today_context(context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
    summary = build_today_execution_context(
        timezone_name=context.timezone_name,
        scheduled_sessions=context.scheduled_sessions,
        activities=context.activities,
        now=context.now,
    )
    payload = {
        "local_date": summary.local_date.isoformat(),
        "planned_session_id": summary.planned_session_id,
        "planned_sport": summary.planned_sport,
        "planned_title": summary.planned_title,
        "planned_duration_min": summary.planned_duration_min,
        "execution_status": summary.execution_status,
        "actual_sports_today": list(summary.actual_sports_today),
        "actual_duration_min_today": summary.actual_duration_min_today,
    }
    return ToolResult(
        tool_name="get_today_context",
        status="ok",
        payload=payload,
        summary=f"Aujourd'hui: {summary.execution_status}, sport prevu={summary.planned_sport or 'none'}, sports reels={', '.join(summary.actual_sports_today) or 'none'}.",
    )


def _get_plan_window(context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
    local_today = get_local_now(context.timezone_name, now=context.now).date()
    start_date = _parse_date(arguments.get("start_date")) or local_today
    end_date = _parse_date(arguments.get("end_date")) or (start_date + timedelta(days=6))
    limit = _coerce_int(arguments.get("limit"), default=14, minimum=1, maximum=31)
    items: list[dict[str, Any]] = []
    for session in context.scheduled_sessions:
        local_date = _local_date(_value(session, "scheduled_date"), timezone_name=context.timezone_name)
        if local_date is None or local_date < start_date or local_date > end_date:
            continue
        items.append(
            {
                "id": _value(session, "id"),
                "scheduled_date": local_date.isoformat(),
                "sport_type": _value(session, "sport_type"),
                "session_title": _value(session, "session_title"),
                "duration_min": _value(session, "duration_min"),
                "completion_status": _value(session, "completion_status"),
            }
        )
        if len(items) >= limit:
            break
    return ToolResult(
        tool_name="get_plan_window",
        status="ok",
        payload={"start_date": start_date.isoformat(), "end_date": end_date.isoformat(), "sessions": items},
        summary=f"{len(items)} seances entre {start_date.isoformat()} et {end_date.isoformat()}.",
    )


def _get_recent_activities(context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
    local_today = get_local_now(context.timezone_name, now=context.now).date()
    days = _coerce_int(arguments.get("days"), default=7, minimum=1, maximum=90)
    limit = _coerce_int(arguments.get("limit"), default=8, minimum=1, maximum=30)
    cutoff = local_today - timedelta(days=max(0, days - 1))
    items: list[dict[str, Any]] = []
    for activity in context.activities:
        local_date = _local_date(_value(activity, "started_at") or _value(activity, "created_at"), timezone_name=context.timezone_name)
        if local_date is None or local_date < cutoff:
            continue
        items.append(
            {
                "id": _value(activity, "id"),
                "local_date": local_date.isoformat(),
                "sport_type": _value(activity, "sport_type"),
                "title": _value(activity, "title"),
                "duration_min": _value(activity, "duration_min"),
                "distance_m": _value(activity, "distance_m"),
                "avg_speed": _value(activity, "avg_speed"),
            }
        )
        if len(items) >= limit:
            break
    return ToolResult(
        tool_name="get_recent_activities",
        status="ok",
        payload={"days": days, "activities": items},
        summary=f"{len(items)} activites sur {days} jours.",
    )


def _get_activity_highlights(context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
    recent = _get_recent_activities(context, {"days": arguments.get("days", 30), "limit": 60}).payload["activities"]
    longest_duration = max(recent, key=lambda item: item.get("duration_min") or 0, default=None)
    longest_distance = max(recent, key=lambda item: item.get("distance_m") or 0, default=None)
    fastest = max(recent, key=lambda item: item.get("avg_speed") or 0, default=None)
    payload = {
        "longest_duration": longest_duration,
        "longest_distance": longest_distance,
        "fastest": fastest,
    }
    highlights = sum(1 for item in payload.values() if item)
    return ToolResult(
        tool_name="get_activity_highlights",
        status="ok",
        payload=payload,
        summary=f"{highlights} highlights activite disponibles.",
    )


def _get_relevant_facts(context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
    affects = arguments.get("affects")
    if not isinstance(affects, list):
        affects = ["conversation"]
    limit = _coerce_int(arguments.get("limit"), default=6, minimum=1, maximum=20)
    selected = select_relevant_facts(context.active_facts, affects=affects, limit=limit, now=context.now)
    return ToolResult(
        tool_name="get_relevant_facts",
        status="ok",
        payload={"affects": affects, "facts": selected},
        summary=f"{len(selected)} facts pertinents pour {', '.join(affects)}.",
    )


def _coerce_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, coerced))


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _local_date(value: Any, *, timezone_name: str | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    timezone = get_timezone(timezone_name)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.date()
        return value.astimezone(timezone).date()
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            try:
                return date.fromisoformat(value)
            except ValueError:
                return None
        if parsed.tzinfo is None:
            return parsed.date()
        return parsed.astimezone(timezone).date()
    return None


def _value(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)
