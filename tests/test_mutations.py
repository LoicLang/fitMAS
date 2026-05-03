from __future__ import annotations

from types import SimpleNamespace

from fitmas.llm import MutationDecision
from fitmas import mutations


def test_noop_move_session_does_not_run_post_hooks(monkeypatch) -> None:
    decision = MutationDecision(
        mutation_type="move_session",
        target_session_id=None,
        from_day=None,
        to_day=None,
        rationale="missing target",
        fitmas_message="OK. Je deplace.",
    )

    monkeypatch.setattr("fitmas.mutations.run_pre_mutation_hooks", lambda *args, **kwargs: SimpleNamespace(allowed=True))

    def _post_hook(*args, **kwargs):
        raise AssertionError("no-op mutation must not run post hooks")

    monkeypatch.setattr("fitmas.mutations.run_post_mutation_hooks", _post_hook)

    pre_result, post_result = mutations.apply(object(), 42, decision)

    assert pre_result.allowed is True
    assert post_result is None
