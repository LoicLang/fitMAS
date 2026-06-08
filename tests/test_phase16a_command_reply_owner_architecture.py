from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DECISION = ROOT / "backend" / "src" / "fitmas" / "decision"
COMMAND_REPLY = DECISION / "command_reply.py"
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


def test_16a_command_reply_owner_exists() -> None:
    assert COMMAND_REPLY.exists()
    functions = _function_names(COMMAND_REPLY)

    assert "should_compose_understanding_command_reply" in functions
    assert "compose_understanding_command_reply" in functions
    assert "_reply_hint_from_understanding" in functions


def test_16a_turn_understanding_route_uses_command_reply_owner() -> None:
    source = _source(UNDERSTANDING_ROUTE)
    imports = _imports(UNDERSTANDING_ROUTE)

    assert "fitmas.legacy.decision.command_reply" in imports
    assert "command_reply.should_compose_understanding_command_reply(" in source
    assert "command_reply.compose_understanding_command_reply(" in source
    assert "readonly_reply.compose_understanding_command_reply(" not in source


def test_16a_readonly_reply_no_longer_owns_command_reply() -> None:
    source = _source(READONLY_REPLY)

    assert "def should_compose_understanding_command_reply(" not in source
    assert "def compose_understanding_command_reply(" not in source
    assert "def _reply_hint_from_understanding(" not in source


def test_16a_readonly_reply_shrinks_below_command_reply_cut_budget() -> None:
    assert len(_source(READONLY_REPLY).splitlines()) <= 510
