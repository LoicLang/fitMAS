from __future__ import annotations

from fitmas.legacy.coach_decision_artifact import legacy_decision_artifact_from_raw
from fitmas.legacy.understanding_shadow import shadow_understanding_from_legacy_decision
from fitmas.llm import CoachDecision


def test_shadow_understanding_returns_none_for_missing_decision() -> None:
    assert shadow_understanding_from_legacy_decision(user_id=1, decision_artifact=None) is None


def test_shadow_understanding_converts_legacy_decision_without_raising() -> None:
    decision = CoachDecision(
        response_type="no_change",
        rationale="lecture simple",
        fitmas_message="Message legacy ignore.",
    )

    understanding = shadow_understanding_from_legacy_decision(
        user_id=1,
        decision_artifact=legacy_decision_artifact_from_raw(decision),
    )

    assert understanding is not None
    assert understanding.intent == "general_answer"
    assert understanding.user_summary == "lecture simple"
