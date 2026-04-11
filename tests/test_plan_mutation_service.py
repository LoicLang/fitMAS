from __future__ import annotations

from types import SimpleNamespace

from fitmas.llm import MutationDecision
from fitmas.plan_mutation_service import apply_decisions_for_user


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
