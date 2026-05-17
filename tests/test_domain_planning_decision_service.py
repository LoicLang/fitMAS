from __future__ import annotations

from types import SimpleNamespace

from fitmas.decision import RequestedPlanChange
from fitmas.domain.planning.decision_service import decide_plan_change


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
    assert "unresolved" in result.reason


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
