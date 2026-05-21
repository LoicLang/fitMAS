from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

logger = logging.getLogger(__name__)


LegacyDecisionArtifactKind = Literal[
    "coach_decision",
    "legacy_readonly",
    "none",
    "unsupported",
]


@dataclass(frozen=True, slots=True)
class LegacyCoachDecisionArtifact:
    kind: LegacyDecisionArtifactKind
    response_type: str = "reply"
    rationale: str = ""
    reply_hint: str = ""
    confirmation_reason: str | None = None
    mutation_decision: Any | None = None
    plan_patch: Any | None = None
    memory_actions: tuple[Any, ...] = ()
    execution_actions: tuple[Any, ...] = ()
    pending_resolution: Any | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)
    source: str = "coach_decision"

    @property
    def is_coach_decision(self) -> bool:
        return self.kind == "coach_decision"

    @property
    def is_legacy_readonly(self) -> bool:
        return self.kind == "legacy_readonly"

    @property
    def has_value(self) -> bool:
        return self.kind not in {"none", "unsupported"}

    @property
    def mutation_type(self) -> str:
        if self.kind == "legacy_readonly":
            return "no_change"
        if self.mutation_decision is not None:
            return _clean_str(getattr(self.mutation_decision, "mutation_type", None))
        return ""


def legacy_decision_artifact_from_raw(value: Any) -> LegacyCoachDecisionArtifact:
    if value is None:
        return LegacyCoachDecisionArtifact(kind="none")
    if _looks_like_coach_decision(value):
        return LegacyCoachDecisionArtifact(
            kind="coach_decision",
            response_type=_clean_str(getattr(value, "response_type", None), default="reply"),
            rationale=_clean_str(getattr(value, "rationale", None)),
            reply_hint=_clean_str(getattr(value, "fitmas_message", None)),
            confirmation_reason=_clean_optional_str(getattr(value, "confirmation_reason", None)),
            mutation_decision=getattr(value, "mutation_decision", None),
            plan_patch=getattr(value, "plan_patch", None),
            memory_actions=_tuple_or_empty(getattr(value, "memory_actions", None)),
            execution_actions=_tuple_or_empty(getattr(value, "execution_actions", None)),
            pending_resolution=getattr(value, "pending_resolution", None),
            payload=_raw_payload_without_message(value),
        )
    if _looks_like_legacy_readonly(value):
        return LegacyCoachDecisionArtifact(
            kind="legacy_readonly",
            response_type="no_change",
            rationale=_clean_str(getattr(value, "rationale", None)),
            reply_hint=_clean_str(getattr(value, "fitmas_message", None)),
            payload=_raw_payload_without_message(value),
            source="legacy_readonly",
        )
    if _looks_like_legacy_mutation_decision(value):
        return LegacyCoachDecisionArtifact(
            kind="unsupported",
            response_type="mutation_decision",
            rationale=_clean_str(getattr(value, "rationale", None)),
            reply_hint=_clean_str(getattr(value, "fitmas_message", None)),
            mutation_decision=value,
            payload=_raw_payload_without_message(value),
            source="unsupported_mutation_decision",
        )
    return LegacyCoachDecisionArtifact(
        kind="unsupported",
        rationale=_clean_str(getattr(value, "rationale", None)),
        source="unsupported",
    )


def legacy_decision_artifact_payload(artifact: LegacyCoachDecisionArtifact) -> dict[str, Any]:
    return {
        "kind": artifact.kind,
        "source": artifact.source,
        "response_type": artifact.response_type,
        "mutation_type": artifact.mutation_type,
        "rationale": artifact.rationale,
        "reply_hint": artifact.reply_hint,
        "confirmation_reason": artifact.confirmation_reason,
        "has_mutation_decision": artifact.mutation_decision is not None,
        "has_plan_patch": artifact.plan_patch is not None,
        "has_pending_resolution": artifact.pending_resolution is not None,
        "memory_action_count": len(artifact.memory_actions),
        "execution_action_count": len(artifact.execution_actions),
    }


def legacy_decision_artifact_json(artifact: LegacyCoachDecisionArtifact) -> str:
    return json.dumps(
        legacy_decision_artifact_payload(artifact),
        ensure_ascii=True,
        default=str,
        separators=(",", ":"),
    )


def is_coach_decision_artifact(value: Any) -> bool:
    return isinstance(value, LegacyCoachDecisionArtifact) and value.is_coach_decision


def is_legacy_readonly_artifact(value: Any) -> bool:
    return isinstance(value, LegacyCoachDecisionArtifact) and value.is_legacy_readonly


def legacy_readonly_decision_payload(artifact: LegacyCoachDecisionArtifact) -> dict[str, Any]:
    return legacy_decision_artifact_payload(artifact)


def coach_decision_payload(artifact: LegacyCoachDecisionArtifact) -> dict[str, Any]:
    return legacy_decision_artifact_payload(artifact)


def legacy_decision_reply_text(artifact: LegacyCoachDecisionArtifact) -> str:
    return str(getattr(artifact, "reply_hint", "") or "")


def decision_json_for_turn(decision: Any | None) -> str:
    if decision is None:
        return "{}"
    if isinstance(decision, LegacyCoachDecisionArtifact):
        return legacy_decision_artifact_json(decision)
    try:
        if hasattr(decision, "model_dump_json"):
            return str(decision.model_dump_json())
        if hasattr(decision, "model_dump"):
            return json.dumps(decision.model_dump(mode="json"), ensure_ascii=True, default=str)
        if isinstance(decision, dict):
            return json.dumps(decision, ensure_ascii=True, default=str)
    except Exception:
        logger.exception("conversation_decision_json_serialization_failed")
    return "{}"


def _looks_like_coach_decision(value: Any) -> bool:
    return value is not None and hasattr(value, "response_type") and hasattr(value, "fitmas_message")


def _looks_like_legacy_readonly(value: Any) -> bool:
    return bool(
        value is not None
        and not hasattr(value, "response_type")
        and _clean_str(getattr(value, "mutation_type", None)) == "no_change"
        and hasattr(value, "fitmas_message")
    )


def _looks_like_legacy_mutation_decision(value: Any) -> bool:
    return bool(value is not None and not hasattr(value, "response_type") and hasattr(value, "mutation_type"))


def _raw_payload_without_message(value: Any) -> Mapping[str, Any]:
    payload: Mapping[str, Any]
    if hasattr(value, "model_dump"):
        try:
            payload = dict(value.model_dump(mode="json"))
        except TypeError:
            payload = dict(value.model_dump())
    else:
        payload = {
            key: item
            for key, item in vars(value).items()
            if not key.startswith("_")
        } if hasattr(value, "__dict__") else {}
    return {key: item for key, item in payload.items() if key != "fitmas_message"}


def _tuple_or_empty(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        return tuple(value)
    return (value,)


def _clean_optional_str(value: Any) -> str | None:
    text = _clean_str(value)
    return text or None


def _clean_str(value: Any, *, default: str = "") -> str:
    text = str(value or "").strip()
    return text or default
