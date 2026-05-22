from __future__ import annotations

from types import SimpleNamespace

from fitmas.domain.planning.evaluator import PlanCandidateEvaluator
from fitmas.domain.planning.models import PlanningCandidateSet
from fitmas.domain.planning.policy import SportPolicy
from fitmas.domain.planning.plan_patch import PlanPatch, PlanPatchOperation, PlanPatchValidation
from fitmas.domain.planning.evaluator import EvaluatedPlanPatchCandidate
from fitmas.domain.planning.candidates import PlanPatchCandidate, PlanPatchCandidateValidation
from fitmas.domain.planning.week_coherence import WeekCoherenceScore


def _candidate() -> PlanPatchCandidate:
    return PlanPatchCandidate(
        id="candidate_a",
        patches=(),
        rationale="move",
        expected_tradeoff="low",
        confidence=0.9,
        assumptions=(),
        risk_notes=(),
        created_from_plan_id="plan_current",
        created_from_plan_version=1,
        candidate_ref="backend:move_session:42:2026-05-15",
    )


def _evaluated(candidate: PlanPatchCandidate | None = None) -> EvaluatedPlanPatchCandidate:
    candidate = candidate or _candidate()
    return EvaluatedPlanPatchCandidate(
        candidate=candidate,
        candidate_validation=PlanPatchCandidateValidation(
            status="valid",
            patch_count=1,
            operation_count=1,
            operation_results=(),
        ),
        patch=PlanPatch(coach_message="ok", operations=[]),
        patch_validation=PlanPatchValidation(status="valid", operation_results=()),
        week_context=None,
        facts=None,
        score=WeekCoherenceScore(
            total=90,
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
        evaluation_summary="ok",
    )


def test_evaluator_delegates_to_existing_candidate_evaluator(monkeypatch) -> None:
    calls = []

    def fake_evaluate(db, **kwargs):
        calls.append(kwargs)
        candidate = kwargs["candidate"]
        return EvaluatedPlanPatchCandidate(
            candidate=candidate,
            candidate_validation=PlanPatchCandidateValidation(
                status="valid",
                patch_count=0,
                operation_count=0,
                operation_results=(),
            ),
            patch=kwargs["backend_candidate_patches"][candidate.candidate_ref],
            patch_validation=None,
            week_context=None,
            facts=None,
            score=WeekCoherenceScore(
                total=90,
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
            evaluation_summary="ok",
        )

    monkeypatch.setattr("fitmas.domain.planning.evaluator.evaluate_plan_patch_candidate", fake_evaluate)
    patch = PlanPatch(
        coach_message="Candidate backend.",
        operations=[
            PlanPatchOperation(
                operation_type="move_session",
                target_session_id=42,
                target_date="2026-05-15",
                rationale="move",
            )
        ],
    )
    candidate_set = PlanningCandidateSet(
        candidates=(_candidate(),),
        backend_candidate_patches={"backend:move_session:42:2026-05-15": patch},
    )

    evaluated = PlanCandidateEvaluator(db=object(), user=SimpleNamespace(id=1, timezone="Europe/Paris")).evaluate(
        candidate_set,
        scheduled_sessions=(),
        activities=(),
        active_facts=(),
        coach_state_bundle=None,
    )

    assert len(evaluated) == 1
    assert calls[0]["current_plan_id"] == "plan_current"
    assert calls[0]["current_plan_version"] == 1
    assert calls[0]["backend_candidate_patches"] == candidate_set.backend_candidate_patches


def test_policy_maps_existing_policy_result() -> None:
    decision = SportPolicy().decide(())

    assert decision.action == "block"
    assert decision.reason == "Aucune option d'adaptation valide."


def test_policy_forces_pending_confirmation_when_requested() -> None:
    decision = SportPolicy().decide(
        (_evaluated(),),
        force_confirmation_reason="Fenetre large: confirmation obligatoire.",
    )

    assert decision.action == "pending_confirmation"
    assert decision.selected_candidate_id == "candidate_a"
    assert decision.reason == "Fenetre large: confirmation obligatoire."
    assert decision.requires_confirmation_reason == "Fenetre large: confirmation obligatoire."
    assert decision.pending_event == {
        "candidate_id": "candidate_a",
        "reason": "Fenetre large: confirmation obligatoire.",
        "risk_level": "medium",
    }
