from __future__ import annotations

from fitmas.domain.planning.plan_patch import PlanPatch, PlanPatchOperation, PlanPatchValidation
from fitmas.domain.planning.policy import decide_adaptation_policy
from fitmas.domain.planning.evaluator import EvaluatedPlanPatchCandidate
from fitmas.domain.planning.reviewer import PlanPatchCandidateReviewDecision
from fitmas.domain.planning.candidates import PlanPatchCandidate, PlanPatchCandidateValidation
from fitmas.domain.planning.week_coherence import CoherenceFinding, WeekCoherenceScore


def test_policy_blocks_when_no_candidate_is_usable() -> None:
    decision = decide_adaptation_policy(
        [
            _evaluated(
                "blocked_candidate",
                candidate_status="blocked",
                score_total=None,
                policy_hint="block",
            )
        ]
    )

    assert decision.action == "block"
    assert decision.selected_candidate_id is None
    assert decision.candidate_options == ()
    assert decision.risk_level == "high"
    assert decision.committed_events == ()
    assert decision.pending_event is None


def test_policy_commits_clear_single_low_risk_candidate() -> None:
    decision = decide_adaptation_policy(
        [
            _evaluated(
                "safe_move",
                score_total=88,
                score_delta=2,
                policy_hint="commit_safe",
            )
        ]
    )

    assert decision.action == "commit"
    assert decision.selected_candidate_id == "safe_move"
    assert decision.candidate_options == ()
    assert decision.risk_level == "low"
    assert decision.committed_events == ()
    assert decision.pending_event is None


def test_policy_requires_confirmation_for_medium_risk_candidate() -> None:
    decision = decide_adaptation_policy(
        [
            _evaluated(
                "possible_but_sensitive",
                score_total=76,
                score_delta=-9,
                policy_hint="ask_confirmation",
                findings=(
                    CoherenceFinding(
                        code="RECOVERY_AFTER_HARD_LOST",
                        severity="warning",
                        message="Recuperation degradee.",
                        evidence={"score_delta": -9},
                    ),
                ),
            )
        ]
    )

    assert decision.action == "pending_confirmation"
    assert decision.selected_candidate_id == "possible_but_sensitive"
    assert decision.candidate_options == ()
    assert decision.risk_level == "medium"
    assert decision.requires_confirmation_reason
    assert decision.pending_event == {
        "candidate_id": "possible_but_sensitive",
        "reason": decision.requires_confirmation_reason,
        "risk_level": "medium",
    }


def test_policy_asks_choice_when_top_candidates_are_close() -> None:
    decision = decide_adaptation_policy(
        [
            _evaluated("move_to_friday", score_total=84, score_delta=-2),
            _evaluated("reduce_tomorrow", score_total=82, score_delta=-4),
        ]
    )

    assert decision.action == "pending_choice"
    assert decision.selected_candidate_id is None
    assert decision.candidate_options == ("move_to_friday", "reduce_tomorrow")
    assert decision.risk_level == "medium"
    assert decision.pending_event == {
        "candidate_ids": ("move_to_friday", "reduce_tomorrow"),
        "reason": decision.requires_confirmation_reason,
        "risk_level": "medium",
    }


def test_policy_uses_reviewer_choice_when_candidates_are_close() -> None:
    decision = decide_adaptation_policy(
        [
            _evaluated("move_to_friday", score_total=84, score_delta=-2),
            _evaluated("reduce_tomorrow", score_total=82, score_delta=-4),
        ],
        reviewer_decision=PlanPatchCandidateReviewDecision(
            preferred_candidate_id="reduce_tomorrow",
            confidence=0.78,
            rationale=("Meilleur compromis humain.",),
        ),
    )

    assert decision.action == "commit"
    assert decision.selected_candidate_id == "reduce_tomorrow"
    assert decision.reason == "Option choisie par reviewer borne."


def test_policy_ignores_reviewer_choice_when_score_gap_is_too_large() -> None:
    decision = decide_adaptation_policy(
        [
            _evaluated("clear_best", score_total=91, score_delta=1),
            _evaluated("too_low", score_total=70, score_delta=-20),
        ],
        reviewer_decision=PlanPatchCandidateReviewDecision(
            preferred_candidate_id="too_low",
            confidence=0.9,
            rationale=("Humainement tentant, mais trop degrade.",),
        ),
    )

    assert decision.action == "commit"
    assert decision.selected_candidate_id == "clear_best"


def test_policy_selects_clear_best_when_candidates_are_not_close() -> None:
    decision = decide_adaptation_policy(
        [
            _evaluated("lower_score", score_total=72, score_delta=-10),
            _evaluated("clear_best", score_total=91, score_delta=1),
        ]
    )

    assert decision.action == "commit"
    assert decision.selected_candidate_id == "clear_best"
    assert decision.candidate_options == ()
    assert decision.risk_level == "low"


def _evaluated(
    candidate_id: str,
    *,
    candidate_status: str = "valid",
    score_total: float | None,
    score_delta: float | None = 0,
    policy_hint: str = "commit_safe",
    findings: tuple[CoherenceFinding, ...] = (),
) -> EvaluatedPlanPatchCandidate:
    candidate = PlanPatchCandidate(
        id=candidate_id,
        patches=(
            PlanPatch(
                operations=[
                    PlanPatchOperation(
                        operation_type="move_session",
                        target_session_id=42,
                        target_date="2099-05-08",
                        rationale="Move.",
                    )
                ],
                coach_message="Candidate only.",
            ),
        ),
        rationale=f"Rationale {candidate_id}.",
        expected_tradeoff="Tradeoff.",
        confidence=0.8,
        assumptions=(),
        risk_notes=(),
        created_from_plan_id="plan_123",
        created_from_plan_version=7,
    )
    candidate_validation = PlanPatchCandidateValidation(
        status=candidate_status,  # type: ignore[arg-type]
        patch_count=1,
        operation_count=1,
        operation_results=(),
        block_reason="blocked_for_test" if candidate_status == "blocked" else None,
        summary="Candidate validation.",
    )
    score = _score(score_total) if score_total is not None else None
    return EvaluatedPlanPatchCandidate(
        candidate=candidate,
        candidate_validation=candidate_validation,
        patch=candidate.patches[0],
        patch_validation=PlanPatchValidation(
            status="valid",
            operation_results=(),
            summary="valid",
        ),
        week_context=None,
        facts=None,
        score=score,
        findings=findings,
        score_delta=score_delta if score is not None else None,
        policy_hint=policy_hint,  # type: ignore[arg-type]
        evaluation_summary="Evaluation.",
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
