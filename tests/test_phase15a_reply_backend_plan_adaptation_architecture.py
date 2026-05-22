from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "backend" / "src" / "fitmas" / "llm"
REPLY_BACKEND = LLM / "reply_backend.py"
PLAN_ADAPTATION = LLM / "reply_plan_adaptation.py"


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


def test_15a_plan_adaptation_reply_owner_exists() -> None:
    assert PLAN_ADAPTATION.exists()
    functions = _function_names(PLAN_ADAPTATION)

    assert "compose_plan_adaptation_reply" in functions
    assert "build_plan_adaptation_reply_context" in functions


def test_15a_reply_backend_reexports_plan_adaptation_without_owning_it() -> None:
    source = _source(REPLY_BACKEND)
    imports = _imports(REPLY_BACKEND)

    assert "fitmas.llm.reply_plan_adaptation" in imports
    assert "def compose_plan_adaptation_reply(" not in source
    assert "def build_plan_adaptation_reply_context(" not in source
    assert "Decision adaptation:" not in source
    assert "AdaptationPolicyDecision" not in source


def test_15a_plan_adaptation_owner_is_planning_specific() -> None:
    source = _source(PLAN_ADAPTATION)
    imports = _imports(PLAN_ADAPTATION)

    assert "AdaptationPolicyDecision" in source
    assert "BlockedEvent" in source
    assert "fitmas.domain.planning.policy" in imports
    assert "fitmas.decision.grounding" not in imports


def test_15a_reply_backend_shrinks_below_reply_slice_budget() -> None:
    assert len(_source(REPLY_BACKEND).splitlines()) <= 290
