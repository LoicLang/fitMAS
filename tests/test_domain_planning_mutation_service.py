from __future__ import annotations

from types import SimpleNamespace

from fitmas.domain.planning.models import PlanningDecisionResult
from fitmas.domain.planning.mutation_service import PlanningCommandService
from fitmas.domain.planning.mutation_permissions import (
    deserialize_plan_patch_choice_confirmation,
    serialize_plan_patch_choice_confirmation,
    serialize_plan_patch_confirmation,
)
from fitmas.plan_patch import PlanPatch, PlanPatchOperation, PlanPatchValidation
from fitmas.plan_patch_adaptation_policy import AdaptationPolicyDecision
from fitmas.plan_patch_candidate_evaluator import EvaluatedPlanPatchCandidate
from fitmas.plan_patch_candidates import PlanPatchCandidate, PlanPatchCandidateValidation


def _patch() -> PlanPatch:
    return PlanPatch(
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


def _multi_move_patch() -> PlanPatch:
    return PlanPatch(
        coach_message="Candidate backend.",
        confirmation_reason="Fenetre large.",
        operations=[
            PlanPatchOperation(
                operation_type="move_session",
                target_session_id=1,
                target_date="2026-05-23",
                rationale="travel",
            ),
            PlanPatchOperation(
                operation_type="move_session",
                target_session_id=2,
                target_date="2026-05-25",
                rationale="travel",
            ),
        ],
    )


def _decision(kind: str, *, patch: PlanPatch | None = None) -> PlanningDecisionResult:
    return PlanningDecisionResult(
        kind=kind,
        selected_candidate_id="candidate_a" if patch else None,
        candidate_options=(),
        reason="reason",
        policy_decision=AdaptationPolicyDecision(
            action=kind,
            selected_candidate_id="candidate_a" if patch else None,
            candidate_options=(),
            reason="reason",
            user_facing_reason="reason",
            requires_confirmation_reason="reason" if kind.startswith("pending") else None,
            risk_level="medium" if kind.startswith("pending") else "low",
        ),
        selected_patch=patch,
        evaluated_candidates=(),
        command_result=None,
        pending_confirmation_id=None,
    )


def test_command_service_commits_selected_patch(monkeypatch) -> None:
    calls = []

    def fake_apply_patch_for_user(*args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            mutation_result=SimpleNamespace(event_count=1),
            validation=PlanPatchValidation(status="valid", operation_results=(), summary="valid"),
        )

    monkeypatch.setattr("fitmas.domain.planning.mutation_service.apply_patch_for_user", fake_apply_patch_for_user)

    result = PlanningCommandService(db=object(), user=SimpleNamespace(id=1)).apply(
        _decision("commit", patch=_patch()),
        source_text="deplace",
        coach_state_bundle=None,
        activities=(),
        active_facts=(),
    )

    assert result.status == "applied"
    assert result.event_count == 1
    assert calls[0]["trigger_type"] == "planning_decision_runtime"


def test_command_service_persists_pending_confirmation(monkeypatch) -> None:
    pending_rows = []

    def fake_create_pending_mutation_confirmation(db, **kwargs):
        pending_rows.append(kwargs)
        return SimpleNamespace(id=99)

    monkeypatch.setattr(
        "fitmas.domain.planning.mutation_service.repo.create_pending_mutation_confirmation",
        fake_create_pending_mutation_confirmation,
    )
    monkeypatch.setattr(
        "fitmas.domain.planning.mutation_service.repo.get_active_pending_mutation_confirmation",
        lambda db, user_id: None,
    )

    result = PlanningCommandService(db=object(), user=SimpleNamespace(id=1)).apply(
        _decision("pending_confirmation", patch=_patch()),
        source_text="deplace",
        coach_state_bundle=None,
        activities=(),
        active_facts=(),
    )

    assert result.status == "pending"
    assert result.pending_confirmation_id == 99
    assert pending_rows[0]["mutation_type"] == "plan_patch"


def test_command_service_persists_multi_operation_pending_confirmation(monkeypatch) -> None:
    pending_rows = []

    def fake_create_pending_mutation_confirmation(db, **kwargs):
        pending_rows.append(kwargs)
        return SimpleNamespace(id=101)

    monkeypatch.setattr(
        "fitmas.domain.planning.mutation_service.repo.create_pending_mutation_confirmation",
        fake_create_pending_mutation_confirmation,
    )
    monkeypatch.setattr(
        "fitmas.domain.planning.mutation_service.repo.get_active_pending_mutation_confirmation",
        lambda db, user_id: None,
    )

    result = PlanningCommandService(db=object(), user=SimpleNamespace(id=1)).apply(
        _decision("pending_confirmation", patch=_multi_move_patch()),
        source_text="je suis absent du 20 au 22",
        coach_state_bundle=None,
        activities=(),
        active_facts=(),
    )

    stored_patch = serialize_plan_patch_confirmation(_multi_move_patch())
    assert result.status == "pending"
    assert result.event_count == 0
    assert result.pending_confirmation_id == 101
    assert pending_rows[0]["mutation_type"] == "plan_patch"
    assert pending_rows[0]["decision_json"] == stored_patch
    assert "move_session" in pending_rows[0]["decision_json"]
    assert "2026-05-25" in pending_rows[0]["decision_json"]


def test_command_service_reuses_matching_active_pending_confirmation(monkeypatch) -> None:
    pending_rows = []
    patch = _patch()
    existing = SimpleNamespace(
        id=77,
        status="pending",
        mutation_type="plan_patch",
        decision_json=serialize_plan_patch_confirmation(patch),
    )

    def fake_create_pending_mutation_confirmation(db, **kwargs):
        pending_rows.append(kwargs)
        return SimpleNamespace(id=99)

    monkeypatch.setattr(
        "fitmas.domain.planning.mutation_service.repo.get_active_pending_mutation_confirmation",
        lambda db, user_id: existing,
    )
    monkeypatch.setattr(
        "fitmas.domain.planning.mutation_service.repo.create_pending_mutation_confirmation",
        fake_create_pending_mutation_confirmation,
    )

    result = PlanningCommandService(db=object(), user=SimpleNamespace(id=1)).apply(
        _decision("pending_confirmation", patch=patch),
        source_text="deplace",
        coach_state_bundle=None,
        activities=(),
        active_facts=(),
    )

    assert result.status == "pending"
    assert result.pending_confirmation_id == 77
    assert pending_rows == []
    assert result.payload["reused_pending_confirmation"] is True


def test_command_service_materializes_pending_choice_patches(monkeypatch) -> None:
    pending_rows = []
    patch = _patch()
    candidate = PlanPatchCandidate(
        id="candidate_a",
        patches=(),
        rationale="option",
        expected_tradeoff="tradeoff",
        confidence=0.8,
        assumptions=(),
        risk_notes=(),
        created_from_plan_id="plan_current",
        created_from_plan_version=1,
        candidate_ref="backend:move_session:42:2026-05-15",
    )
    evaluated = EvaluatedPlanPatchCandidate(
        candidate=candidate,
        candidate_validation=PlanPatchCandidateValidation(
            status="valid",
            patch_count=0,
            operation_count=0,
            operation_results=(),
            summary="valid",
        ),
        patch=patch,
        patch_validation=PlanPatchValidation(status="valid", operation_results=(), summary="valid"),
        week_context=None,
        facts=None,
        score=None,
        findings=(),
        score_delta=None,
        policy_hint="ask_confirmation",
        evaluation_summary="ok",
    )
    decision = PlanningDecisionResult(
        kind="pending_choice",
        selected_candidate_id=None,
        candidate_options=("candidate_a",),
        reason="choisis",
        policy_decision=AdaptationPolicyDecision(
            action="pending_choice",
            selected_candidate_id=None,
            candidate_options=("candidate_a",),
            reason="choisis",
            user_facing_reason="choisis",
            requires_confirmation_reason="choisis",
            risk_level="medium",
        ),
        selected_patch=None,
        evaluated_candidates=(evaluated,),
        command_result=None,
        pending_confirmation_id=None,
    )

    def fake_create_pending_mutation_confirmation(db, **kwargs):
        pending_rows.append(kwargs)
        return SimpleNamespace(id=100)

    monkeypatch.setattr(
        "fitmas.domain.planning.mutation_service.repo.create_pending_mutation_confirmation",
        fake_create_pending_mutation_confirmation,
    )
    monkeypatch.setattr(
        "fitmas.domain.planning.mutation_service.repo.get_active_pending_mutation_confirmation",
        lambda db, user_id: None,
    )

    result = PlanningCommandService(db=object(), user=SimpleNamespace(id=1)).apply(
        decision,
        source_text="choix",
        coach_state_bundle=None,
        activities=(),
        active_facts=(),
    )

    stored_candidates = deserialize_plan_patch_choice_confirmation(pending_rows[0]["decision_json"])
    assert result.status == "pending"
    assert result.pending_confirmation_id == 100
    assert pending_rows[0]["mutation_type"] == "plan_patch_choice"
    assert stored_candidates[0].patches == (patch,)


def test_command_service_reuses_matching_active_pending_choice(monkeypatch) -> None:
    pending_rows = []
    patch = _patch()
    candidate = PlanPatchCandidate(
        id="candidate_a",
        patches=(),
        rationale="option",
        expected_tradeoff="tradeoff",
        confidence=0.8,
        assumptions=(),
        risk_notes=(),
        created_from_plan_id="plan_current",
        created_from_plan_version=1,
        candidate_ref="backend:move_session:42:2026-05-15",
    )
    evaluated = EvaluatedPlanPatchCandidate(
        candidate=candidate,
        candidate_validation=PlanPatchCandidateValidation(
            status="valid",
            patch_count=0,
            operation_count=0,
            operation_results=(),
            summary="valid",
        ),
        patch=patch,
        patch_validation=PlanPatchValidation(status="valid", operation_results=(), summary="valid"),
        week_context=None,
        facts=None,
        score=None,
        findings=(),
        score_delta=None,
        policy_hint="ask_confirmation",
        evaluation_summary="ok",
    )
    decision = PlanningDecisionResult(
        kind="pending_choice",
        selected_candidate_id=None,
        candidate_options=("candidate_a",),
        reason="choisis",
        policy_decision=AdaptationPolicyDecision(
            action="pending_choice",
            selected_candidate_id=None,
            candidate_options=("candidate_a",),
            reason="choisis",
            user_facing_reason="choisis",
            requires_confirmation_reason="choisis",
            risk_level="medium",
        ),
        selected_patch=None,
        evaluated_candidates=(evaluated,),
        command_result=None,
        pending_confirmation_id=None,
    )
    existing = SimpleNamespace(
        id=78,
        status="pending",
        mutation_type="plan_patch_choice",
        decision_json=serialize_plan_patch_choice_confirmation((_candidate_with_patch(candidate, patch),)),
    )

    def fake_create_pending_mutation_confirmation(db, **kwargs):
        pending_rows.append(kwargs)
        return SimpleNamespace(id=100)

    monkeypatch.setattr(
        "fitmas.domain.planning.mutation_service.repo.get_active_pending_mutation_confirmation",
        lambda db, user_id: existing,
    )
    monkeypatch.setattr(
        "fitmas.domain.planning.mutation_service.repo.create_pending_mutation_confirmation",
        fake_create_pending_mutation_confirmation,
    )

    result = PlanningCommandService(db=object(), user=SimpleNamespace(id=1)).apply(
        decision,
        source_text="choix",
        coach_state_bundle=None,
        activities=(),
        active_facts=(),
    )

    assert result.status == "pending"
    assert result.pending_confirmation_id == 78
    assert pending_rows == []
    assert result.payload["reused_pending_confirmation"] is True


def _candidate_with_patch(candidate: PlanPatchCandidate, patch: PlanPatch) -> PlanPatchCandidate:
    return PlanPatchCandidate(
        id=candidate.id,
        patches=(patch,),
        rationale=candidate.rationale,
        expected_tradeoff=candidate.expected_tradeoff,
        confidence=candidate.confidence,
        assumptions=candidate.assumptions,
        risk_notes=candidate.risk_notes,
        created_from_plan_id=candidate.created_from_plan_id,
        created_from_plan_version=candidate.created_from_plan_version,
        candidate_ref=None,
    )
