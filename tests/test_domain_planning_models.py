from __future__ import annotations

from datetime import date

from fitmas.legacy.decision import RequestedPlanChange
from fitmas.legacy.domain.planning.models import (
    PlanChangeReference,
    PlanningCandidateSet,
    PlanningDecisionResult,
    ResolvedPlanChange,
)


def test_resolved_plan_change_keeps_requested_change_and_typed_refs() -> None:
    requested = RequestedPlanChange(
        kind="move",
        source_ref="session_id:42",
        target_ref="date:2026-05-15",
        desired_sport=None,
        desired_duration_min=None,
        desired_intensity=None,
        reason="fatigue",
        risk_signals=("fatigue",),
    )
    resolved = ResolvedPlanChange(
        requested_change=requested,
        source=PlanChangeReference(kind="session", raw="session_id:42", session_id=42, date=None),
        target=PlanChangeReference(kind="date", raw="date:2026-05-15", session_id=None, date=date(2026, 5, 15)),
        warnings=(),
    )

    assert resolved.kind == "move"
    assert resolved.source.session_id == 42
    assert resolved.target.date == date(2026, 5, 15)
    assert resolved.reason == "fatigue"


def test_planning_candidate_set_is_backend_owned() -> None:
    candidate_set = PlanningCandidateSet(candidates=(), backend_candidate_patches={})

    assert candidate_set.candidates == ()
    assert candidate_set.backend_candidate_patches == {}


def test_planning_decision_result_has_no_reply_text() -> None:
    result = PlanningDecisionResult(
        kind="block",
        selected_candidate_id=None,
        candidate_options=(),
        reason="Aucune option valide.",
        policy_decision=None,
        selected_patch=None,
        evaluated_candidates=(),
        command_result=None,
        pending_confirmation_id=None,
    )

    assert result.kind == "block"
    assert not hasattr(result, "fitmas_message")
    assert not hasattr(result, "reply_text")
