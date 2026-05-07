from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from fitmas.plan_patch import PlanPatch, PlanPatchOperation, PlanPatchValidation
from fitmas.week_coherence import (
    DeterministicWeekChecks,
    WeekCoherenceContext,
    WeekCoherenceFinding,
    WeekCoherenceReview,
    aggregate_week_coherence_policy,
    evaluate_week_invariants,
    review_week_coherence_with_llm,
    simulate_plan_patch,
)


def test_simulate_plan_patch_moves_session_without_mutating_original() -> None:
    original_date = datetime(2026, 5, 6, 8, 0)
    session = _session(
        session_id=42,
        scheduled_date=original_date,
        sport_type="running",
        session_type="tempo",
        intensity="hard",
        duration_min=50,
        priority="Seance cle",
    )
    patch = PlanPatch(
        operations=[
            PlanPatchOperation(
                operation_type="move_session",
                target_session_id=42,
                target_date="2026-05-09",
                rationale="Indispo mercredi.",
            )
        ],
        coach_message="Je deplace mercredi a samedi.",
    )

    before, after, diff = simulate_plan_patch([session], patch, timezone_name="Europe/Paris")

    assert session.scheduled_date == original_date
    assert before.sessions[0]["scheduled_date"] == "2026-05-06"
    assert after.sessions[0]["scheduled_date"] == "2026-05-09"
    assert diff.changed_sessions[0]["id"] == 42
    assert diff.changed_sessions[0]["before"]["scheduled_date"] == "2026-05-06"
    assert diff.changed_sessions[0]["after"]["scheduled_date"] == "2026-05-09"


def test_simulate_plan_patch_replaces_session_fields() -> None:
    session = _session(
        session_id=12,
        scheduled_date=datetime(2026, 5, 7, 8, 0),
        sport_type="swimming",
        session_type="css",
        intensity="hard",
        duration_min=45,
        priority="Seance cle",
    )
    patch = PlanPatch(
        operations=[
            PlanPatchOperation(
                operation_type="replace_session",
                target_session_id=12,
                new_sport_type="running",
                new_session_type="easy",
                new_title="Running relais",
                new_goal="Remplacer la piscine sans casser la semaine",
                new_duration_min=40,
                new_intensity="easy",
                new_description="40 min facile.",
                rationale="Piscine fermee.",
            )
        ],
        coach_message="Je remplace par un running facile.",
    )

    _, after, diff = simulate_plan_patch([session], patch, timezone_name="Europe/Paris")

    assert after.sessions[0]["sport_type"] == "running"
    assert after.sessions[0]["session_type"] == "easy"
    assert after.sessions[0]["session_title"] == "Running relais"
    assert after.sessions[0]["session_goal"] == "Remplacer la piscine sans casser la semaine"
    assert after.sessions[0]["duration_min"] == 40
    assert after.sessions[0]["intensity"] == "easy"
    assert after.sessions[0]["session_description"] == "40 min facile."
    assert diff.changed_sessions[0]["before"]["sport_type"] == "swimming"
    assert diff.changed_sessions[0]["after"]["sport_type"] == "running"


def test_evaluate_week_invariants_detects_key_touch_recovery_delta_and_hard_gap() -> None:
    sessions = [
        _session(1, datetime(2026, 5, 4, 8, 0), "running", "tempo", "hard", 55, "Seance cle"),
        _session(2, datetime(2026, 5, 5, 8, 0), "rest", "recovery", "easy", 0, "Recovery"),
        _session(3, datetime(2026, 5, 7, 8, 0), "cycling", "intervals", "hard", 70, "Seance cle"),
    ]
    patch = PlanPatch(
        operations=[
            PlanPatchOperation(
                operation_type="replace_session",
                target_session_id=2,
                new_sport_type="strength",
                new_session_type="strength",
                new_title="Renfo relais",
                new_duration_min=35,
                new_intensity="easy",
                rationale="Ajouter du support.",
            ),
            PlanPatchOperation(
                operation_type="move_session",
                target_session_id=3,
                target_date="2026-05-05",
                rationale="Tasser la qualite.",
            ),
        ],
        coach_message="Je modifie la semaine.",
    )
    before, after, diff = simulate_plan_patch(sessions, patch, timezone_name="Europe/Paris")
    context = WeekCoherenceContext(
        patch=patch,
        validation=PlanPatchValidation(status="valid", operation_results=()),
        before_week=before,
        after_week=after,
        diff=diff,
        deterministic_checks=_empty_checks(),
        planning_contract=None,
        week_mission=None,
        session_policies=(),
        recent_reality=None,
        active_constraints=(),
    )

    checks = evaluate_week_invariants(context)

    assert checks.hard_sessions_before == 2
    assert checks.hard_sessions_after == 2
    assert checks.min_hard_gap_hours_after == 24
    assert checks.recovery_sessions_before == 1
    assert checks.recovery_sessions_after == 0
    assert checks.key_session_ids_touched == (3,)
    assert checks.weekly_duration_delta_min == 35
    assert "recovery_session_lost" in checks.flags
    assert "hard_sessions_too_close" in checks.flags


def test_evaluate_week_invariants_detects_recovery_after_hard_lost_even_if_recovery_count_is_preserved() -> None:
    sessions = [
        _session(1, datetime(2026, 5, 4, 8, 0), "running", "tempo", "hard", 50, "Seance cle"),
        _session(2, datetime(2026, 5, 5, 8, 0), "rest", "recovery", "easy", 0, "Recovery"),
        _session(3, datetime(2026, 5, 7, 8, 0), "running", "easy", "easy", 40, "Support"),
    ]
    patch = PlanPatch(
        operations=[
            PlanPatchOperation(
                operation_type="move_session",
                target_session_id=2,
                target_date="2026-05-08",
                rationale="Deplacer le repos plus tard.",
            )
        ],
        coach_message="Je deplace la recuperation.",
    )
    before, after, diff = simulate_plan_patch(sessions, patch, timezone_name="Europe/Paris")
    context = WeekCoherenceContext(
        patch=patch,
        validation=PlanPatchValidation(status="valid", operation_results=()),
        before_week=before,
        after_week=after,
        diff=diff,
        deterministic_checks=_empty_checks(),
        planning_contract=None,
        week_mission=None,
        session_policies=(),
        recent_reality=None,
        active_constraints=(),
    )

    checks = evaluate_week_invariants(context)

    assert checks.recovery_sessions_before == checks.recovery_sessions_after
    assert checks.recovery_after_hard_preserved is False
    assert "recovery_after_hard_lost" in checks.flags


def test_aggregate_week_coherence_policy_preserves_hard_block_and_reviewer_friction() -> None:
    valid = PlanPatchValidation(status="valid", operation_results=())
    blocked = PlanPatchValidation(status="blocked", operation_results=())
    checks = _empty_checks()

    assert aggregate_week_coherence_policy(
        patch_validation=blocked,
        week_review=_review("valid", "commit_original"),
        deterministic_checks=checks,
        allow_requires_confirmation=True,
    ) == "blocked"
    assert aggregate_week_coherence_policy(
        patch_validation=valid,
        week_review=_review("requires_confirmation", "confirm_original"),
        deterministic_checks=checks,
        allow_requires_confirmation=False,
    ) == "requires_confirmation"
    assert aggregate_week_coherence_policy(
        patch_validation=valid,
        week_review=_review("blocked", "block_original"),
        deterministic_checks=checks,
        allow_requires_confirmation=True,
    ) == "blocked"
    assert aggregate_week_coherence_policy(
        patch_validation=valid,
        week_review=None,
        deterministic_checks=checks,
        allow_requires_confirmation=False,
    ) == "valid"


def test_review_week_coherence_with_llm_accepts_typed_json() -> None:
    context = _basic_context()

    def _request_json(**kwargs):
        return {
            "status": "valid",
            "sport_quality": "good",
            "confidence": 0.91,
            "summary": "La semaine reste propre.",
            "findings": [
                {
                    "code": "mission_preserved",
                    "severity": "info",
                    "detail": "La seance cle reste lisible.",
                    "target_session_ids": [42],
                }
            ],
            "suggested_adjustments": [],
            "recommended_policy": "commit_original",
        }

    review = review_week_coherence_with_llm(context, request_json_fn=_request_json)

    assert review.status == "valid"
    assert review.sport_quality == "good"
    assert review.confidence == 0.91
    assert review.recommended_policy == "commit_original"
    assert review.findings[0].code == "mission_preserved"
    assert review.findings[0].target_session_ids == (42,)


def test_review_week_coherence_with_llm_falls_back_on_invalid_json() -> None:
    context = _basic_context(flags=("hard_sessions_too_close",))

    def _request_json(**kwargs):
        return {
            "status": "commit",
            "sport_quality": "excellent",
            "confidence": "high",
            "summary": "",
            "findings": [],
            "recommended_policy": "ship_it",
        }

    review = review_week_coherence_with_llm(context, request_json_fn=_request_json)

    assert review.status == "requires_confirmation"
    assert review.sport_quality == "fragile"
    assert review.recommended_policy == "confirm_original"
    assert any(finding.code == "reviewer_invalid_response" for finding in review.findings)
    assert any(finding.code == "hard_sessions_too_close" for finding in review.findings)


def test_review_week_coherence_without_llm_fallback_respects_validation_warning() -> None:
    context = _basic_context(validation_status="requires_confirmation")

    review = review_week_coherence_with_llm(context, request_json_fn=None)

    assert review.status == "requires_confirmation"
    assert review.recommended_policy == "confirm_original"
    assert any(finding.code == "runtime_validation_requires_confirmation" for finding in review.findings)


def _session(
    session_id: int,
    scheduled_date: datetime,
    sport_type: str,
    session_type: str,
    intensity: str,
    duration_min: int,
    priority: str,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=session_id,
        user_id=1,
        day=scheduled_date.strftime("%A").lower(),
        label=scheduled_date.strftime("%a"),
        scheduled_date=scheduled_date,
        sport_type=sport_type,
        session_type=session_type,
        session_title=f"{sport_type} {session_type}",
        session_goal="Stimulus utile.",
        session_note="",
        session_description="Description.",
        duration_min=duration_min,
        intensity=intensity,
        load_score=3 if intensity == "hard" else 1,
        priority=priority,
        nutrition_focus="",
        flexibility="stable",
        completion_status="planned",
    )


def _empty_checks() -> DeterministicWeekChecks:
    return DeterministicWeekChecks(
        hard_sessions_before=0,
        hard_sessions_after=0,
        min_hard_gap_hours_after=None,
        recovery_sessions_before=0,
        recovery_sessions_after=0,
        recovery_after_hard_preserved=True,
        key_session_ids_touched=(),
        completed_session_ids_touched=(),
        weekly_duration_delta_min=0,
        estimated_tss_delta=None,
        change_budget_remaining_before=None,
        change_budget_remaining_after=None,
        flags=(),
    )


def _basic_context(
    *,
    flags: tuple[str, ...] = (),
    validation_status: str = "valid",
) -> WeekCoherenceContext:
    patch = PlanPatch(
        operations=[
            PlanPatchOperation(
                operation_type="move_session",
                target_session_id=42,
                target_date="2026-05-08",
                rationale="Indispo.",
            )
        ],
        coach_message="Je deplace.",
    )
    checks = DeterministicWeekChecks(
        hard_sessions_before=1,
        hard_sessions_after=1,
        min_hard_gap_hours_after=None,
        recovery_sessions_before=1,
        recovery_sessions_after=1,
        recovery_after_hard_preserved=True,
        key_session_ids_touched=(),
        completed_session_ids_touched=(),
        weekly_duration_delta_min=0,
        estimated_tss_delta=0.0,
        change_budget_remaining_before=None,
        change_budget_remaining_after=None,
        flags=flags,
    )
    snapshot = SimpleNamespace(week_start=None, sessions=())
    return WeekCoherenceContext(
        patch=patch,
        validation=PlanPatchValidation(status=validation_status, operation_results=()),
        before_week=snapshot,
        after_week=snapshot,
        diff=SimpleNamespace(changed_sessions=(), created_sessions=(), removed_or_lightened_sessions=()),
        deterministic_checks=checks,
        planning_contract=None,
        week_mission=None,
        session_policies=(),
        recent_reality=None,
        active_constraints=(),
    )


def _review(status: str, recommended_policy: str) -> WeekCoherenceReview:
    return WeekCoherenceReview(
        status=status,
        sport_quality="acceptable",
        confidence=0.8,
        summary="review",
        findings=(
            WeekCoherenceFinding(
                code="patch_sportively_good",
                severity="info",
                detail="OK.",
            ),
        ),
        suggested_adjustments=(),
        recommended_policy=recommended_policy,
    )
