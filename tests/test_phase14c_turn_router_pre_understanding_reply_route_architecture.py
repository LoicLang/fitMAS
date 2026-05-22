from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DECISION = ROOT / "backend" / "src" / "fitmas" / "decision"
ROUTER = DECISION / "turn_router.py"
PRE_UNDERSTANDING_REPLY_ROUTE = DECISION / "turn_pre_understanding_reply_route.py"


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


def test_14c_pre_understanding_reply_route_owner_exists() -> None:
    assert PRE_UNDERSTANDING_REPLY_ROUTE.exists()
    assert "route_pre_understanding_replies" in _function_names(PRE_UNDERSTANDING_REPLY_ROUTE)


def test_14c_turn_router_delegates_pre_understanding_reply_route() -> None:
    imports = _imports(ROUTER)
    source = _source(ROUTER)

    assert "fitmas.decision.turn_pre_understanding_reply_route" in imports
    assert "route_pre_understanding_replies(" in source


def test_14c_turn_router_no_longer_owns_early_reply_composers() -> None:
    imports = _imports(ROUTER)
    source = _source(ROUTER)

    assert "fitmas.decision.activity_highlight" not in imports
    assert "fitmas.decision.clarification_reply" not in imports
    assert "compose_canonical_clarification_reply(" not in source
    assert "compose_activity_highlight_reply(" not in source


def test_14c_turn_router_stays_under_next_route_budget() -> None:
    assert len(_source(ROUTER).splitlines()) <= 310
