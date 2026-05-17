from __future__ import annotations

import json
import logging
from typing import Any

from fitmas.legacy.coach_decision_artifact import (
    LegacyCoachDecisionArtifact,
    legacy_decision_artifact_json,
    legacy_decision_artifact_payload,
)

logger = logging.getLogger(__name__)


def is_coach_decision(value: Any) -> bool:
    return isinstance(value, LegacyCoachDecisionArtifact) and value.is_coach_decision


def is_legacy_readonly_decision(value: Any) -> bool:
    return isinstance(value, LegacyCoachDecisionArtifact) and value.is_legacy_readonly


def legacy_readonly_decision_payload(decision_artifact: LegacyCoachDecisionArtifact) -> dict[str, Any]:
    return legacy_decision_artifact_payload(decision_artifact)


def legacy_decision_reply_text(decision_artifact: LegacyCoachDecisionArtifact) -> str:
    return str(getattr(decision_artifact, "reply_hint", "") or "")


def coach_decision_payload(decision_artifact: LegacyCoachDecisionArtifact) -> dict[str, Any]:
    return legacy_decision_artifact_payload(decision_artifact)


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
