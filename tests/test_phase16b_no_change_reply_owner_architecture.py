from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DECISION = ROOT / "backend" / "src" / "fitmas" / "decision"
NO_CHANGE_REPLY = DECISION / "no_change_reply.py"
READONLY_REPLY = DECISION / "readonly_reply.py"
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


def test_16b_no_change_reply_owner_exists() -> None:
    assert NO_CHANGE_REPLY.exists()
    functions = _function_names(NO_CHANGE_REPLY)

    assert "compose_no_change_reply_for_turn" in functions
    assert "memory_action_phrases_for_final_reply" in functions
    assert "execution_action_phrases_for_final_reply" in functions
    assert "_safe_no_change_fallback" in functions


def test_16b_turn_understanding_route_uses_no_change_reply_owner() -> None:
    source = _source(UNDERSTANDING_ROUTE)
    imports = _imports(UNDERSTANDING_ROUTE)

    assert "fitmas.legacy.decision.no_change_reply" in imports
    assert "compose_no_change_reply_for_turn_fn=no_change_reply.compose_no_change_reply_for_turn" in source
    assert "compose_no_change_reply_for_turn_fn=readonly_reply.compose_no_change_reply_for_turn" not in source


def test_16b_readonly_reply_no_longer_owns_no_change_reply() -> None:
    source = _source(READONLY_REPLY)
    imports = _imports(READONLY_REPLY)

    assert "def compose_no_change_reply_for_turn(" not in source
    assert "def memory_action_phrases_for_final_reply(" not in source
    assert "def execution_action_phrases_for_final_reply(" not in source
    assert "def turn_context_primary_intent(" not in source
    assert "def _safe_no_change_fallback(" not in source
    assert "fitmas.legacy.llm.reply_backend" not in imports
    assert "fitmas.legacy.domain.planning.repository" not in imports


def test_16b_readonly_reply_shrinks_below_no_change_cut_budget() -> None:
    assert len(_source(READONLY_REPLY).splitlines()) <= 360
