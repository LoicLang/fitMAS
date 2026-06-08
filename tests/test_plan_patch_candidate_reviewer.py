from __future__ import annotations

from fitmas.legacy.domain.planning.plan_patch import PlanPatch, PlanPatchOperation, PlanPatchValidation
from fitmas.legacy.domain.planning.evaluator import EvaluatedPlanPatchCandidate
from fitmas.legacy.domain.planning.reviewer import review_plan_patch_candidates
from fitmas.legacy.domain.planning.candidates import PlanPatchCandidate, PlanPatchCandidateValidation
from fitmas.legacy.domain.planning.week_coherence import WeekCoherenceScore


def test_reviewer_accepts_only_known_candidate_id_and_ignores_patch_payload() -> None:
    calls: list[dict] = []

    def _request_json(**kwargs):
        calls.append(kwargs)
        return {
            "preferred_candidate_id": "reduce_tomorrow",
            "confidence": 0.78,
            "rationale": ["Meilleur compromis humain."],
            "patch": {"operations": [{"operation_type": "create_session"}]},
        }

    decision = review_plan_patch_candidates(
        [
            _evaluated("move_friday", score_total=84),
            _evaluated("reduce_tomorrow", score_total=82),
        ],
        request_json_fn=_request_json,
    )

    assert decision is not None
    assert decision.preferred_candidate_id == "reduce_tomorrow"
    assert decision.confidence == 0.78
    assert "candidate_id only" in calls[0]["system"]
    assert "create_session" not in decision.rationale


def test_reviewer_rejects_unknown_candidate_id() -> None:
    decision = review_plan_patch_candidates(
        [_evaluated("move_friday", score_total=84)],
        request_json_fn=lambda **kwargs: {
            "preferred_candidate_id": "invented",
            "confidence": 0.9,
            "rationale": ["Invented option."],
        },
    )

    assert decision is None


def _evaluated(candidate_id: str, *, score_total: float) -> EvaluatedPlanPatchCandidate:
    patch = PlanPatch(
        operations=[
            PlanPatchOperation(
                operation_type="move_session",
                target_session_id=42,
                target_date="2099-05-08",
                rationale="Move.",
            )
        ],
        coach_message="Candidate only.",
    )
    candidate = PlanPatchCandidate(
        id=candidate_id,
        patches=(patch,),
        rationale=f"Rationale {candidate_id}.",
        expected_tradeoff="Tradeoff.",
        confidence=0.8,
        assumptions=(),
        risk_notes=(),
        created_from_plan_id="plan_123",
        created_from_plan_version=7,
    )
    return EvaluatedPlanPatchCandidate(
        candidate=candidate,
        candidate_validation=PlanPatchCandidateValidation(
            status="valid",
            patch_count=1,
            operation_count=1,
            operation_results=(),
            summary="Candidate validation.",
        ),
        patch=patch,
        patch_validation=PlanPatchValidation(status="valid", operation_results=(), summary="valid"),
        week_context=None,
        facts=None,
        score=WeekCoherenceScore(
            total=score_total,
            recovery=90,
            goal_alignment=90,
            progression=90,
            adherence=90,
            readiness_fit=90,
            constraint_fit=90,
            risk=90,
        ),
        findings=(),
        score_delta=0,
        policy_hint="commit_safe",
        evaluation_summary="Evaluation.",
    )
