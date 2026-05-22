from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DECISION = ROOT / "backend" / "src" / "fitmas" / "decision"
ROUTER = DECISION / "turn_router.py"
UNDERSTANDING_ROUTE = DECISION / "turn_understanding_route.py"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _function_names(path: Path) -> set[str]:
    tree = ast.parse(_source(path), filename=str(path))
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _imports(path: Path) -> set[str]:
    tree = ast.parse(_source(path), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def test_14d_understanding_route_owner_exists() -> None:
    assert UNDERSTANDING_ROUTE.exists()
    assert "route_post_pre_understanding_decision" in _function_names(UNDERSTANDING_ROUTE)


def test_14d_turn_router_delegates_post_understanding_route() -> None:
    imports = _imports(ROUTER)
    source = _source(ROUTER)

    assert "fitmas.decision.turn_understanding_route" in imports
    assert "route_post_pre_understanding_decision(" in source


def test_14d_turn_router_no_longer_owns_post_understanding_branches() -> None:
    imports = _imports(ROUTER)
    source = _source(ROUTER)

    forbidden_imports = {
        "fitmas.decision.coach_decision_runtime",
        "fitmas.decision.command_application",
        "fitmas.decision.pending_resolution",
        "fitmas.decision.readonly_reply",
        "fitmas.decision.turn_idempotency",
        "fitmas.decision.understanding_runtime",
    }
    assert forbidden_imports.isdisjoint(imports)
    for token in (
        "should_use_canonical_understanding_without_legacy(",
        "should_use_canonical_readonly_without_legacy(",
        "canonical_provider_clarification_outcome(",
        "compose_understanding_command_reply(",
        "keep_pending_for_non_mutating_turn(",
        "decide_none_context(",
        "llm_unavailable",
    ):
        assert token not in source


def test_14d_turn_router_stays_under_next_route_budget() -> None:
    assert len(_source(ROUTER).splitlines()) <= 220
