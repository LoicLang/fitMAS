from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fitmas.llm import MutationDecision
from fitmas.plan_mutation_service import (
    apply_decisions_for_user,
    complete_session_for_user,
    mark_day_completed_for_user,
    mark_session_completed_for_user,
    move_session_for_user,
    skip_session_for_user,
)


def test_apply_decisions_for_user_returns_none_when_empty() -> None:
    user = SimpleNamespace(id=1)
    assert apply_decisions_for_user(object(), user=user, decisions=[]) is None


def test_apply_decisions_for_user_routes_all_decisions_through_mutations(monkeypatch) -> None:
    user = SimpleNamespace(id=7)
    decisions = [
        MutationDecision(mutation_type="lighten_day", target_session_id=10, rationale="fatigue", fitmas_message=""),
        MutationDecision(mutation_type="replace_session", target_session_id=11, rationale="douleur", fitmas_message=""),
    ]

    monkeypatch.setattr(
        "fitmas.plan_mutation_service.repo.get_active_plan",
        lambda db, user_id: SimpleNamespace(id=42),
    )

    calls: list[tuple[int, str]] = []

    def _fake_apply(db, plan_id, decision, **kwargs):
        calls.append((plan_id, decision.mutation_type))
        return SimpleNamespace(allowed=True), SimpleNamespace()

    monkeypatch.setattr("fitmas.plan_mutation_service.mutations.apply", _fake_apply)

    result = apply_decisions_for_user(
        object(),
        user=user,
        decisions=decisions,
    )

    assert result is not None
    assert result.plan_id == 42
    assert result.attempted_count == 2
    assert result.applied_count == 2
    assert calls == [(42, "lighten_day"), (42, "replace_session")]


def test_apply_decisions_for_user_counts_only_successful_applies(monkeypatch) -> None:
    user = SimpleNamespace(id=7)
    decisions = [
        MutationDecision(mutation_type="lighten_day", target_session_id=10, rationale="fatigue", fitmas_message=""),
        MutationDecision(mutation_type="no_change", rationale="noop", fitmas_message=""),
    ]

    monkeypatch.setattr(
        "fitmas.plan_mutation_service.repo.get_active_plan",
        lambda db, user_id: SimpleNamespace(id=42),
    )

    def _fake_apply(db, plan_id, decision, **kwargs):
        if decision.mutation_type == "lighten_day":
            return SimpleNamespace(allowed=True), SimpleNamespace()
        return SimpleNamespace(allowed=True), None

    monkeypatch.setattr("fitmas.plan_mutation_service.mutations.apply", _fake_apply)

    result = apply_decisions_for_user(
        object(),
        user=user,
        decisions=decisions,
    )

    assert result is not None
    assert result.attempted_count == 2
    assert result.applied_count == 1


def test_session_action_helpers_route_through_low_level_actions(monkeypatch) -> None:
    user = SimpleNamespace(id=7)
    session = SimpleNamespace(id=10)
    calls: list[tuple[str, int]] = []

    def _complete(db, *, user, session_id):
        calls.append(("complete", session_id))
        return session

    def _skip(db, *, user, session_id):
        calls.append(("skip", session_id))
        return session

    def _move(db, *, user, session_id, target_date=None):
        calls.append(("move", session_id))
        return session

    monkeypatch.setattr("fitmas.plan_mutation_service.plan_actions.complete_session", _complete)
    monkeypatch.setattr("fitmas.plan_mutation_service.plan_actions.skip_session", _skip)
    monkeypatch.setattr("fitmas.plan_mutation_service.plan_actions.move_session", _move)

    completed = complete_session_for_user(object(), user=user, session_id=10, source="app")
    skipped = skip_session_for_user(object(), user=user, session_id=10, source="app")
    moved = move_session_for_user(object(), user=user, session_id=10, target_date=None, source="app")

    assert completed is not None
    assert completed.action_type == "complete_session"
    assert completed.source == "app"
    assert completed.session is session
    assert skipped is not None
    assert skipped.action_type == "skip_session"
    assert moved is not None
    assert moved.action_type == "move_session"
    assert calls == [("complete", 10), ("skip", 10), ("move", 10)]


def test_activity_completion_helper_records_activity_source(monkeypatch) -> None:
    user = SimpleNamespace(id=7)
    session = SimpleNamespace(id=10)

    monkeypatch.setattr(
        "fitmas.plan_mutation_service.plan_actions.complete_session",
        lambda db, *, user, session_id: session,
    )

    result = mark_session_completed_for_user(
        object(),
        user=user,
        session_id=10,
        source="strava",
    )

    assert result is not None
    assert result.action_type == "activity_completed"
    assert result.source == "strava"
    assert result.session is session


def test_day_completion_helper_routes_legacy_day_sync(monkeypatch) -> None:
    calls: list[tuple[int, str]] = []

    def _mark_day_completed(db, plan_id, day):
        calls.append((plan_id, day))
        return True

    monkeypatch.setattr("fitmas.plan_mutation_service.repo.mark_day_completed", _mark_day_completed)

    result = mark_day_completed_for_user(
        object(),
        plan_id=42,
        day="monday",
        source="manual_activity",
    )

    assert result is True
    assert calls == [(42, "monday")]


def test_orchestrators_do_not_call_low_level_plan_writers_directly() -> None:
    root = Path(__file__).resolve().parents[1]
    orchestrators = [
        root / "backend/src/fitmas/api_plan.py",
        root / "backend/src/fitmas/api_activities.py",
        root / "backend/src/fitmas/api_messages.py",
        root / "backend/src/fitmas/strava.py",
    ]
    forbidden = (
        "plan_actions.",
        "repo.mark_scheduled_session_completed",
        "repo.set_scheduled_session_status",
        "repo.mark_day_completed",
    )

    offenders: list[str] = []
    for path in orchestrators:
        text = path.read_text()
        for token in forbidden:
            if token in text:
                offenders.append(f"{path.name}: {token}")

    assert offenders == []
