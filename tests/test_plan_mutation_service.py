from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from fitmas.legacy.decision_contracts import MutationDecision
from fitmas.plan_patch import PlanPatch, PlanPatchOperation
from fitmas.plan_mutation_service import (
    apply_decisions_for_user,
    apply_patch_for_user,
    complete_session_for_user,
    complete_session_from_activity_for_user,
    mark_day_completed_for_user,
    mark_session_completed_for_user,
    move_session_for_user,
    skip_session_for_user,
)
from fitmas.week_coherence import WeekCoherenceFinding, WeekCoherenceReview


@pytest.fixture(autouse=True)
def _default_week_review(monkeypatch) -> None:
    monkeypatch.setattr(
        "fitmas.plan_mutation_service.review_week_coherence_with_llm",
        lambda *args, **kwargs: _week_review("valid", "commit_original"),
    )
    monkeypatch.setattr("fitmas.plan_mutation_service.repo.get_activities", lambda *args, **kwargs: [])
    monkeypatch.setattr("fitmas.plan_mutation_service.repo.get_active_memory_items", lambda *args, **kwargs: [])


def test_apply_decisions_for_user_returns_none_when_empty() -> None:
    user = SimpleNamespace(id=1)
    assert apply_decisions_for_user(object(), user=user, decisions=[]) is None


def test_apply_patch_for_user_commits_only_valid_patch(monkeypatch) -> None:
    user = SimpleNamespace(id=7, timezone="Europe/Paris")
    patch = PlanPatch(
        operations=[
            PlanPatchOperation(
                operation_type="replace_session",
                target_session_id=22,
                new_sport_type="running",
                new_session_type="easy",
                new_title="Running relais",
                new_duration_min=40,
                new_intensity="easy",
                rationale="Piscine fermee.",
            )
        ],
        coach_message="Je remplace par un running facile.",
    )

    monkeypatch.setattr("fitmas.plan_mutation_service.repo.get_active_plan_optional", lambda db, user_id: SimpleNamespace(id=42))
    monkeypatch.setattr(
        "fitmas.plan_mutation_service.repo.get_scheduled_sessions",
        lambda *args, **kwargs: [SimpleNamespace(id=22, intensity="easy", completion_status="planned")],
    )
    monkeypatch.setattr("fitmas.plan_mutation_service.repo.get_scheduled_session", lambda *args, **kwargs: None)
    monkeypatch.setattr("fitmas.plan_mutation_service.repo.add_plan_mutation_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "fitmas.plan_mutation_service.mutations.apply",
        lambda db, plan_id, decision, **kwargs: (SimpleNamespace(allowed=True, warnings=[]), SimpleNamespace()),
    )

    result = apply_patch_for_user(object(), user=user, patch=patch)

    assert result.validation.status == "valid"
    assert result.mutation_result is not None
    assert result.mutation_result.applied_count == 1


def test_apply_patch_for_user_week_review_requires_confirmation_prevents_commit(monkeypatch) -> None:
    user = SimpleNamespace(id=7, timezone="Europe/Paris")
    patch = PlanPatch(
        operations=[
            PlanPatchOperation(
                operation_type="move_session",
                target_session_id=22,
                target_date="2099-04-30",
                rationale="Indispo.",
            )
        ],
        coach_message="Je deplace.",
    )

    monkeypatch.setattr("fitmas.plan_mutation_service.repo.get_active_plan_optional", lambda db, user_id: SimpleNamespace(id=42))
    monkeypatch.setattr(
        "fitmas.plan_mutation_service.repo.get_scheduled_sessions",
        lambda *args, **kwargs: [SimpleNamespace(id=22, scheduled_date=date(2099, 4, 29), intensity="easy", completion_status="planned")],
    )
    monkeypatch.setattr(
        "fitmas.plan_mutation_service.review_week_coherence_with_llm",
        lambda *args, **kwargs: _week_review("requires_confirmation", "confirm_original"),
    )

    def _apply(*args, **kwargs):
        raise AssertionError("week review requires_confirmation must not commit")

    monkeypatch.setattr("fitmas.plan_mutation_service.mutations.apply", _apply)

    result = apply_patch_for_user(object(), user=user, patch=patch)

    assert result.validation.status == "valid"
    assert result.week_review is not None
    assert result.week_review.status == "requires_confirmation"
    assert result.week_policy_status == "requires_confirmation"
    assert result.mutation_result is None


def test_apply_patch_for_user_week_review_blocked_prevents_commit(monkeypatch) -> None:
    user = SimpleNamespace(id=7, timezone="Europe/Paris")
    patch = PlanPatch(
        operations=[
            PlanPatchOperation(
                operation_type="move_session",
                target_session_id=22,
                target_date="2099-04-30",
                rationale="Indispo.",
            )
        ],
        coach_message="Je deplace.",
    )

    monkeypatch.setattr("fitmas.plan_mutation_service.repo.get_active_plan_optional", lambda db, user_id: SimpleNamespace(id=42))
    monkeypatch.setattr(
        "fitmas.plan_mutation_service.repo.get_scheduled_sessions",
        lambda *args, **kwargs: [SimpleNamespace(id=22, scheduled_date=date(2099, 4, 29), intensity="easy", completion_status="planned")],
    )
    monkeypatch.setattr(
        "fitmas.plan_mutation_service.review_week_coherence_with_llm",
        lambda *args, **kwargs: _week_review("blocked", "block_original"),
    )

    def _apply(*args, **kwargs):
        raise AssertionError("week review blocked must not commit")

    monkeypatch.setattr("fitmas.plan_mutation_service.mutations.apply", _apply)

    result = apply_patch_for_user(object(), user=user, patch=patch)

    assert result.validation.status == "valid"
    assert result.week_review is not None
    assert result.week_review.status == "blocked"
    assert result.week_policy_status == "blocked"
    assert result.mutation_result is None


def test_apply_patch_for_user_confirmed_week_review_can_commit(monkeypatch) -> None:
    user = SimpleNamespace(id=7, timezone="Europe/Paris")
    patch = PlanPatch(
        operations=[
            PlanPatchOperation(
                operation_type="move_session",
                target_session_id=22,
                target_date="2099-04-30",
                rationale="Indispo.",
            )
        ],
        coach_message="Je deplace.",
    )
    calls: list[str] = []

    monkeypatch.setattr("fitmas.plan_mutation_service.repo.get_active_plan_optional", lambda db, user_id: SimpleNamespace(id=42))
    monkeypatch.setattr(
        "fitmas.plan_mutation_service.repo.get_scheduled_sessions",
        lambda *args, **kwargs: [SimpleNamespace(id=22, scheduled_date=date(2099, 4, 29), intensity="easy", completion_status="planned")],
    )
    monkeypatch.setattr("fitmas.plan_mutation_service.repo.get_scheduled_session", lambda *args, **kwargs: None)
    monkeypatch.setattr("fitmas.plan_mutation_service.repo.add_plan_mutation_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "fitmas.plan_mutation_service.review_week_coherence_with_llm",
        lambda *args, **kwargs: _week_review("requires_confirmation", "confirm_original"),
    )

    def _apply(db, plan_id, decision, **kwargs):
        calls.append(decision.mutation_type)
        return SimpleNamespace(allowed=True, warnings=[]), SimpleNamespace()

    monkeypatch.setattr("fitmas.plan_mutation_service.mutations.apply", _apply)

    result = apply_patch_for_user(object(), user=user, patch=patch, allow_requires_confirmation=True)

    assert result.week_policy_status == "valid"
    assert result.mutation_result is not None
    assert result.mutation_result.applied_count == 1
    assert calls == ["move_session"]


def test_apply_patch_for_user_passes_loaded_context_to_week_review(monkeypatch) -> None:
    user = SimpleNamespace(id=7, timezone="Europe/Paris")
    patch = PlanPatch(
        operations=[
            PlanPatchOperation(
                operation_type="move_session",
                target_session_id=22,
                target_date="2099-04-30",
                rationale="Indispo.",
            )
        ],
        coach_message="Je deplace.",
    )
    bundle = SimpleNamespace(
        planning_contract={"goal": "10k"},
        week_mission={"mission": "preserve_key_session"},
        session_policies=({"session_id": 22, "role": "key"},),
        recent_reality=None,
    )
    active_facts = ({"category": "availability", "key": "pool_closed", "value": "true"},)
    activities = (SimpleNamespace(id=1),)
    captured = []

    monkeypatch.setattr("fitmas.plan_mutation_service.repo.get_active_plan_optional", lambda db, user_id: SimpleNamespace(id=42))
    monkeypatch.setattr(
        "fitmas.plan_mutation_service.repo.get_scheduled_sessions",
        lambda *args, **kwargs: [SimpleNamespace(id=22, scheduled_date=date(2099, 4, 29), intensity="easy", completion_status="planned")],
    )

    def _review(context, **kwargs):
        captured.append(context)
        return _week_review("requires_confirmation", "confirm_original")

    monkeypatch.setattr("fitmas.plan_mutation_service.review_week_coherence_with_llm", _review)

    result = apply_patch_for_user(
        object(),
        user=user,
        patch=patch,
        coach_state_bundle=bundle,
        activities=activities,
        active_facts=active_facts,
    )

    assert result.week_policy_status == "requires_confirmation"
    assert captured[0].planning_contract == {"goal": "10k"}
    assert captured[0].week_mission == {"mission": "preserve_key_session"}
    assert captured[0].session_policies == ({"session_id": 22, "role": "key"},)
    assert captured[0].recent_reality == {"activity_count": 1}
    assert captured[0].active_constraints == active_facts


def test_apply_patch_for_user_runtime_block_skips_week_review(monkeypatch) -> None:
    user = SimpleNamespace(id=7, timezone="Europe/Paris")
    patch = PlanPatch(
        operations=[
            PlanPatchOperation(
                operation_type="move_session",
                target_session_id=999,
                target_date="2099-04-30",
                rationale="Indispo.",
            )
        ],
        coach_message="Je deplace.",
    )

    monkeypatch.setattr("fitmas.plan_mutation_service.repo.get_active_plan_optional", lambda db, user_id: SimpleNamespace(id=42))
    monkeypatch.setattr("fitmas.plan_mutation_service.repo.get_scheduled_sessions", lambda *args, **kwargs: [])

    def _review(*args, **kwargs):
        raise AssertionError("week review must not run after runtime hard block")

    monkeypatch.setattr("fitmas.plan_mutation_service.review_week_coherence_with_llm", _review)

    result = apply_patch_for_user(object(), user=user, patch=patch)

    assert result.validation.status == "blocked"
    assert result.week_review is None
    assert result.week_policy_status == "blocked"
    assert result.mutation_result is None


def test_apply_patch_for_user_does_not_commit_patch_requiring_confirmation(monkeypatch) -> None:
    user = SimpleNamespace(id=7, timezone="Europe/Paris")
    patch = PlanPatch(
        operations=[
            PlanPatchOperation(
                operation_type="replace_session",
                target_session_id=22,
                new_sport_type="running",
                new_session_type="tempo",
                new_title="Tempo relais",
                new_duration_min=45,
                new_intensity="hard",
                rationale="Remplacer la nage par une course qualite.",
            )
        ],
        coach_message="Je mets un tempo a la place.",
    )
    sessions = [
        SimpleNamespace(id=20, intensity="hard", completion_status="planned"),
        SimpleNamespace(id=21, intensity="key", completion_status="planned"),
        SimpleNamespace(id=24, intensity="hard", completion_status="planned"),
        SimpleNamespace(id=22, intensity="easy", completion_status="planned"),
    ]

    monkeypatch.setattr("fitmas.plan_mutation_service.repo.get_active_plan_optional", lambda db, user_id: SimpleNamespace(id=42))
    monkeypatch.setattr("fitmas.plan_mutation_service.repo.get_scheduled_sessions", lambda *args, **kwargs: sessions)

    def _apply(*args, **kwargs):
        raise AssertionError("patch requiring confirmation must not be committed")

    monkeypatch.setattr("fitmas.plan_mutation_service.mutations.apply", _apply)

    result = apply_patch_for_user(object(), user=user, patch=patch)

    assert result.validation.status == "requires_confirmation"
    assert result.mutation_result is None


def test_apply_patch_for_user_uses_runtime_sessions_without_active_plan(monkeypatch) -> None:
    user = SimpleNamespace(id=7, timezone="Europe/Paris")
    patch = PlanPatch(
        operations=[
            PlanPatchOperation(
                operation_type="replace_session",
                target_session_id=22,
                new_sport_type="running",
                new_session_type="easy",
                new_title="Running relais",
                new_duration_min=40,
                new_intensity="easy",
                rationale="Piscine fermee.",
            )
        ],
        coach_message="Je remplace par un running facile.",
    )

    monkeypatch.setattr("fitmas.plan_mutation_service.repo.get_active_plan_optional", lambda db, user_id: None)
    monkeypatch.setattr(
        "fitmas.plan_mutation_service.repo.get_scheduled_sessions",
        lambda *args, **kwargs: [SimpleNamespace(id=22, intensity="easy", completion_status="planned")],
    )
    monkeypatch.setattr("fitmas.plan_mutation_service.repo.get_scheduled_session", lambda *args, **kwargs: None)
    monkeypatch.setattr("fitmas.plan_mutation_service.repo.add_plan_mutation_event", lambda *args, **kwargs: None)

    captured: list[int] = []

    def _apply(db, plan_id, decision, **kwargs):
        captured.append(plan_id)
        return SimpleNamespace(allowed=True, warnings=[]), SimpleNamespace()

    monkeypatch.setattr("fitmas.plan_mutation_service.mutations.apply", _apply)

    result = apply_patch_for_user(object(), user=user, patch=patch)

    assert result.validation.status == "valid"
    assert result.mutation_result is not None
    assert result.mutation_result.applied_count == 1
    assert captured == [0]


def test_apply_patch_for_user_normalizes_targetless_replace_to_create_without_active_plan(monkeypatch) -> None:
    user = SimpleNamespace(id=7, timezone="Europe/Paris")
    patch = PlanPatch(
        operations=[
            PlanPatchOperation(
                operation_type="replace_session",
                target_session_id=None,
                target_date="2099-04-29",
                new_sport_type="running",
                new_session_type="easy",
                new_title="Running easy",
                new_duration_min=35,
                new_intensity="easy",
                rationale="Piscine fermee.",
            )
        ],
        coach_message="Je pose un running mercredi.",
    )
    created_session = SimpleNamespace(
        id=89,
        day="wednesday",
        scheduled_date=date(2099, 4, 29),
        sport_type="running",
        session_type="easy",
        session_title="Running easy",
        duration_min=35,
        completion_status="planned",
    )
    events: list[dict] = []

    monkeypatch.setattr("fitmas.plan_mutation_service.repo.get_active_plan_optional", lambda db, user_id: None)
    monkeypatch.setattr("fitmas.plan_mutation_service.repo.get_scheduled_sessions", lambda *args, **kwargs: [])
    monkeypatch.setattr("fitmas.plan_mutation_service.plan_actions.create_session", lambda *args, **kwargs: created_session)
    monkeypatch.setattr("fitmas.plan_mutation_service.repo.add_plan_mutation_event", lambda *args, **kwargs: events.append(kwargs) or SimpleNamespace(id=124))

    result = apply_patch_for_user(object(), user=user, patch=patch)

    assert result.validation.status == "valid"
    assert result.mutation_result is not None
    assert result.mutation_result.applied_count == 1
    assert result.mutation_result.applied_events[0].command_type == "create_session"
    assert events[0]["command_type"] == "create_session"


def test_apply_patch_for_user_can_commit_confirmed_patch_requiring_confirmation(monkeypatch) -> None:
    user = SimpleNamespace(id=7, timezone="Europe/Paris")
    patch = PlanPatch(
        operations=[
            PlanPatchOperation(
                operation_type="replace_session",
                target_session_id=22,
                new_sport_type="running",
                new_session_type="tempo",
                new_title="Tempo relais",
                new_duration_min=45,
                new_intensity="hard",
                rationale="Remplacer la nage par une course qualite.",
            )
        ],
        coach_message="Je mets un tempo a la place.",
    )
    sessions = [
        SimpleNamespace(id=20, intensity="hard", completion_status="planned"),
        SimpleNamespace(id=21, intensity="key", completion_status="planned"),
        SimpleNamespace(id=24, intensity="hard", completion_status="planned"),
        SimpleNamespace(id=22, intensity="easy", completion_status="planned"),
    ]

    monkeypatch.setattr("fitmas.plan_mutation_service.repo.get_active_plan_optional", lambda db, user_id: SimpleNamespace(id=42))
    monkeypatch.setattr("fitmas.plan_mutation_service.repo.get_scheduled_sessions", lambda *args, **kwargs: sessions)
    monkeypatch.setattr("fitmas.plan_mutation_service.repo.get_scheduled_session", lambda *args, **kwargs: None)
    monkeypatch.setattr("fitmas.plan_mutation_service.repo.add_plan_mutation_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "fitmas.plan_mutation_service.mutations.apply",
        lambda db, plan_id, decision, **kwargs: (
            SimpleNamespace(allowed=True, warnings=[SimpleNamespace(message="Charge dense.")]),
            SimpleNamespace(),
        ),
    )

    result = apply_patch_for_user(object(), user=user, patch=patch, allow_requires_confirmation=True)

    assert result.validation.status == "requires_confirmation"
    assert result.mutation_result is not None
    assert result.mutation_result.applied_count == 1


def test_apply_patch_for_user_creates_session_from_create_operation(monkeypatch) -> None:
    user = SimpleNamespace(id=7, timezone="Europe/Paris")
    patch = PlanPatch(
        operations=[
            PlanPatchOperation(
                operation_type="create_session",
                target_date="2099-04-29",
                new_sport_type="running",
                new_session_type="easy",
                new_title="Footing easy",
                new_goal="Garder du volume sans piscine.",
                new_duration_min=30,
                new_intensity="easy",
                rationale="Piscine fermee.",
            )
        ],
        coach_message="Je pose un footing easy mercredi.",
    )
    created_session = SimpleNamespace(
        id=88,
        day="wednesday",
        scheduled_date=date(2099, 4, 29),
        sport_type="running",
        session_type="easy",
        session_title="Footing easy",
        duration_min=30,
        completion_status="planned",
    )

    monkeypatch.setattr("fitmas.plan_mutation_service.repo.get_active_plan_optional", lambda db, user_id: SimpleNamespace(id=42, created_at=None))
    monkeypatch.setattr("fitmas.plan_mutation_service.repo.get_scheduled_sessions", lambda *args, **kwargs: [])
    monkeypatch.setattr("fitmas.plan_mutation_service.plan_actions.create_session", lambda *args, **kwargs: created_session)

    events: list[dict] = []
    monkeypatch.setattr(
        "fitmas.plan_mutation_service.repo.add_plan_mutation_event",
        lambda db, **kwargs: events.append(kwargs) or SimpleNamespace(id=501),
    )

    result = apply_patch_for_user(object(), user=user, patch=patch, explained_to_user=True)

    assert result.validation.status == "valid"
    assert result.mutation_result is not None
    assert result.mutation_result.applied_count == 1
    assert result.mutation_result.applied_events[0].command_type == "create_session"
    assert result.mutation_result.applied_events[0].target_session_id == 88
    assert events[0]["command_type"] == "create_session"
    assert events[0]["target_session_ids"] == [88]
    assert events[0]["explained_to_user"] is True


def test_apply_decisions_for_user_routes_all_decisions_through_mutations(monkeypatch) -> None:
    user = SimpleNamespace(id=7)
    decisions = [
        MutationDecision(mutation_type="lighten_day", target_session_id=10, rationale="fatigue", fitmas_message=""),
        MutationDecision(mutation_type="replace_session", target_session_id=11, rationale="douleur", fitmas_message=""),
    ]

    calls: list[tuple[int, str]] = []

    def _fake_apply(db, plan_id, decision, **kwargs):
        calls.append((plan_id, decision.mutation_type))
        return SimpleNamespace(allowed=True), SimpleNamespace()

    monkeypatch.setattr("fitmas.plan_mutation_service.mutations.apply", _fake_apply)
    monkeypatch.setattr("fitmas.plan_mutation_service.repo.add_plan_mutation_event", lambda *args, **kwargs: None)
    monkeypatch.setattr("fitmas.plan_mutation_service.repo.get_scheduled_sessions", lambda *args, **kwargs: [])
    monkeypatch.setattr("fitmas.plan_mutation_service.repo.get_scheduled_session", lambda *args, **kwargs: None)

    result = apply_decisions_for_user(
        object(),
        user=user,
        decisions=decisions,
    )

    assert result is not None
    assert result.plan_id == 0
    assert result.attempted_count == 2
    assert result.applied_count == 2
    assert result.event_count == 2
    assert calls == [(0, "lighten_day"), (0, "replace_session")]


def test_apply_decisions_for_user_routes_create_session_through_patch_path(monkeypatch) -> None:
    user = SimpleNamespace(id=7, timezone="Europe/Paris")
    decision = MutationDecision(
        mutation_type="create_session",
        target_date="2099-04-29",
        new_sport_type="running",
        new_session_type="easy",
        new_title="Footing easy",
        new_goal="Garder du volume.",
        new_duration_min=30,
        new_intensity="easy",
        rationale="Piscine fermee.",
        fitmas_message="Je pose un footing easy mercredi.",
    )
    created_session = SimpleNamespace(
        id=89,
        day="wednesday",
        scheduled_date=date(2099, 4, 29),
        sport_type="running",
        session_type="easy",
        session_title="Footing easy",
        duration_min=30,
        completion_status="planned",
    )

    monkeypatch.setattr("fitmas.plan_mutation_service.repo.get_active_plan_optional", lambda db, user_id: SimpleNamespace(id=42, created_at=None))
    monkeypatch.setattr("fitmas.plan_mutation_service.repo.get_scheduled_sessions", lambda *args, **kwargs: [])
    monkeypatch.setattr("fitmas.plan_mutation_service.plan_actions.create_session", lambda *args, **kwargs: created_session)

    events: list[dict] = []
    monkeypatch.setattr(
        "fitmas.plan_mutation_service.repo.add_plan_mutation_event",
        lambda db, **kwargs: events.append(kwargs) or SimpleNamespace(id=502),
    )

    result = apply_decisions_for_user(object(), user=user, decisions=[decision], explained_to_user=True)

    assert result is not None
    assert result.applied_count == 1
    assert result.event_count == 1
    assert result.applied_events[0].command_type == "create_session"
    assert events[0]["command_type"] == "create_session"


def test_apply_decisions_for_user_uses_runtime_sessions_without_active_plan(monkeypatch) -> None:
    user = SimpleNamespace(id=7, timezone="Europe/Paris")
    decision = MutationDecision(
        mutation_type="replace_session",
        target_session_id=11,
        rationale="contrainte",
        fitmas_message="On remplace.",
    )

    monkeypatch.setattr(
        "fitmas.plan_mutation_service.repo.get_active_plan_optional",
        lambda db, user_id: None,
    )
    monkeypatch.setattr(
        "fitmas.plan_mutation_service.repo.get_scheduled_sessions",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        "fitmas.plan_mutation_service.repo.get_scheduled_session",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "fitmas.plan_mutation_service.repo.add_plan_mutation_event",
        lambda *args, **kwargs: None,
    )

    captured: list[int] = []

    def _fake_apply(db, plan_id, decision, **kwargs):
        captured.append(plan_id)
        return SimpleNamespace(allowed=True), SimpleNamespace()

    monkeypatch.setattr("fitmas.plan_mutation_service.mutations.apply", _fake_apply)

    result = apply_decisions_for_user(
        object(),
        user=user,
        decisions=[decision],
    )

    assert result is not None
    assert result.plan_id == 0
    assert captured == [0]


def test_apply_decisions_for_user_counts_only_successful_applies(monkeypatch) -> None:
    user = SimpleNamespace(id=7)
    decisions = [
        MutationDecision(mutation_type="lighten_day", target_session_id=10, rationale="fatigue", fitmas_message=""),
        MutationDecision(mutation_type="no_change", rationale="noop", fitmas_message=""),
    ]

    monkeypatch.setattr(
        "fitmas.plan_mutation_service.repo.get_active_plan_optional",
        lambda db, user_id: SimpleNamespace(id=42),
    )

    def _fake_apply(db, plan_id, decision, **kwargs):
        if decision.mutation_type == "lighten_day":
            return SimpleNamespace(allowed=True), SimpleNamespace()
        return SimpleNamespace(allowed=True), None

    monkeypatch.setattr("fitmas.plan_mutation_service.mutations.apply", _fake_apply)
    monkeypatch.setattr("fitmas.plan_mutation_service.repo.add_plan_mutation_event", lambda *args, **kwargs: None)
    monkeypatch.setattr("fitmas.plan_mutation_service.repo.get_scheduled_sessions", lambda *args, **kwargs: [])
    monkeypatch.setattr("fitmas.plan_mutation_service.repo.get_scheduled_session", lambda *args, **kwargs: None)

    result = apply_decisions_for_user(
        object(),
        user=user,
        decisions=decisions,
    )

    assert result is not None
    assert result.attempted_count == 2
    assert result.applied_count == 1
    assert result.event_count == 1


def test_apply_decisions_for_user_exposes_blocked_events_with_reason(monkeypatch) -> None:
    """When a pre-hook blocks a mutation, the service result must surface
    the block_reason so the caller can generate a reason-specific reply
    instead of a generic fallback."""
    user = SimpleNamespace(id=7)
    decision = MutationDecision(
        mutation_type="move_session",
        target_session_id=10,
        target_date="2026-04-17",
        rationale="repos",
        fitmas_message="Je deplace.",
    )

    monkeypatch.setattr(
        "fitmas.plan_mutation_service.repo.get_active_plan_optional",
        lambda db, user_id: SimpleNamespace(id=42),
    )
    monkeypatch.setattr(
        "fitmas.plan_mutation_service.mutations.apply",
        lambda db, plan_id, decision, **kwargs: (
            SimpleNamespace(allowed=False, block_reason="protected_recovery_target", warnings=[]),
            None,
        ),
    )
    monkeypatch.setattr("fitmas.plan_mutation_service.repo.get_scheduled_sessions", lambda *args, **kwargs: [])
    monkeypatch.setattr("fitmas.plan_mutation_service.repo.add_plan_mutation_event", lambda *args, **kwargs: None)

    result = apply_decisions_for_user(
        object(),
        user=user,
        decisions=[decision],
    )

    assert result is not None
    assert result.attempted_count == 1
    assert result.applied_count == 0
    assert len(result.blocked_events) == 1
    blocked = result.blocked_events[0]
    assert blocked.command_type == "move_session"
    assert blocked.block_reason == "protected_recovery_target"
    assert blocked.target_session_id == 10


def test_apply_decisions_for_user_does_not_event_noop_move(monkeypatch) -> None:
    user = SimpleNamespace(id=7)
    decision = MutationDecision(
        mutation_type="move_session",
        target_session_id=None,
        target_date="2026-04-17",
        rationale="no concrete session",
        fitmas_message="OK. Je deplace.",
    )

    monkeypatch.setattr(
        "fitmas.plan_mutation_service.repo.get_active_plan_optional",
        lambda db, user_id: SimpleNamespace(id=42),
    )
    monkeypatch.setattr(
        "fitmas.plan_mutation_service.mutations.apply",
        lambda db, plan_id, decision, **kwargs: (SimpleNamespace(allowed=True), None),
    )
    monkeypatch.setattr("fitmas.plan_mutation_service.repo.get_scheduled_sessions", lambda *args, **kwargs: [])

    def _add_event(*args, **kwargs):
        raise AssertionError("no-op move should not create a mutation event")

    monkeypatch.setattr("fitmas.plan_mutation_service.repo.add_plan_mutation_event", _add_event)

    result = apply_decisions_for_user(object(), user=user, decisions=[decision])

    assert result is not None
    assert result.applied_count == 0
    assert result.event_count == 0
    assert result.applied_events == ()


def test_apply_decisions_for_user_passes_runtime_sessions_to_mutation_hooks(monkeypatch) -> None:
    user = SimpleNamespace(id=7, timezone="Europe/Paris")
    sessions = [SimpleNamespace(id=10), SimpleNamespace(id=11)]
    decision = MutationDecision(
        mutation_type="move_session",
        target_session_id=10,
        target_date="2026-04-03",
        rationale="indispo",
        fitmas_message="Je deplace.",
    )

    monkeypatch.setattr(
        "fitmas.plan_mutation_service.repo.get_active_plan_optional",
        lambda db, user_id: SimpleNamespace(id=42),
    )
    monkeypatch.setattr(
        "fitmas.plan_mutation_service.repo.get_scheduled_sessions",
        lambda db, user_id, limit: sessions,
    )
    monkeypatch.setattr("fitmas.plan_mutation_service.repo.get_scheduled_session", lambda *args, **kwargs: None)
    monkeypatch.setattr("fitmas.plan_mutation_service.repo.add_plan_mutation_event", lambda *args, **kwargs: None)

    captured: dict[str, object] = {}

    def _fake_apply(db, plan_id, decision, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(allowed=True), SimpleNamespace()

    monkeypatch.setattr("fitmas.plan_mutation_service.mutations.apply", _fake_apply)

    result = apply_decisions_for_user(object(), user=user, decisions=[decision])

    assert result is not None
    assert captured["scheduled_sessions"] is sessions
    assert captured["timezone_name"] == "Europe/Paris"


def test_apply_decisions_for_user_records_event_for_successful_apply(monkeypatch) -> None:
    user = SimpleNamespace(id=7)
    decision = MutationDecision(
        mutation_type="lighten_day",
        target_session_id=10,
        rationale="fatigue",
        fitmas_message="On allege.",
    )

    monkeypatch.setattr(
        "fitmas.plan_mutation_service.repo.get_active_plan_optional",
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
    monkeypatch.setattr("fitmas.plan_mutation_service.repo.get_scheduled_sessions", lambda *args, **kwargs: [])
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


def test_multi_session_decision_records_one_event_with_both_targets(monkeypatch) -> None:
    user = SimpleNamespace(id=7)
    decision = MutationDecision(
        mutation_type="swap_sessions",
        target_session_id=10,
        second_session_id=11,
        rationale="recovery",
        fitmas_message="J'echange les deux seances.",
    )

    monkeypatch.setattr(
        "fitmas.plan_mutation_service.repo.get_active_plan_optional",
        lambda db, user_id: SimpleNamespace(id=42),
    )
    monkeypatch.setattr(
        "fitmas.plan_mutation_service.mutations.apply",
        lambda db, plan_id, decision, **kwargs: (SimpleNamespace(allowed=True), SimpleNamespace()),
    )
    monkeypatch.setattr("fitmas.plan_mutation_service.repo.get_scheduled_session", lambda *args, **kwargs: None)
    monkeypatch.setattr("fitmas.plan_mutation_service.repo.get_scheduled_sessions", lambda *args, **kwargs: [])

    events: list[dict] = []
    monkeypatch.setattr(
        "fitmas.plan_mutation_service.repo.add_plan_mutation_event",
        lambda db, **kwargs: events.append(kwargs) or SimpleNamespace(id=202),
    )

    result = apply_decisions_for_user(object(), user=user, decisions=[decision])

    assert result is not None
    assert result.applied_count == 1
    assert result.event_count == 1
    assert events[0]["command_type"] == "swap_sessions"
    assert events[0]["target_session_ids"] == [10, 11]


def test_swap_session_event_summary_uses_committed_session_not_llm_text(monkeypatch) -> None:
    user = SimpleNamespace(id=7)
    first_after = SimpleNamespace(
        id=10,
        day="wednesday",
        label="Mercredi",
        scheduled_date=None,
        sport_type="running",
        session_type="fartlek",
        session_title="Fartlek progressif",
        duration_min=42,
        intensity="hard",
        completion_status="adapted",
    )
    second_after = SimpleNamespace(
        id=11,
        day="thursday",
        label="Jeudi",
        scheduled_date=None,
        sport_type="swimming",
        session_type="technique",
        session_title="Natation technique",
        duration_min=35,
        intensity="moderate",
        completion_status="adapted",
    )
    decision = MutationDecision(
        mutation_type="swap_sessions",
        target_session_id=10,
        second_session_id=11,
        rationale="Simple inversion.",
        fitmas_message="Natation mercredi et fartlek jeudi ? Simple inversion des deux jours.",
    )

    monkeypatch.setattr(
        "fitmas.plan_mutation_service.repo.get_active_plan_optional",
        lambda db, user_id: SimpleNamespace(id=42),
    )
    monkeypatch.setattr(
        "fitmas.plan_mutation_service.mutations.apply",
        lambda db, plan_id, decision, **kwargs: (SimpleNamespace(allowed=True), SimpleNamespace()),
    )
    monkeypatch.setattr(
        "fitmas.plan_mutation_service.repo.get_scheduled_session",
        lambda db, user_id, session_id: {10: first_after, 11: second_after}.get(session_id),
    )
    monkeypatch.setattr("fitmas.plan_mutation_service.repo.get_scheduled_sessions", lambda *args, **kwargs: [])

    events: list[dict] = []
    monkeypatch.setattr(
        "fitmas.plan_mutation_service.repo.add_plan_mutation_event",
        lambda db, **kwargs: events.append(kwargs) or SimpleNamespace(id=203),
    )

    result = apply_decisions_for_user(object(), user=user, decisions=[decision])

    assert result is not None
    summary = result.applied_events[0].user_visible_summary
    assert "Mercredi" in summary
    assert "Fartlek progressif" in summary
    assert "42 min" in summary
    assert "Jeudi" in summary
    assert "Natation technique" in summary
    assert "35 min" in summary
    assert "Natation mercredi" not in summary
    assert events[0]["user_visible_summary"] == summary


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
        "fitmas.plan_mutation_service.repo.get_active_plan_optional",
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
    monkeypatch.setattr("fitmas.plan_mutation_service.repo.get_scheduled_sessions", lambda *args, **kwargs: [])

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


def test_move_session_for_user_blocks_same_sport_proximity_before_action(monkeypatch) -> None:
    user = SimpleNamespace(id=7, timezone="Europe/Paris")
    target = SimpleNamespace(
        id=10,
        scheduled_date=date(2026, 4, 13),
        sport_type="running",
        session_type="tempo",
        completion_status="planned",
    )
    neighbor = SimpleNamespace(
        id=11,
        scheduled_date=date(2026, 4, 16),
        sport_type="running",
        session_type="tempo",
        completion_status="planned",
    )
    called = {"move": False, "event": False}

    monkeypatch.setattr("fitmas.plan_mutation_service.repo.get_scheduled_session", lambda *args, **kwargs: target)
    monkeypatch.setattr("fitmas.plan_mutation_service.repo.get_scheduled_sessions", lambda *args, **kwargs: [target, neighbor])

    def _move(*args, **kwargs):
        called["move"] = True
        raise AssertionError("blocked move should not reach plan_actions.move_session")

    def _event(*args, **kwargs):
        called["event"] = True
        raise AssertionError("blocked move should not create event")

    monkeypatch.setattr("fitmas.plan_mutation_service.plan_actions.move_session", _move)
    monkeypatch.setattr("fitmas.plan_mutation_service.repo.add_plan_mutation_event", _event)

    result = move_session_for_user(
        object(),
        user=user,
        session_id=10,
        target_date=date(2026, 4, 15),
        source="app",
    )

    assert result is None
    assert called == {"move": False, "event": False}


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


def test_activity_completion_does_not_sync_legacy_day_plan(monkeypatch) -> None:
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
    events: list[dict] = []

    monkeypatch.setattr(
        "fitmas.plan_mutation_service.plan_actions.complete_session",
        lambda db, *, user, session_id: session,
    )
    monkeypatch.setattr("fitmas.plan_mutation_service.repo.get_scheduled_session", lambda *args, **kwargs: session)

    def _mark_day_completed(*args, **kwargs):
        raise AssertionError("runtime activity completion must not mutate DayPlan")

    monkeypatch.setattr("fitmas.plan_mutation_service.repo.mark_day_completed", _mark_day_completed)
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
    assert events[0]["command_type"] == "activity_completed"
    assert events[0]["reason"] == {"matched_day": "monday"}


def test_activity_completion_records_matched_day_without_legacy_sync(monkeypatch) -> None:
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
    assert day_calls == []
    assert len(events) == 1
    assert events[0]["command_type"] == "activity_completed"
    assert events[0]["target_session_ids"] == [10]
    assert events[0]["reason"] == {"matched_day": "monday"}


def test_day_completion_helper_is_noop_compat(monkeypatch) -> None:
    def _mark_day_completed(*args, **kwargs):
        raise AssertionError("compat helper must not mutate DayPlan")

    def _add_event(*args, **kwargs):
        raise AssertionError("compat helper must not emit legacy day events")

    monkeypatch.setattr("fitmas.plan_mutation_service.repo.mark_day_completed", _mark_day_completed)
    monkeypatch.setattr("fitmas.plan_mutation_service.repo.add_plan_mutation_event", _add_event)

    result = mark_day_completed_for_user(
        object(),
        plan_id=42,
        day="monday",
        source="manual_activity",
    )

    assert result is False


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


def _week_review(status: str, recommended_policy: str) -> WeekCoherenceReview:
    return WeekCoherenceReview(
        status=status,
        sport_quality="fragile" if status != "valid" else "good",
        confidence=0.86,
        summary="review semaine",
        findings=(
            WeekCoherenceFinding(
                code="mission_preserved" if status == "valid" else "mission_diluted",
                severity="info" if status == "valid" else "requires_confirmation",
                detail="Review test.",
            ),
        ),
        suggested_adjustments=(),
        recommended_policy=recommended_policy,
    )
