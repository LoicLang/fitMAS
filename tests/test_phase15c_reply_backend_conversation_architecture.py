from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "backend" / "src" / "fitmas" / "llm"
REPLY_BACKEND = LLM / "reply_backend.py"
REPLY_CONVERSATION = LLM / "reply_conversation.py"


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


def test_15c_conversation_reply_owner_exists() -> None:
    assert REPLY_CONVERSATION.exists()
    functions = _function_names(REPLY_CONVERSATION)

    assert "compose_no_change_reply" in functions
    assert "compose_execution_report_reply" in functions
    assert "compose_plan_lookup_reply" in functions


def test_15c_reply_backend_reexports_conversation_replies_without_owning_them() -> None:
    source = _source(REPLY_BACKEND)
    imports = _imports(REPLY_BACKEND)

    assert "fitmas.legacy.llm.reply_conversation" in imports
    assert "def compose_no_change_reply(" not in source
    assert "def compose_execution_report_reply(" not in source
    assert "def compose_plan_lookup_reply(" not in source
    assert "Response type: no_change" not in source
    assert "Response type: execution_report" not in source
    assert "Response type: plan_lookup" not in source


def test_15c_conversation_reply_owner_stays_conversation_specific() -> None:
    source = _source(REPLY_CONVERSATION)
    imports = _imports(REPLY_CONVERSATION)

    assert "Response type: no_change" in source
    assert "Response type: execution_report" in source
    assert "Response type: plan_lookup" in source
    assert "fitmas.legacy.decision.grounding" in imports
    assert "fitmas.legacy.domain.planning.policy" not in imports


def test_15c_reply_backend_shrinks_below_core_facade_budget() -> None:
    assert len(_source(REPLY_BACKEND).splitlines()) <= 140
