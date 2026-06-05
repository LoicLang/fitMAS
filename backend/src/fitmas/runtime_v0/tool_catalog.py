from __future__ import annotations

from fitmas.runtime_v0.event import InputEvent
from fitmas.runtime_v0.llm_clients.base import ToolSchema
from fitmas.runtime_v0.snapshot import WorldSnapshot
from fitmas.runtime_v0.tools_proposal import (
    ask_clarification,
    propose_execution_correction,
    propose_execution_update,
    propose_fact_resolution,
    propose_memory_update,
    propose_plan_patch,
)
from fitmas.runtime_v0.tools_read import (
    get_active_facts,
    get_current_plan,
    get_plan_day,
    get_recent_execution_events,
    get_session,
    resolve_date_reference,
)

def for_event(event: InputEvent, snapshot: WorldSnapshot) -> tuple[ToolSchema, ...]:
    if event.type != "user_message":
        return ()
    tools = (
        ToolSchema(
            name="get_current_plan",
            description="Return planned sessions from today through a bounded future window.",
            parameters=_schema({"days": {"type": "integer", "minimum": 1, "maximum": 14}}),
            handler=get_current_plan,
            is_proposal=False,
        ),
        ToolSchema(
            name="get_plan_day",
            description="Return planned sessions for one allowed date.",
            parameters=_schema({"date": {"type": "string", "format": "date"}}, ("date",)),
            handler=get_plan_day,
            is_proposal=False,
        ),
        ToolSchema(
            name="get_session",
            description="Return one planned or recent session by id.",
            parameters=_schema({"session_id": {"type": "integer"}}, ("session_id",)),
            handler=get_session,
            is_proposal=False,
        ),
        ToolSchema(
            name="get_recent_execution_events",
            description="Return recent execution command events.",
            parameters=_schema({"limit": {"type": "integer", "minimum": 1, "maximum": 10}}),
            handler=get_recent_execution_events,
            is_proposal=False,
        ),
        ToolSchema(
            name="get_active_facts",
            description="Return active non-expired user facts.",
            parameters=_schema({}),
            handler=get_active_facts,
            is_proposal=False,
        ),
        ToolSchema(
            name="resolve_date_reference",
            description=(
                "Resolve an LLM-extracted date reference to a concrete ISO date. "
                "Use relative_day for today/tomorrow, or weekday plus direction=future for named weekdays."
            ),
            parameters=_schema(
                {
                    "relative_day": {"type": "string", "enum": ["today", "tomorrow"]},
                    "weekday": {"type": "string", "enum": ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]},
                    "direction": {"type": "string", "enum": ["future"]},
                }
            ),
            handler=resolve_date_reference,
            is_proposal=False,
        ),
        ToolSchema(
            name="propose_execution_update",
            description="Propose a session status update without committing it.",
            parameters=_schema({"session_id": {"type": "integer"}, "status": {"type": "string", "enum": ["done", "skipped", "partial"]}, "duration_min": {"type": "integer"}, "intensity_note": {"type": "string"}, "evidence": {"type": "string"}}, ("session_id", "status")),
            handler=propose_execution_update,
            is_proposal=True,
        ),
        ToolSchema(
            name="propose_execution_correction",
            description="Propose a correction to a recent execution event.",
            parameters=_schema({"previous_event_id": {"type": "integer"}, "correct_session_id": {"type": "integer"}, "correct_status": {"type": "string", "enum": ["done", "skipped", "partial", "planned"]}, "duration_min": {"type": "integer"}, "intensity_note": {"type": "string"}, "evidence": {"type": "string"}}, ("previous_event_id", "correct_session_id", "correct_status")),
            handler=propose_execution_correction,
            is_proposal=True,
        ),
        ToolSchema(
            name="propose_plan_patch",
            description=(
                "Propose a bounded plan patch without committing it. "
                "For lighten, include new_intensity_label and/or new_duration_min. "
                "For replace, include new_sport and any changed intensity/duration."
            ),
            parameters=_schema(
                {
                    "operations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "kind": {
                                    "type": "string",
                                    "enum": ["move", "swap", "lighten", "replace", "remove_optional"],
                                },
                                "source_session_id": {"type": "integer"},
                                "target_date": {"type": "string", "format": "date"},
                                "target_session_id": {"type": "integer"},
                                "new_intensity_label": {
                                    "type": "string",
                                    "enum": ["easy", "moderate", "hard"],
                                },
                                "new_sport": {
                                    "type": "string",
                                    "enum": ["run", "bike", "swim", "strength", "mobility", "rest"],
                                },
                                "new_duration_min": {"type": "integer", "minimum": 1},
                            },
                            "required": ["kind", "source_session_id"],
                        },
                    },
                    "rationale": {"type": "string"},
                },
                ("operations", "rationale"),
            ),
            handler=propose_plan_patch,
            is_proposal=True,
        ),
        ToolSchema(
            name="propose_memory_update",
            description="Propose a user memory fact update without committing it.",
            parameters=_schema({"kind": {"type": "string", "enum": ["preference", "health", "availability", "constraint"]}, "text": {"type": "string"}, "confidence": {"type": "number"}, "expires_at": {"type": "string"}}, ("kind", "text", "confidence")),
            handler=propose_memory_update,
            is_proposal=True,
        ),
        ToolSchema(
            name="propose_fact_resolution",
            description=(
                "Resolve (retract) an active user fact the user reports is over "
                "(e.g. a pain that has passed). Call get_active_facts first to find "
                "the fact_id. Do not create a new contradicting fact."
            ),
            parameters=_schema({"fact_id": {"type": "integer"}, "reason": {"type": "string"}}, ("fact_id",)),
            handler=propose_fact_resolution,
            is_proposal=True,
        ),
        ToolSchema(
            name="ask_clarification",
            description="Ask for missing information and optionally preserve unresolved intent.",
            parameters=_schema({"question": {"type": "string"}, "unresolved_intent": {"type": "object", "properties": {"type": {"type": "string"}, "target_date": {"type": "string"}, "missing": {"type": "array", "items": {"type": "string"}}}}}, ("question", "unresolved_intent")),
            handler=ask_clarification,
            is_proposal=True,
        ),
    )
    if snapshot.conversation_state.last_unresolved_intent and snapshot.conversation_state.last_unresolved_intent.get("type") == "move_session":
        allowed = {"get_current_plan", "get_plan_day", "get_session", "resolve_date_reference", "propose_plan_patch", "ask_clarification"}
        return tuple(tool for tool in tools if tool.name in allowed)
    return tools

def _schema(properties: dict, required: tuple[str, ...] = ()) -> dict:
    return {"type": "object", "properties": properties, "required": list(required)}
