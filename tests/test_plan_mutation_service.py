from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fitmas.llm import MutationDecision
from fitmas.plan_mutation_service import (
    apply_decisions_for_user,
    complete_session_for_user,
    complete_session_from_activity_for_user,
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
    monkeypatch.setattr("fitmas.plan_mutation_service.repo.add_plan_mutation_event", lambda *args, **kwargs: None)
    monkeypatch.setattr("fitmas.plan_mutation_service.repo.get_scheduled_session", lambda *args, **kwargs: None)

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
    monkeypatch.setattr("fitmas.plan_mutation_service.repo.add_plan_mutation_event", lambda *args, **kwargs: None)
    monkeypatch.setattr("fitmas.plan_mutation_service.repo.get_scheduled_session", lambda *args, **kwargs: None)

    result = apply_decisions_for_user(
        object(),
        user=user,
        decisions=decisions,
    )

    assert result is not None
    assert result.attempted_count == 2
    assert result.applied_count == 1


def test_apply_decisions_for_user_records_event_for_successful_apply(monkeypatch) -> None:
    user = SimpleNamespace(id=7)
    decision = MutationDecision(
        mutation_type="lighten_day",
        target_session_id=10,
        rationale="fatigue",
        fitmas_message="On allege.",
    )

    monkeypatch.setattr(
        "fitmas.plan_mutation_service.repo.get_active_plan",
        lambda db, user_id: SimpleNamespace(id=42),
    )
    monkeypatch.setattr(
        "fitmas.plan_mutation_service.mutations.apply",
        lambda db, plan_id, decision, **kwargs: (SimpleNamespace(allowed=True), SimpleNamespace(delta_weekly_load=-2)),
    )

    events: list[dict] = []

    def _add_event(db, **kwargs):
        events.append(kwargs)
        return SimpleNamespace(id=99)

    monkeypatch.setattr("fitmas.plan_mutation_service.repo.add_plan_mutation_event", _add_event)
    monkeypatch.setattr("fitmas.plan_mutation_service.repo.get_scheduled_session", lambda *args, **kwargs: None)

    result = apply_decisions_for_user(
        object(),
        user=user,
        decisions=[decision],
        source="conversation",
        trigger_type="message",
    )

    assert result is not None
    assert result.applied_count == 1
    assert result.event_count == 1
    assert events == [
        {
            "user_id": 7,
            "source": "conversation",
            "trigger_type": "message",
            "command_type": "lighten_day",
            "target_session_ids": [10],
            "before_snapshot": {},
            "after_snapshot": {},
            "reason": {"rationale": "fatigue"},
            "impact": {"delta_weekly_load": -2},
            "user_visible_summary": "On allege.",
            "explained_to_user": False,
            "conversation_turn_id": None,
        }
    ]


def test_apply_decisions_for_user_returns_event_summary_for_replace(monkeypatch) -> None:
    user = SimpleNamespace(id=7)
    updated_session = SimpleNamespace(
        id=10,
        day="monday",
        scheduled_date=None,
        sport_type="swimming",
        session_type="recovery",
        session_title="Natation douce",
        duration_min=35,
        intensity="easy",
        completion_status="adapted",
    )
    decision = MutationDecision(
        mutation_type="replace_session",
        target_session_id=10,
        new_title="Natation douce",
        new_duration_min=35,
        new_intensity="easy",
        rationale="Epaule a proteger.",
        fitmas_message="Message LLM trop vague.",
    )

    monkeypatch.setattr(
        "fitmas.plan_mutation_service.repo.get_active_plan",
        lambda db, user_id: SimpleNamespace(id=42),
    )
    monkeypatch.setattr(
        "fitmas.plan_mutation_service.mutations.apply",
        lambda db, plan_id, decision, **kwargs: (SimpleNamespace(allowed=True), SimpleNamespace()),
    )
    monkeypatch.setattr(
        "fitmas.plan_mutation_service.repo.get_scheduled_session",
        lambda db, user_id, session_id: updated_session,
    )

    events: list[dict] = []

    def _add_event(db, **kwargs):
        events.append(kwargs)
        return SimpleNamespace(id=101)

    monkeypatch.setattr("fitmas.plan_mutation_service.repo.add_plan_mutation_event", _add_event)

    result = apply_decisions_for_user(
        object(),
        user=user,
        decisions=[decision],
        explained_to_user=True,
    )

    assert result is not None
    assert result.applied_events
    assert result.applied_events[0].event_id == 101
    assert result.applied_events[0].user_visible_summary == (
        "OK. Je bascule sur natation douce. 35 min, facile. Epaule a proteger."
    )
    assert events[0]["user_visible_summary"] == result.applied_events[0].user_visible_summary
    assert events[0]["explained_to_user"] is True


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
    monkeypatch.setattr("fitmas.plan_mutation_service.repo.get_scheduled_session", lambda *args, **kwargs: session)
    monkeypatch.setattr("fitmas.plan_mutation_service.repo.add_plan_mutation_event", lambda *args, **kwargs: None)

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
    monkeypatch.setattr("fitmas.plan_mutation_service.repo.get_scheduled_session", lambda *args, **kwargs: session)
    monkeypatch.setattr("fitmas.plan_mutation_service.repo.add_plan_mutation_event", lambda *args, **kwargs: None)

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


def test_activity_completion_with_legacy_day_sync_records_one_event(monkeypatch) -> None:
    user = SimpleNamespace(id=7)
    session = SimpleNamespace(
        id=10,
        day="monday",
        scheduled_date=None,
        sport_type="running",
        session_type="easy",
        session_title="Footing",
        duration_min=40,
        completion_status="done",
    )
    day_calls: list[tuple[int, str]] = []
    events: list[dict] = []

    monkeypatch.setattr(
        "fitmas.plan_mutation_service.plan_actions.complete_session",
        lambda db, *, user, session_id: session,
    )
    monkeypatch.setattr("fitmas.plan_mutation_service.repo.get_scheduled_session", lambda *args, **kwargs: session)
    monkeypatch.setattr(
        "fitmas.plan_mutation_service.repo.mark_day_completed",
        lambda db, plan_id, day: day_calls.append((plan_id, day)) or True,
    )
    monkeypatch.setattr(
        "fitmas.plan_mutation_service.repo.add_plan_mutation_event",
        lambda db, **kwargs: events.append(kwargs) or SimpleNamespace(id=201),
    )

    result = complete_session_from_activity_for_user(
        object(),
        user=user,
        session_id=10,
        plan_id=42,
        matched_day="monday",
        source="manual_activity",
    )

    assert result is not None
    assert result.action_type == "activity_completed"
    assert result.event_id == 201
    assert day_calls == [(42, "monday")]
    assert len(events) == 1
    assert events[0]["command_type"] == "activity_completed"
    assert events[0]["target_session_ids"] == [10]
    assert events[0]["reason"] == {"legacy_day_sync": "monday"}


def test_day_completion_helper_routes_legacy_day_sync(monkeypatch) -> None:
    calls: list[tuple[int, str]] = []

    def _mark_day_completed(db, plan_id, day):
        calls.append((plan_id, day))
        return True

    monkeypatch.setattr("fitmas.plan_mutation_service.repo.mark_day_completed", _mark_day_completed)
    monkeypatch.setattr("fitmas.plan_mutation_service.repo.add_plan_mutation_event", lambda *args, **kwargs: None)

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


def test_only_plan_mutation_service_imports_low_level_mutation_executor() -> None:
    root = Path(__file__).resolve().parents[1] / "backend/src/fitmas"
    offenders: list[str] = []
    forbidden = (
        "from fitmas import mutations",
        "import fitmas.mutations",
        "from fitmas.mutations",
    )
    for path in root.rglob("*.py"):
        if path.name == "plan_mutation_service.py":
            continue
        text = path.read_text()
        if any(token in text for token in forbidden):
            offenders.append(str(path.relative_to(root)))

    assert offenders == []
