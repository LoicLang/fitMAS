from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "backend" / "src" / "fitmas" / "llm"
REPLY_BACKEND = LLM / "reply_backend.py"
CLOSE_TURN = LLM / "reply_close_turn.py"


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


def test_15b_close_turn_reply_owner_exists() -> None:
    assert CLOSE_TURN.exists()
    functions = _function_names(CLOSE_TURN)

    assert "compose_close_turn_reply" in functions
    assert "_close_turn_context" in functions


def test_15b_reply_backend_reexports_close_turn_without_owning_it() -> None:
    source = _source(REPLY_BACKEND)
    imports = _imports(REPLY_BACKEND)

    assert "fitmas.legacy.llm.reply_close_turn" in imports
    assert "def compose_close_turn_reply(" not in source
    assert "def _close_turn_context(" not in source
    assert "Intent: terminal_close" not in source


def test_15b_close_turn_owner_stays_terminal_social_specific() -> None:
    source = _source(CLOSE_TURN)
    imports = _imports(CLOSE_TURN)

    assert "Intent: terminal_close" in source
    assert "verify_close_turn_reply" in source
    assert "fitmas.legacy.domain.planning.policy" not in imports
    assert "fitmas.legacy.decision.output_verifier" not in imports


def test_15b_reply_backend_shrinks_below_close_turn_slice_budget() -> None:
    assert len(_source(REPLY_BACKEND).splitlines()) <= 220
