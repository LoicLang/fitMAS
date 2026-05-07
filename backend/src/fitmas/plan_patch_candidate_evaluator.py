from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Sequence

from sqlalchemy.orm import Session

from fitmas.plan_patch import PlanPatch, PlanPatchValidation, validate_plan_patch
from fitmas.plan_patch_candidates import (
    PlanPatchCandidate,
    PlanPatchCandidateValidation,
    validate_plan_patch_candidate_contract,
)
from fitmas.week_coherence import (
    CoherenceFinding,
    WeekCoherenceContext,
    WeekCoherenceScore,
    WeekFacts,
    build_week_coherence_context,
)

PolicyHint = Literal["commit_safe", "ask_confirmation", "block"]


@dataclass(frozen=True, slots=True)
class EvaluatedPlanPatchCandidate:
    candidate: PlanPatchCandidate
    candidate_validation: PlanPatchCandidateValidation
    patch: PlanPatch | None
    patch_validation: PlanPatchValidation | None
    week_context: WeekCoherenceContext | None
    facts: WeekFacts | None
    score: WeekCoherenceScore | None
    findings: tuple[CoherenceFinding, ...]
    score_delta: float | None
    policy_hint: PolicyHint
    evaluation_summary: str


def evaluate_plan_patch_candidate(
    db: Session,
    *,
    candidate: PlanPatchCandidate,
    current_plan_id: str,
    current_plan_version: int,
    plan_id: int,
    scheduled_sessions: Sequence[Any],
    current_score: WeekCoherenceScore | None,
    timezone_name: str | None = None,
    allowed_operations: Sequence[str] | None = None,
    coach_state_bundle: Any | None = None,
    activities: Sequence[Any] = (),
    active_facts: Sequence[Any] = (),
) -> EvaluatedPlanPatchCandidate:
    candidate_validation = validate_plan_patch_candidate_contract(
        candidate,
        current_plan_id=current_plan_id,
        current_plan_version=current_plan_version,
        allowed_operations=allowed_operations,
    )
    if candidate_validation.status == "blocked":
        return _blocked_evaluation(
            candidate=candidate,
            candidate_validation=candidate_validation,
            summary=candidate_validation.summary,
        )

    patch = _combine_candidate_patches(candidate)
    patch_validation = validate_plan_patch(
        db,
        plan_id=plan_id,
        patch=patch,
        scheduled_sessions=scheduled_sessions,
        timezone_name=timezone_name,
    )
    if patch_validation.status == "blocked":
        return EvaluatedPlanPatchCandidate(
            candidate=candidate,
            candidate_validation=candidate_validation,
            patch=patch,
            patch_validation=patch_validation,
            week_context=None,
            facts=None,
            score=None,
            findings=(),
            score_delta=None,
            policy_hint="block",
            evaluation_summary=patch_validation.summary,
        )

    week_context = build_week_coherence_context(
        patch=patch,
        validation=patch_validation,
        scheduled_sessions=scheduled_sessions,
        coach_state_bundle=coach_state_bundle,
        activities=activities,
        active_facts=active_facts,
        timezone_name=timezone_name,
    )
    score = week_context.score
    score_delta = None
    if score is not None and current_score is not None:
        score_delta = round(score.total - current_score.total, 1)
    policy_hint = _policy_hint(
        patch_validation=patch_validation,
        score=score,
        score_delta=score_delta,
        findings=week_context.coherence_findings,
    )
    return EvaluatedPlanPatchCandidate(
        candidate=candidate,
        candidate_validation=candidate_validation,
        patch=patch,
        patch_validation=patch_validation,
        week_context=week_context,
        facts=week_context.facts,
        score=score,
        findings=week_context.coherence_findings,
        score_delta=score_delta,
        policy_hint=policy_hint,
        evaluation_summary=_evaluation_summary(policy_hint=policy_hint, score_delta=score_delta),
    )


def _combine_candidate_patches(candidate: PlanPatchCandidate) -> PlanPatch:
    operations = []
    for patch in candidate.patches:
        operations.extend(patch.operations)
    return PlanPatch(
        operations=operations,
        coach_message=candidate.rationale or "Candidate PlanPatch.",
        confirmation_reason=candidate.expected_tradeoff or None,
    )


def _policy_hint(
    *,
    patch_validation: PlanPatchValidation,
    score: WeekCoherenceScore | None,
    score_delta: float | None,
    findings: tuple[CoherenceFinding, ...],
) -> PolicyHint:
    if patch_validation.status == "blocked":
        return "block"
    if patch_validation.status in {"warning", "requires_confirmation"}:
        return "ask_confirmation"
    if any(finding.severity in {"risk", "blocker"} for finding in findings):
        return "ask_confirmation"
    if any(finding.severity == "warning" for finding in findings):
        return "ask_confirmation"
    if score_delta is not None and score_delta <= -15:
        return "ask_confirmation"
    if score is not None and score.total < 70:
        return "ask_confirmation"
    return "commit_safe"


def _evaluation_summary(*, policy_hint: PolicyHint, score_delta: float | None) -> str:
    if policy_hint == "block":
        return "Candidate bloquee avant application."
    if policy_hint == "ask_confirmation":
        if score_delta is not None:
            return f"Candidate possible, confirmation recommandee (score_delta={score_delta})."
        return "Candidate possible, confirmation recommandee."
    if score_delta is not None:
        return f"Candidate basse friction (score_delta={score_delta})."
    return "Candidate basse friction."


def _blocked_evaluation(
    *,
    candidate: PlanPatchCandidate,
    candidate_validation: PlanPatchCandidateValidation,
    summary: str,
) -> EvaluatedPlanPatchCandidate:
    return EvaluatedPlanPatchCandidate(
        candidate=candidate,
        candidate_validation=candidate_validation,
        patch=None,
        patch_validation=None,
        week_context=None,
        facts=None,
        score=None,
        findings=(),
        score_delta=None,
        policy_hint="block",
        evaluation_summary=summary,
    )
