from __future__ import annotations

from types import SimpleNamespace

from fitmas.decision import RequestedPlanChange
from fitmas.domain.planning.decision_service import decide_plan_change
from fitmas.plan_patch import PlanPatchValidation
from fitmas.domain.planning.evaluator import EvaluatedPlanPatchCandidate
from fitmas.domain.planning.candidates import PlanPatchCandidateValidation
from fitmas.week_coherence import WeekCoherenceScore


def _context():
    return SimpleNamespace(
        local_time=SimpleNamespace(today_iso="2026-05-14"),
        plan=SimpleNamespace(
            scheduled_sessions=(
                SimpleNamespace(id=42, scheduled_date="2026-05-14", duration_min=45, completion_status=None),
            )
        ),
        execution=SimpleNamespace(activities=()),
        memory=SimpleNamespace(active_facts=()),
    )


def _swap_context():
    return SimpleNamespace(
        local_time=SimpleNamespace(today_iso="2026-05-17"),
        plan=SimpleNamespace(
            scheduled_sessions=(
                SimpleNamespace(id=1, scheduled_date="2026-05-20", duration_min=65, completion_status=None),
                SimpleNamespace(id=2, scheduled_date="2026-05-21", duration_min=95, completion_status=None),
            )
        ),
        execution=SimpleNamespace(activities=()),
        memory=SimpleNamespace(active_facts=()),
    )


def _hard_dense_context():
    return SimpleNamespace(
        local_time=SimpleNamespace(today_iso="2026-05-19"),
        plan=SimpleNamespace(
            scheduled_sessions=(
                SimpleNamespace(
                    id=1,
                    scheduled_date="2026-05-20",
                    sport_type="running",
                    session_type="threshold",
                    intensity="hard",
                    duration_min=65,
                    completion_status=None,
                    flexibility="stable",
                ),
                SimpleNamespace(
                    id=2,
                    scheduled_date="2026-05-21",
                    sport_type="running",
                    session_type="long",
                    intensity="hard",
                    duration_min=95,
                    completion_status=None,
                    flexibility="stable",
                ),
                SimpleNamespace(
                    id=3,
                    scheduled_date="2026-05-22",
                    sport_type="strength",
                    session_type="recovery",
                    intensity="easy",
                    duration_min=30,
                    completion_status=None,
                    flexibility="flexible",
                ),
            )
        ),
        execution=SimpleNamespace(activities=()),
        memory=SimpleNamespace(active_facts=()),
    )


def _window_context():
    return SimpleNamespace(
        local_time=SimpleNamespace(today_iso="2026-05-19"),
        plan=SimpleNamespace(
            scheduled_sessions=(
                SimpleNamespace(
                    id=1,
                    scheduled_date="2026-05-20",
                    sport_type="swimming",
                    session_type="easy",
                    session_title="Natation hotel",
                    duration_min=35,
                    completion_status=None,
                    flexibility="stable",
                ),
                SimpleNamespace(
                    id=2,
                    scheduled_date="2026-05-22",
                    sport_type="strength",
                    session_type="general",
                    session_title="Renfo hotel",
                    duration_min=30,
                    completion_status=None,
                    flexibility="stable",
                ),
                SimpleNamespace(
                    id=3,
                    scheduled_date="2026-05-24",
                    sport_type="running",
                    session_type="easy",
                    session_title="Footing retour",
                    duration_min=45,
                    completion_status=None,
                    flexibility="stable",
                ),
            )
        ),
        execution=SimpleNamespace(activities=()),
        memory=SimpleNamespace(active_facts=()),
    )


def test_decide_plan_change_blocks_unresolved_change() -> None:
    requested = RequestedPlanChange(
        kind="move",
        source_ref="seance dure",
        target_ref="vendredi",
        desired_sport=None,
        desired_duration_min=None,
        desired_intensity=None,
        reason="fatigue",
        risk_signals=(),
    )

    result = decide_plan_change(
        requested,
        context=_context(),
        db=object(),
        user=SimpleNamespace(id=1, timezone="Europe/Paris"),
        coach_state_bundle=None,
        reviewer_request_json_fn=None,
    )

    assert result.kind == "block"
    assert result.reason == "Je ne trouve pas la seance cible a modifier. Je ne touche pas au plan."


def test_decide_plan_change_blocks_empty_date_ref_with_user_safe_reason() -> None:
    requested = RequestedPlanChange(
        kind="lighten",
        source_ref="date:2026-05-15",
        target_ref=None,
        desired_sport=None,
        desired_duration_min=None,
        desired_intensity=None,
        reason="fatigue",
        risk_signals=(),
    )

    result = decide_plan_change(
        requested,
        context=_context(),
        db=object(),
        user=SimpleNamespace(id=1, timezone="Europe/Paris"),
        coach_state_bundle=None,
        reviewer_request_json_fn=None,
    )

    assert result.kind == "block"
    assert result.reason == "Je ne trouve pas de seance planifiee le 2026-05-15. Je ne touche pas au plan."
    assert "unresolved" not in result.reason


def test_decide_plan_change_builds_and_policies_resolved_change(monkeypatch) -> None:
    calls = []

    class FakeEvaluator:
        def __init__(self, *, db, user):
            pass

        def evaluate(self, candidate_set, **kwargs):
            calls.append(candidate_set)
            return ()

    monkeypatch.setattr("fitmas.domain.planning.decision_service.PlanCandidateEvaluator", FakeEvaluator)

    requested = RequestedPlanChange(
        kind="move",
        source_ref="session_id:42",
        target_ref="date:2026-05-15",
        desired_sport=None,
        desired_duration_min=None,
        desired_intensity=None,
        reason="fatigue",
        risk_signals=(),
    )

    result = decide_plan_change(
        requested,
        context=_context(),
        db=object(),
        user=SimpleNamespace(id=1, timezone="Europe/Paris"),
        coach_state_bundle=None,
        reviewer_request_json_fn=None,
    )

    assert calls
    assert result.kind == "block"
    assert result.reason == "Aucune option d'adaptation valide."


def test_decide_plan_change_blocks_hard_create_on_dense_day_before_evaluator(monkeypatch) -> None:
    class FailingEvaluator:
        def __init__(self, *, db, user):
            pass

        def evaluate(self, candidate_set, **kwargs):
            raise AssertionError("dense hard create should be blocked before candidate evaluation")

    monkeypatch.setattr("fitmas.domain.planning.decision_service.PlanCandidateEvaluator", FailingEvaluator)
    requested = RequestedPlanChange(
        kind="create",
        source_ref=None,
        target_ref="date:2026-05-20",
        desired_sport="running",
        desired_duration_min=None,
        desired_intensity="hard",
        reason="add hard session",
        risk_signals=("load",),
    )

    result = decide_plan_change(
        requested,
        context=_hard_dense_context(),
        db=object(),
        user=SimpleNamespace(id=1, timezone="Europe/Paris"),
        coach_state_bundle=None,
        reviewer_request_json_fn=None,
    )

    assert result.kind == "block"
    assert result.reason == (
        "Je ne rajoute pas de seance dure le 2026-05-20: la semaine a deja une charge intense trop proche. "
        "Je ne touche pas au plan."
    )
    assert result.selected_candidate_id is None


def test_decide_plan_change_blocks_hard_create_without_inferred_sport(monkeypatch) -> None:
    class FailingEvaluator:
        def __init__(self, *, db, user):
            pass

        def evaluate(self, candidate_set, **kwargs):
            raise AssertionError("hard create without sport should not infer a candidate")

    monkeypatch.setattr("fitmas.domain.planning.decision_service.PlanCandidateEvaluator", FailingEvaluator)
    requested = RequestedPlanChange(
        kind="create",
        source_ref=None,
        target_ref="date:2026-05-20",
        desired_sport=None,
        desired_duration_min=None,
        desired_intensity="hard",
        reason="add hard session",
        risk_signals=("load",),
    )

    result = decide_plan_change(
        requested,
        context=_hard_dense_context(),
        db=object(),
        user=SimpleNamespace(id=1, timezone="Europe/Paris"),
        coach_state_bundle=None,
        reviewer_request_json_fn=None,
    )

    assert result.kind == "block"
    assert result.reason == (
        "Je ne rajoute pas de seance dure le 2026-05-20: la semaine a deja une charge intense trop proche. "
        "Je ne touche pas au plan."
    )
    assert result.selected_candidate_id is None


def test_decide_plan_change_treats_high_create_intensity_as_hard(monkeypatch) -> None:
    class FailingEvaluator:
        def __init__(self, *, db, user):
            pass

        def evaluate(self, candidate_set, **kwargs):
            raise AssertionError("high intensity create should be normalized before evaluation")

    monkeypatch.setattr("fitmas.domain.planning.decision_service.PlanCandidateEvaluator", FailingEvaluator)
    requested = RequestedPlanChange(
        kind="create",
        source_ref=None,
        target_ref="date:2026-05-20",
        desired_sport=None,
        desired_duration_min=None,
        desired_intensity="high",
        reason="add high intensity session",
        risk_signals=("load",),
    )

    result = decide_plan_change(
        requested,
        context=_hard_dense_context(),
        db=object(),
        user=SimpleNamespace(id=1, timezone="Europe/Paris"),
        coach_state_bundle=None,
        reviewer_request_json_fn=None,
    )

    assert result.kind == "block"
    assert result.reason == (
        "Je ne rajoute pas de seance dure le 2026-05-20: la semaine a deja une charge intense trop proche. "
        "Je ne touche pas au plan."
    )


def test_decide_plan_change_blocks_target_only_create_on_occupied_day(monkeypatch) -> None:
    class FailingEvaluator:
        def __init__(self, *, db, user):
            pass

        def evaluate(self, candidate_set, **kwargs):
            raise AssertionError("target-only create on occupied day should block before evaluation")

    monkeypatch.setattr("fitmas.domain.planning.decision_service.PlanCandidateEvaluator", FailingEvaluator)
    requested = RequestedPlanChange(
        kind="create",
        source_ref=None,
        target_ref="date:2026-05-20",
        desired_sport=None,
        desired_duration_min=None,
        desired_intensity=None,
        reason="add session",
        risk_signals=(),
    )

    result = decide_plan_change(
        requested,
        context=_hard_dense_context(),
        db=object(),
        user=SimpleNamespace(id=1, timezone="Europe/Paris"),
        coach_state_bundle=None,
        reviewer_request_json_fn=None,
    )

    assert result.kind == "block"
    assert result.reason == (
        "Je ne rajoute pas de seance le 2026-05-20: une seance stable est deja prevue ce jour-la. "
        "Je ne touche pas au plan."
    )
    assert result.selected_candidate_id is None


def test_decide_plan_change_blocks_target_only_create_without_inferred_sport_on_free_day() -> None:
    requested = RequestedPlanChange(
        kind="create",
        source_ref=None,
        target_ref="date:2026-05-26",
        desired_sport=None,
        desired_duration_min=None,
        desired_intensity=None,
        reason="add session",
        risk_signals=(),
    )

    result = decide_plan_change(
        requested,
        context=_hard_dense_context(),
        db=object(),
        user=SimpleNamespace(id=1, timezone="Europe/Paris"),
        coach_state_bundle=None,
        reviewer_request_json_fn=None,
    )

    assert result.kind == "block"
    assert result.reason == (
        "Il me manque le sport cible pour creer une seance le 2026-05-26. Je ne touche pas au plan."
    )
    assert result.selected_candidate_id is None


def test_decide_plan_change_builds_swap_from_date_refs(monkeypatch) -> None:
    calls = []

    class FakeEvaluator:
        def __init__(self, *, db, user):
            pass

        def evaluate(self, candidate_set, **kwargs):
            calls.append(candidate_set)
            return ()

    monkeypatch.setattr("fitmas.domain.planning.decision_service.PlanCandidateEvaluator", FakeEvaluator)

    requested = RequestedPlanChange(
        kind="swap",
        source_ref="date:2026-05-20",
        target_ref="date:2026-05-21",
        desired_sport=None,
        desired_duration_min=None,
        desired_intensity=None,
        reason="swap days",
        risk_signals=(),
    )

    result = decide_plan_change(
        requested,
        context=_swap_context(),
        db=object(),
        user=SimpleNamespace(id=1, timezone="Europe/Paris"),
        coach_state_bundle=None,
        reviewer_request_json_fn=None,
    )

    candidate_set = calls[0]
    patch = next(iter(candidate_set.backend_candidate_patches.values()))
    assert patch.operations[0].operation_type == "swap_sessions"
    assert patch.operations[0].target_session_id == 1
    assert patch.operations[0].second_session_id == 2
    assert result.kind == "block"


def test_decide_plan_change_builds_swap_when_move_targets_occupied_day(monkeypatch) -> None:
    calls = []

    class FakeEvaluator:
        def __init__(self, *, db, user):
            pass

        def evaluate(self, candidate_set, **kwargs):
            calls.append(candidate_set)
            return ()

    monkeypatch.setattr("fitmas.domain.planning.decision_service.PlanCandidateEvaluator", FakeEvaluator)

    requested = RequestedPlanChange(
        kind="move",
        source_ref="date:2026-05-21",
        target_ref="date:2026-05-20",
        desired_sport=None,
        desired_duration_min=None,
        desired_intensity=None,
        reason="move hard session earlier",
        risk_signals=(),
    )

    result = decide_plan_change(
        requested,
        context=_swap_context(),
        db=object(),
        user=SimpleNamespace(id=1, timezone="Europe/Paris"),
        coach_state_bundle=None,
        reviewer_request_json_fn=None,
    )

    candidate_set = calls[0]
    patch = next(iter(candidate_set.backend_candidate_patches.values()))
    assert patch.operations[0].operation_type == "swap_sessions"
    assert patch.operations[0].target_session_id == 2
    assert patch.operations[0].second_session_id == 1
    assert result.kind == "block"


def test_decide_plan_change_blocks_empty_sport_window_with_user_safe_reason() -> None:
    requested = RequestedPlanChange(
        kind="replace",
        source_ref="sport_window:swimming:2026-05-18:2026-06-01",
        target_ref=None,
        desired_sport=None,
        desired_duration_min=None,
        desired_intensity="easy",
        reason="swim unavailable",
        risk_signals=("availability",),
    )

    result = decide_plan_change(
        requested,
        context=_context(),
        db=object(),
        user=SimpleNamespace(id=1, timezone="Europe/Paris"),
        coach_state_bundle=None,
        reviewer_request_json_fn=None,
    )

    assert result.kind == "block"
    assert result.reason == (
        "Je ne trouve aucune seance de natation planifiee entre 2026-05-18 et 2026-06-01. "
        "Je ne touche pas au plan."
    )


def test_decide_plan_change_routes_general_window_to_forced_pending(monkeypatch) -> None:
    class FakeEvaluator:
        def __init__(self, *, db, user):
            pass

        def evaluate(self, candidate_set, **kwargs):
            candidate = candidate_set.candidates[0]
            return (
                EvaluatedPlanPatchCandidate(
                    candidate=candidate,
                    candidate_validation=PlanPatchCandidateValidation(
                        status="valid",
                        patch_count=1,
                        operation_count=2,
                        operation_results=(),
                    ),
                    patch=candidate_set.backend_candidate_patches[candidate.candidate_ref],
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
                ),
            )

    monkeypatch.setattr("fitmas.domain.planning.decision_service.PlanCandidateEvaluator", FakeEvaluator)
    requested = RequestedPlanChange(
        kind="constraint_window",
        source_ref="availability_window:unavailable:general:2026-05-20:2026-05-22",
        target_ref=None,
        desired_sport=None,
        desired_duration_min=None,
        desired_intensity=None,
        reason="travel unavailable",
        risk_signals=("availability",),
    )

    result = decide_plan_change(
        requested,
        context=_window_context(),
        db=object(),
        user=SimpleNamespace(id=1, timezone="Europe/Paris"),
        coach_state_bundle=None,
        reviewer_request_json_fn=None,
    )

    assert result.kind == "pending_confirmation"
    assert result.selected_candidate_id == "backend:constraint_window:2026-05-20:2026-05-22:move_after"
    assert result.reason == "Fenetre large: confirmation requise avant de deplacer plusieurs seances."
    assert result.selected_patch is not None
    assert [operation.target_session_id for operation in result.selected_patch.operations] == [1, 2]
