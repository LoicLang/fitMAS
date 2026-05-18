from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from fitmas.decision import (
    ClarificationNeed,
    CoachUnderstanding,
    PendingResolution,
    RequestedPlanChange,
    UserSignal,
)
from fitmas.llm import gateway as gw
from fitmas.llm.prompts.understanding import UnderstandingPromptInput, build_understanding_prompt


FORBIDDEN_UNDERSTANDING_KEYS = {
    "_".join(("reply", "text")),
    "final_reply",
    "_".join(("fitmas", "message")),
    "coach_message",
    "plan_patch",
    "mutation_decision",
    "commands",
    "memory_actions",
    "execution_actions",
}


@dataclass(frozen=True, slots=True)
class UnderstandingRequest:
    event_summary: str
    context_blocks: tuple[str, ...]


class LLMUnderstandingService:
    def __init__(self, request_json_fn: Callable[..., dict | None] | None = None) -> None:
        self._request_json_fn = request_json_fn or gw.request_json

    def understand(self, request: UnderstandingRequest) -> CoachUnderstanding | None:
        rendered = build_understanding_prompt(
            UnderstandingPromptInput(
                event_summary=request.event_summary,
                context_blocks=request.context_blocks,
            )
        )
        payload = self._request_json_fn(
            system=rendered.system,
            prompt=rendered.prompt,
            max_tokens=rendered.max_tokens,
            schema_hint="CoachUnderstanding",
        )
        return parse_coach_understanding_payload(payload)


def parse_coach_understanding_payload(payload: Mapping[str, Any] | None) -> CoachUnderstanding | None:
    if not isinstance(payload, Mapping):
        return None
    if FORBIDDEN_UNDERSTANDING_KEYS.intersection(payload.keys()):
        return None
    intent = str(payload.get("intent") or "general_answer")
    signals = _signals(payload.get("extracted_signals"))
    try:
        return CoachUnderstanding(
            intent=intent,
            confidence=_confidence(payload.get("confidence"), default=0.5),
            user_summary=str(payload.get("user_summary") or "").strip(),
            extracted_signals=signals,
            requested_change=_requested_change(payload.get("requested_change"), signals=signals)
            if intent == "plan_change"
            else None,
            pending_resolution=_pending_resolution(payload.get("pending_resolution"))
            if intent == "pending_response"
            else None,
            clarification_need=_clarification_need(payload.get("clarification_need")) if intent == "clarification" else None,
        )
    except (TypeError, ValueError):
        return None


def _signals(value: Any) -> tuple[UserSignal, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    signals: list[UserSignal] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        signal_type = str(item.get("type") or "other")
        if signal_type in {"fatigue", "pain"}:
            signal_type = "readiness" if signal_type == "fatigue" else "health"
        signals.append(
            UserSignal(
                type=signal_type,
                label=str(item.get("label") or item.get("type") or "other"),
                status=str(item.get("status") or "unknown"),
                severity=str(item.get("severity") or "unknown"),
                confidence=_confidence(item.get("confidence"), default=0.7),
                evidence=_optional_str(item.get("evidence")),
                payload=_mapping(item.get("payload")),
            )
        )
    return tuple(signals)


def _requested_change(value: Any, *, signals: tuple[UserSignal, ...]) -> RequestedPlanChange | None:
    if not isinstance(value, Mapping):
        return None
    source_ref = _normalize_plan_ref(value.get("source_ref")) or _source_ref_from_signals(signals)
    target_ref = _normalize_plan_ref(value.get("target_ref")) or _target_ref_from_signals(signals)
    return RequestedPlanChange(
        kind=str(value.get("kind") or "unknown"),
        source_ref=source_ref,
        target_ref=target_ref,
        desired_sport=_optional_str(value.get("desired_sport")),
        desired_duration_min=_optional_int(value.get("desired_duration_min")),
        desired_intensity=_optional_str(value.get("desired_intensity")),
        reason=str(value.get("reason") or "").strip(),
        risk_signals=tuple(str(item) for item in value.get("risk_signals") or ()),
    )


def _pending_resolution(value: Any) -> PendingResolution | None:
    if not isinstance(value, Mapping):
        return None
    resolution_type = str(value.get("type") or "ignore")
    legacy_map = {
        "accept": "accept_pending",
        "reject": "reject_pending",
        "modify": "modify_pending",
    }
    return PendingResolution(
        type=legacy_map.get(resolution_type, resolution_type),
        reason=_optional_str(value.get("reason")),
        selected_candidate_id=_optional_str(value.get("selected_candidate_id")),
        requested_changes=_optional_str(value.get("requested_changes")),
        question=_optional_str(value.get("question")),
    )


def _clarification_need(value: Any) -> ClarificationNeed | None:
    if not isinstance(value, Mapping):
        return None
    question_intent = _optional_str(value.get("question_intent")) or _optional_str(value.get("question")) or "clarify"
    return ClarificationNeed(
        reason=str(value.get("reason") or value.get("question") or "").strip(),
        missing_fields=tuple(str(item) for item in value.get("missing_fields") or ()),
        question_intent=question_intent,
    )


def _mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _optional_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _normalize_plan_ref(value: Any) -> str | None:
    if isinstance(value, Mapping):
        session_id = value.get("session_id") or value.get("session")
        if session_id is not None:
            raw_id = str(session_id).strip()
            if raw_id.isdigit():
                return f"session_id:{raw_id}"
        raw_date = value.get("date")
        if raw_date is not None:
            date_text = str(raw_date).strip()
            if date_text:
                return f"date:{date_text[:10]}"
        raw_day = value.get("day")
        if raw_day is not None:
            day_text = str(raw_day).strip()
            if day_text:
                return f"day:{day_text}"
        return None
    text = _optional_str(value)
    if text is None:
        return None
    for prefix in ("session_id:", "session:", "session_", "id:"):
        if text.startswith(prefix):
            raw_id = text.split(prefix, 1)[1].strip()
            if raw_id.isdigit():
                return f"session_id:{raw_id}"
    for prefix in ("date:", "date_"):
        if text.startswith(prefix):
            raw_date = text.split(prefix, 1)[1].strip()
            if _looks_like_iso_date(raw_date):
                return f"date:{raw_date[:10]}"
    for prefix in ("day:", "day_"):
        if text.startswith(prefix):
            raw_day = text.split(prefix, 1)[1].strip()
            if _looks_like_iso_date(raw_day):
                return f"date:{raw_day[:10]}"
            if raw_day:
                return f"day:{raw_day}"
    if _looks_like_iso_date(text):
        return f"date:{text[:10]}"
    return text


def _source_ref_from_signals(signals: tuple[UserSignal, ...]) -> str | None:
    for signal in signals:
        payload = signal.payload
        raw_id = payload.get("target_session_id") or payload.get("session_id") or payload.get("source_session_id")
        if raw_id is None:
            continue
        text = str(raw_id).strip()
        if text.isdigit():
            return f"session_id:{text}"
    return None


def _target_ref_from_signals(signals: tuple[UserSignal, ...]) -> str | None:
    for signal in signals:
        payload = signal.payload
        raw_ref = payload.get("target_ref") or payload.get("target_date") or payload.get("starts_on")
        normalized = _normalize_plan_ref(raw_ref)
        if normalized is not None:
            return normalized
    return None


def _looks_like_iso_date(text: str) -> bool:
    if len(text) < 10:
        return False
    if len(text) > 10 and text[10] not in {"T", " "}:
        return False
    parts = text[:10].split("-")
    return len(parts) == 3 and all(part.isdigit() for part in parts)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _confidence(value: Any, *, default: float) -> float:
    if isinstance(value, (int, float)):
        return max(0.0, min(1.0, float(value)))
    return default
