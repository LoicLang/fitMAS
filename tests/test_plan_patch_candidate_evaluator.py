from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from fitmas.plan_patch import PlanPatch, PlanPatchOperation
from fitmas.plan_patch_candidate_evaluator import evaluate_plan_patch_candidate
from fitmas.plan_patch_candidates import PlanPatchCandidate
from fitmas.week_coherence import WeekCoherenceScore


def test_candidate_evaluator_validates_simulates_scores_and_returns_score_delta() -> None:
    candidate = _candidate(
        patches=(
            PlanPatch(
                operations=[
                    PlanPatchOperation(
                        operation_type="move_session",
                        target_session_id=2,
                        target_date="2099-05-08",
                        rationale="Deplacer la recuperation plus tard.",
                    )
                ],
                coach_message="Candidate only.",
            ),
        )
    )

    result = evaluate_plan_patch_candidate(
        object(),
        candidate=candidate,
        current_plan_id="123",
        current_plan_version=7,
        plan_id=123,
        scheduled_sessions=[
            _session(1, "2099-05-04", "running", "tempo", "hard", 50, "Seance cle"),
            _session(2, "2099-05-05", "rest", "recovery", "easy", 0, "Recovery"),
        ],
        current_score=_score(90),
        timezone_name="Europe/Paris",
    )

    assert result.candidate_validation.status == "valid"
    assert result.patch is not None
    assert len(result.patch.operations) == 1
    assert result.patch_validation is not None
    assert result.patch_validation.status == "valid"
    assert result.facts is not None
    assert result.facts.recovery_after_hard_after == 0
    assert result.score is not None
    assert result.score_delta is not None
    assert result.score_delta < 0
    assert any(finding.code == "RECOVERY_AFTER_HARD_LOST" for finding in result.findings)
    assert result.policy_hint == "ask_confirmation"


def test_candidate_evaluator_blocks_stale_candidate_before_patch_validation() -> None:
    result = evaluate_plan_patch_candidate(
        object(),
        candidate=_candidate(created_from_plan_version=6),
        current_plan_id="123",
        current_plan_version=7,
        plan_id=123,
        scheduled_sessions=[],
        current_score=_score(90),
        timezone_name="Europe/Paris",
    )

    assert result.candidate_validation.status == "blocked"
    assert result.candidate_validation.block_reason == "stale_plan_version"
    assert result.patch is None
    assert result.patch_validation is None
    assert result.policy_hint == "block"


def test_candidate_evaluator_blocks_runtime_invalid_patch_contract() -> None:
    candidate = _candidate(
        patches=(
            PlanPatch(
                operations=[
                    PlanPatchOperation(
                        operation_type="move_session",
                        target_session_id=999,
                        target_date="2099-05-08",
                        rationale="Cible inexistante.",
                    )
                ],
                coach_message="Candidate only.",
            ),
        )
    )

    result = evaluate_plan_patch_candidate(
        object(),
        candidate=candidate,
        current_plan_id="123",
        current_plan_version=7,
        plan_id=123,
        scheduled_sessions=[
            _session(1, "2099-05-04", "running", "tempo", "hard", 50, "Seance cle"),
        ],
        current_score=_score(90),
        timezone_name="Europe/Paris",
    )

    assert result.candidate_validation.status == "valid"
    assert result.patch_validation is not None
    assert result.patch_validation.status == "blocked"
    assert result.patch_validation.operation_results[0].block_reason == "target_session_not_found"
    assert result.policy_hint == "block"


def _candidate(
    *,
    patches: tuple[PlanPatch, ...] | None = None,
    created_from_plan_version: int = 7,
) -> PlanPatchCandidate:
    if patches is None:
        patches = (
            PlanPatch(
                operations=[
                    PlanPatchOperation(
                        operation_type="move_session",
                        target_session_id=1,
                        target_date="2099-05-08",
                        rationale="Move.",
                    )
                ],
                coach_message="Candidate only.",
            ),
        )
    return PlanPatchCandidate(
        id="candidate_1",
        patches=patches,
        rationale="Option candidate.",
        expected_tradeoff="Tradeoff a mesurer.",
        confidence=0.8,
        assumptions=(),
        risk_notes=(),
        created_from_plan_id="123",
        created_from_plan_version=created_from_plan_version,
    )


def _session(
    session_id: int,
    scheduled_date: str,
    sport_type: str,
    session_type: str,
    intensity: str,
    duration_min: int,
    priority: str,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=session_id,
        scheduled_date=datetime.fromisoformat(scheduled_date),
        sport_type=sport_type,
        session_type=session_type,
        session_title=f"{sport_type} {session_type}",
        duration_min=duration_min,
        intensity=intensity,
        load_score=3 if intensity == "hard" else 1,
        priority=priority,
        completion_status="planned",
    )


def _score(total: float) -> WeekCoherenceScore:
    return WeekCoherenceScore(
        total=total,
        recovery=90,
        goal_alignment=90,
        progression=90,
        adherence=90,
        readiness_fit=90,
        constraint_fit=90,
        risk=90,
    )
