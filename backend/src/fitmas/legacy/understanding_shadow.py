from __future__ import annotations

import logging

from fitmas.decision import CoachUnderstanding
from fitmas.legacy.coach_decision_artifact import LegacyCoachDecisionArtifact
from fitmas.legacy.coach_understanding_adapter import coach_decision_artifact_to_understanding

logger = logging.getLogger(__name__)


def shadow_understanding_from_legacy_decision(
    *,
    user_id: int,
    decision_artifact: LegacyCoachDecisionArtifact | None,
) -> CoachUnderstanding | None:
    if decision_artifact is None or not decision_artifact.has_value:
        return None
    try:
        understanding = coach_decision_artifact_to_understanding(decision_artifact)
    except Exception as exc:
        logger.warning(
            "decision_runtime.shadow_understanding_failed user=%s error=%s",
            user_id,
            str(exc)[:180],
            exc_info=True,
        )
        return None

    logger.info(
        "decision_runtime.shadow_understanding user=%s intent=%s confidence=%.2f signals=%s requested_change=%s pending=%s",
        user_id,
        understanding.intent,
        understanding.confidence,
        len(understanding.extracted_signals),
        1 if understanding.requested_change is not None else 0,
        1 if understanding.pending_resolution is not None else 0,
    )
    return understanding
