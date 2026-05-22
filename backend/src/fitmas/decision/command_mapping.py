from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from fitmas.decision import CoachUnderstanding, Command, UserSignal
from fitmas.decision.command_actions import (
    AvailabilityConstraintAction,
    ExecutionUpdateAction,
    HealthSignalAction,
    MemoryAction,
    PreferenceSignalAction,
)


@dataclass(frozen=True, slots=True)
class CoachCommandBundle:
    commands: tuple[Command, ...]
    deferred_execution_count: int = 0
    source: str = "coach_decision"


def commands_from_legacy_decision(decision_artifact: Any, *, turn_plan: Any | None) -> CoachCommandBundle:
    memory_actions = tuple(getattr(decision_artifact, "memory_actions", ()) or ())
    memory_actions = _memory_actions_with_turn_plan_availability(
        memory_actions=memory_actions,
        turn_plan=turn_plan,
    )
    execution_actions = tuple(getattr(decision_artifact, "execution_actions", ()) or ())
    execution_actions, deferred_execution_count = _defer_conflicting_execution_actions(
        decision_artifact=decision_artifact,
        memory_actions=memory_actions,
        execution_actions=execution_actions,
    )
    return CoachCommandBundle(
        commands=(
            *_commands_from_memory_actions(memory_actions),
            *_commands_from_execution_actions(execution_actions),
        ),
        deferred_execution_count=deferred_execution_count,
        source="coach_decision",
    )


def commands_from_understanding(understanding: CoachUnderstanding) -> CoachCommandBundle:
    memory_actions: list[MemoryAction] = []
    execution_actions: list[ExecutionUpdateAction] = []
    for signal in understanding.extracted_signals:
        if signal.type in {"health", "availability", "preference"}:
            action = _memory_action_from_signal(signal)
            if action is not None:
                memory_actions.append(action)
        elif signal.type == "execution":
            action = _execution_action_from_signal(signal)
            if action is not None:
                execution_actions.append(action)
    return CoachCommandBundle(
        commands=(
            *_commands_from_memory_actions(tuple(memory_actions)),
            *_commands_from_execution_actions(tuple(execution_actions)),
        ),
        deferred_execution_count=0,
        source="coach_understanding",
    )


def memory_action_from_command(command: Command) -> MemoryAction:
    payload = dict(command.payload)
    action_type = str(payload.pop("action_type", None) or payload.get("type") or command.name)
    payload["type"] = action_type
    if action_type == "record_health_signal":
        return HealthSignalAction(**payload)
    if action_type == "record_availability":
        return AvailabilityConstraintAction(**payload)
    if action_type == "record_preference":
        return PreferenceSignalAction(**payload)
    raise ValueError(f"unsupported memory command: {action_type}")


def execution_action_from_command(command: Command) -> ExecutionUpdateAction:
    payload = dict(command.payload)
    payload["type"] = str(payload.pop("action_type", None) or payload.get("type") or command.name)
    return ExecutionUpdateAction(**payload)


def _commands_from_memory_actions(actions: Iterable[Any]) -> tuple[Command, ...]:
    commands: list[Command] = []
    for index, action in enumerate(actions):
        commands.append(
            Command(
                id=f"memory:{index}:{getattr(action, 'type', 'unknown')}",
                domain="memory",
                name=str(getattr(action, "type", "") or "memory_action"),
                payload=_action_payload(action),
            )
        )
    return tuple(commands)


def _commands_from_execution_actions(actions: Iterable[Any]) -> tuple[Command, ...]:
    commands: list[Command] = []
    for index, action in enumerate(actions):
        commands.append(
            Command(
                id=f"execution:{index}:{getattr(action, 'type', 'unknown')}",
                domain="execution",
                name=str(getattr(action, "type", "") or "execution_action"),
                payload=_action_payload(action),
            )
        )
    return tuple(commands)


def _action_payload(action: Any) -> dict[str, Any]:
    if hasattr(action, "model_dump"):
        return dict(action.model_dump(mode="json", exclude_none=True))
    return {}


def _memory_actions_with_turn_plan_availability(*, memory_actions: tuple, turn_plan: Any | None) -> tuple:
    turn_plan_action = _availability_memory_action_from_turn_plan(turn_plan)
    if turn_plan_action is None:
        return memory_actions
    if any(_availability_actions_match(existing, turn_plan_action) for existing in memory_actions):
        return memory_actions
    return (*memory_actions, turn_plan_action)


def _availability_actions_match(existing: Any, candidate: Any) -> bool:
    if str(getattr(existing, "type", "") or "") != "record_availability":
        return False
    fields = ("availability", "sport_type", "scope", "starts_on", "ends_on")
    return all(
        _normalized_pending_value(getattr(existing, field, None))
        == _normalized_pending_value(getattr(candidate, field, None))
        for field in fields
    )


def _defer_conflicting_execution_actions(
    *,
    decision_artifact: Any,
    memory_actions: tuple,
    execution_actions: tuple,
) -> tuple[tuple, int]:
    if not execution_actions:
        return execution_actions, 0
    if str(getattr(decision_artifact, "response_type", "") or "") not in {"plan_patch", "requires_confirmation"}:
        return execution_actions, 0
    if not _has_availability_memory_action(memory_actions):
        return execution_actions, 0
    patch = getattr(decision_artifact, "plan_patch", None)
    patch_session_ids = _plan_patch_session_ids(patch)
    if not patch_session_ids:
        return execution_actions, 0
    kept = []
    deferred = 0
    for action in execution_actions:
        status = str(getattr(action, "status", "") or "")
        target_session_id = getattr(action, "target_session_id", None)
        if status == "not_completed" and target_session_id in patch_session_ids:
            deferred += 1
            continue
        kept.append(action)
    return tuple(kept), deferred


def _has_availability_memory_action(memory_actions: tuple) -> bool:
    return any(
        str(getattr(action, "type", "") or "") == "record_availability"
        for action in memory_actions
    )


def _plan_patch_session_ids(patch: Any) -> set[int]:
    ids: set[int] = set()
    for operation in tuple(getattr(patch, "operations", ()) or ()):
        for field_name in ("target_session_id", "second_session_id"):
            raw = getattr(operation, field_name, None)
            try:
                value = int(raw)
            except (TypeError, ValueError):
                continue
            ids.add(value)
    return ids


def _availability_memory_action_from_turn_plan(turn_plan: Any | None):
    raw = getattr(turn_plan, "availability_constraint", None)
    if not isinstance(raw, dict):
        return None
    availability = _clean_enum_value(
        raw.get("availability"),
        allowed={"unavailable", "limited", "available", "unknown"},
        default="unknown",
    )
    if availability == "unknown":
        return None
    sport_type = _clean_optional_artifact_value(raw.get("sport_type"))
    starts_on = _clean_optional_artifact_value(raw.get("starts_on"))
    ends_on = _clean_optional_artifact_value(raw.get("ends_on"))
    scope = _clean_optional_artifact_value(raw.get("scope"))
    window_text = _availability_window_text(
        availability=availability,
        sport_type=sport_type,
        starts_on=starts_on,
        ends_on=ends_on,
    )
    try:
        return AvailabilityConstraintAction(
            type="record_availability",
            window_text=window_text,
            availability=availability,
            sport_type=sport_type,
            scope=scope,
            starts_on=starts_on,
            ends_on=ends_on,
            confidence=float(getattr(turn_plan, "confidence", 0.75) or 0.75),
            evidence="turn_plan.availability_constraint",
        )
    except Exception:
        return None


def _clean_enum_value(value: object, *, allowed: set[str], default: str) -> str:
    cleaned = str(value or "").strip().lower()
    return cleaned if cleaned in allowed else default


def _clean_optional_artifact_value(value: object) -> str | None:
    cleaned = str(value or "").strip()
    if not cleaned or cleaned.lower() in {"unknown", "null", "none"}:
        return None
    return cleaned


def _availability_window_text(
    *,
    availability: str,
    sport_type: str | None,
    starts_on: str | None,
    ends_on: str | None,
) -> str:
    subject = sport_type or "availability"
    if starts_on or ends_on:
        return f"{subject} {availability} {starts_on or '?'}..{ends_on or '?'}"
    return f"{subject} {availability}"


def _normalized_pending_value(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        return stripped.lower()
    return value


def _memory_action_from_signal(signal: UserSignal) -> MemoryAction | None:
    payload = dict(signal.payload)
    action_type = _signal_action_type(signal)
    common = {
        "confidence": float(payload.get("confidence") or signal.confidence),
        "evidence": str(payload.get("evidence") or signal.evidence or ""),
    }
    if action_type == "record_health_signal":
        return HealthSignalAction(
            type="record_health_signal",
            health_signal=str(payload.get("health_signal") or signal.label),
            body_area=_optional_str(payload.get("body_area")),
            status=_health_status(payload.get("status") or signal.status),
            severity=_health_severity(payload.get("severity") or signal.severity),
            signal_kind=_health_signal_kind(payload.get("signal_kind")),
            **common,
        )
    if action_type == "record_availability":
        return AvailabilityConstraintAction(
            type="record_availability",
            window_text=str(payload.get("window_text") or signal.label),
            availability=_availability_status(payload.get("availability")),
            sport_type=_optional_str(payload.get("sport_type")),
            scope=_optional_str(payload.get("scope")),
            starts_on=_optional_str(payload.get("starts_on")),
            ends_on=_optional_str(payload.get("ends_on")),
            **common,
        )
    if action_type == "record_preference":
        return PreferenceSignalAction(
            type="record_preference",
            preference=str(payload.get("preference") or signal.label),
            polarity=_preference_polarity(payload.get("polarity")),
            scope=_optional_str(payload.get("scope")),
            **common,
        )
    return None


def _execution_action_from_signal(signal: UserSignal) -> ExecutionUpdateAction | None:
    payload = dict(signal.payload)
    action_type = _signal_action_type(signal)
    if action_type != "record_execution_update":
        return None
    return ExecutionUpdateAction(
        type="record_execution_update",
        target_ref=str(payload.get("target_ref") or ""),
        target_session_id=_optional_int(payload.get("target_session_id")),
        status=_execution_status(payload.get("status")),
        completed=_optional_bool(payload.get("completed")),
        sport_type=_optional_str(payload.get("sport_type")),
        duration_min=_optional_int(payload.get("duration_min")),
        confidence=float(payload.get("confidence") or signal.confidence),
        evidence=str(payload.get("evidence") or signal.evidence or ""),
    )


def _signal_action_type(signal: UserSignal) -> str:
    payload = dict(signal.payload)
    explicit = str(payload.get("action_type") or payload.get("type") or "").strip()
    if explicit:
        return explicit
    return {
        "health": "record_health_signal",
        "availability": "record_availability",
        "preference": "record_preference",
        "execution": "record_execution_update",
    }.get(signal.type, "")


def _optional_str(value: object) -> str | None:
    text = str(value or "").strip()
    if not text or text.lower() in {"unknown", "null", "none"}:
        return None
    return text


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    cleaned = str(value or "").strip().lower()
    if cleaned in {"true", "1", "yes"}:
        return True
    if cleaned in {"false", "0", "no"}:
        return False
    return None


def _health_status(value: object) -> str:
    cleaned = str(value or "").strip().lower()
    if cleaned in {"new", "ongoing", "improving", "worsening", "resolved", "unknown"}:
        return cleaned
    if cleaned == "open":
        return "ongoing"
    return "unknown"


def _health_severity(value: object) -> str:
    cleaned = str(value or "").strip().lower()
    if cleaned in {"mild", "moderate", "severe", "unknown"}:
        return cleaned
    if cleaned == "low":
        return "mild"
    if cleaned == "medium":
        return "moderate"
    if cleaned == "high":
        return "severe"
    return "unknown"


def _health_signal_kind(value: object) -> str:
    cleaned = str(value or "").strip().lower()
    if cleaned in {"pain", "injury", "fatigue", "sleep", "illness", "tension", "other"}:
        return cleaned
    return "other"


def _availability_status(value: object) -> str:
    cleaned = str(value or "").strip().lower()
    if cleaned in {"unavailable", "limited", "available", "unknown"}:
        return cleaned
    return "unknown"


def _preference_polarity(value: object) -> str:
    cleaned = str(value or "").strip().lower()
    if cleaned in {"prefer", "avoid", "like", "dislike", "neutral", "unknown"}:
        return cleaned
    return "unknown"


def _execution_status(value: object) -> str:
    cleaned = str(value or "").strip().lower()
    if cleaned in {"completed", "not_completed", "partially_completed", "unknown"}:
        return cleaned
    return "unknown"
