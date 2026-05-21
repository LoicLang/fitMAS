from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

from fitmas.decision import turn_planning_route


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"
DECISION = SRC / "decision"


def _source(relative: str) -> str:
    return (SRC / relative).read_text(encoding="utf-8")


def _imports(relative: str) -> set[str]:
    tree = ast.parse(_source(relative), filename=relative)
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def test_10x_turn_planning_route_owner_exists_under_decision() -> None:
    assert (DECISION / "turn_planning_route.py").exists()


def test_10x_turn_router_delegates_canonical_planning_route() -> None:
    router = _source("decision/turn_router.py")
    imports = _imports("decision/turn_router.py")

    assert "fitmas.decision.turn_planning_route" in imports
    assert "fitmas.decision.planning_runtime" not in imports
    assert "handle_canonical_planning(" not in router
    assert "should_prepare_canonical_planning_understanding(" not in router


def test_10x_turn_router_shrinks_below_planning_route_budget() -> None:
    assert len(_source("decision/turn_router.py").splitlines()) <= 370


def test_10x_turn_planning_route_does_not_import_conversation_pipeline() -> None:
    imports = _imports("decision/turn_planning_route.py")

    assert "fitmas.conversation_pipeline" not in imports


def test_10x_planning_route_preserves_existing_understanding_when_not_applicable(monkeypatch) -> None:
    monkeypatch.setattr(
        turn_planning_route.planning_runtime,
        "should_prepare_canonical_planning_understanding",
        lambda **_kwargs: False,
    )

    result = turn_planning_route.route_pre_understanding_planning(
        db=SimpleNamespace(),
        user=SimpleNamespace(),
        user_text="oui",
        turn_plan=SimpleNamespace(),
        conversation_context=SimpleNamespace(),
        coach_bundle=SimpleNamespace(),
        state=SimpleNamespace(),
        pending_confirmation=None,
        context_artifacts=SimpleNamespace(),
        grounding_facts=(),
        turn_context={},
        decision_reply_composer_fn=lambda: SimpleNamespace(),
        reviewer_request_json_fn=lambda **_kwargs: {},
    )

    assert result.outcome is None
    assert result.canonical_understanding is None
    assert result.understanding_refreshed is False


def test_10x_existing_understanding_route_handles_unsupported_planning(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_handle(**kwargs):
        captured["handle_unsupported"] = kwargs["handle_unsupported"]
        return None, False

    monkeypatch.setattr(turn_planning_route, "_handle_planning_if_applicable", fake_handle)

    result = turn_planning_route.route_with_existing_understanding(
        db=SimpleNamespace(),
        user=SimpleNamespace(),
        user_text="Echange mercredi et jeudi",
        understanding=SimpleNamespace(),
        turn_plan=SimpleNamespace(),
        pending_confirmation=None,
        context_artifacts=SimpleNamespace(),
        coach_bundle=SimpleNamespace(),
        grounding_facts=(),
        turn_context={},
        decision_reply_composer_fn=lambda: SimpleNamespace(),
        reviewer_request_json_fn=lambda **_kwargs: {},
    )

    assert result.outcome is None
    assert captured == {"handle_unsupported": True}
