from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DECISION = ROOT / "backend" / "src" / "fitmas" / "decision"
ROUTER = DECISION / "turn_router.py"
PENDING_ROUTE = DECISION / "turn_pending_route.py"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _class_names(path: Path) -> set[str]:
    tree = ast.parse(_source(path), filename=str(path))
    return {node.name for node in tree.body if isinstance(node, ast.ClassDef)}


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


def test_14b_pending_route_owner_exists() -> None:
    assert PENDING_ROUTE.exists()
    assert "PendingRouteResult" in _class_names(PENDING_ROUTE)
    assert "route_pending_confirmation" in _function_names(PENDING_ROUTE)


def test_14b_turn_router_delegates_pending_route() -> None:
    imports = _imports(ROUTER)
    source = _source(ROUTER)

    assert "fitmas.decision.turn_pending_route" in imports
    assert "route_pending_confirmation(" in source


def test_14b_turn_router_no_longer_owns_pending_pre_understanding_flow() -> None:
    source = _source(ROUTER)

    assert "should_prepare_canonical_pending_understanding" not in source
    assert '"canonical_pending_provider"' not in source


def test_14b_turn_router_stays_under_next_route_budget() -> None:
    assert len(_source(ROUTER).splitlines()) <= 330
