from __future__ import annotations

from typing import Any

from fitmas.legacy.decision_contracts import (
    AcceptPendingResolution,
    AvailabilityConstraintAction,
    CoachDecision,
    ExecutionUpdateAction,
    HealthSignalAction,
    IgnorePendingResolution,
    MemoryAction,
    ModifyPendingResolution,
    MutationDecision,
    NeedsClarificationPendingResolution,
    PendingResolution,
    PreferenceSignalAction,
    RejectPendingResolution,
)

from . import decision_legacy as _legacy


_PATCHABLE_LEGACY_NAMES = (
    "_client",
    "_request_text",
    "_request_message",
    "_request_json",
    "_request_json_with_tools",
    "_request_structured_json",
    "execute_tool_calls",
    "log_tool_trace",
)

_client = _legacy._client
_request_text = _legacy._request_text
_request_message = _legacy._request_message
_request_structured_json = _legacy._request_structured_json
execute_tool_calls = _legacy.execute_tool_calls
log_tool_trace = _legacy.log_tool_trace

_LEGACY_DEFAULTS = {
    "_client": _legacy._client,
    "_request_text": _legacy._request_text,
    "_request_message": _legacy._request_message,
    "_request_json": _legacy._request_json,
    "_request_json_with_tools": _legacy._request_json_with_tools,
    "_request_structured_json": _legacy._request_structured_json,
    "execute_tool_calls": _legacy.execute_tool_calls,
    "log_tool_trace": _legacy.log_tool_trace,
}
_PACKAGE_DEFAULTS = {
    "_client": _client,
    "_request_text": _request_text,
    "_request_message": _request_message,
    "_request_structured_json": _request_structured_json,
    "execute_tool_calls": execute_tool_calls,
    "log_tool_trace": log_tool_trace,
}


def _sync_patchable_legacy_globals() -> None:
    for name in _PATCHABLE_LEGACY_NAMES:
        if name in globals():
            value = globals()[name]
            if value is _PACKAGE_DEFAULTS.get(name) or (
                name == "_request_json" and value is _PACKAGE_REQUEST_JSON_WRAPPER
            ) or (
                name == "_request_json_with_tools"
                and value is _PACKAGE_REQUEST_JSON_WITH_TOOLS_WRAPPER
            ):
                setattr(_legacy, name, _LEGACY_DEFAULTS[name])
                continue
            setattr(_legacy, name, value)


def decide(*args: Any, **kwargs: Any):
    _sync_patchable_legacy_globals()
    return _legacy.decide(*args, **kwargs)


def _request_json(*args: Any, **kwargs: Any):
    _sync_patchable_legacy_globals()
    return _legacy._request_json(*args, **kwargs)


_PACKAGE_REQUEST_JSON_WRAPPER = _request_json


def _request_json_with_tools(*args: Any, **kwargs: Any):
    _sync_patchable_legacy_globals()
    return _legacy._request_json_with_tools(*args, **kwargs)


_PACKAGE_REQUEST_JSON_WITH_TOOLS_WRAPPER = _request_json_with_tools


def clear_last_decide_none() -> None:
    _legacy.clear_last_decide_none()


def get_last_decide_none() -> dict[str, Any] | None:
    return _legacy.get_last_decide_none()


def parse_coach_decision_payload(payload: dict[str, Any]):
    return _legacy.parse_coach_decision_payload(payload)


def __getattr__(name: str):
    attr = getattr(_legacy, name)
    if callable(attr):
        def _wrapped(*args: Any, **kwargs: Any):
            _sync_patchable_legacy_globals()
            return attr(*args, **kwargs)

        return _wrapped
    return attr


__all__ = [
    "AcceptPendingResolution",
    "AvailabilityConstraintAction",
    "CoachDecision",
    "ExecutionUpdateAction",
    "HealthSignalAction",
    "IgnorePendingResolution",
    "MemoryAction",
    "ModifyPendingResolution",
    "MutationDecision",
    "NeedsClarificationPendingResolution",
    "PendingResolution",
    "PreferenceSignalAction",
    "RejectPendingResolution",
    "clear_last_decide_none",
    "decide",
    "get_last_decide_none",
    "parse_coach_decision_payload",
    "_request_json_with_tools",
]
