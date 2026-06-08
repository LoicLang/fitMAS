from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DECISION = ROOT / "backend" / "src" / "fitmas" / "decision"
READONLY_REPLY = DECISION / "readonly_reply.py"
READONLY_GROUNDING = DECISION / "readonly_grounding.py"


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


def test_16c_readonly_grounding_owner_exists() -> None:
    assert READONLY_GROUNDING.exists()
    functions = _function_names(READONLY_GROUNDING)

    assert "answer_outcome_from_understanding" in functions
    assert "grounded_readonly_fallback" in functions
    assert "plan_lookup_reply_mentions_plan_truth" in functions
    assert "_humanize_plan_window_line" in functions


def test_16c_readonly_reply_uses_grounding_owner() -> None:
    source = _source(READONLY_REPLY)
    imports = _imports(READONLY_REPLY)

    assert "fitmas.legacy.decision.readonly_grounding" in imports
    assert "readonly_grounding.answer_outcome_from_understanding(" in source
    assert "readonly_grounding.grounded_readonly_fallback(" in source
    assert "readonly_grounding.plan_lookup_reply_mentions_plan_truth(" in source


def test_16c_readonly_reply_no_longer_owns_grounding_fallbacks() -> None:
    source = _source(READONLY_REPLY)
    imports = _imports(READONLY_REPLY)

    assert "def _answer_outcome_from_understanding(" not in source
    assert "def _grounded_readonly_fallback(" not in source
    assert "def _humanize_plan_window_line(" not in source
    assert "def _plan_lookup_reply_mentions_plan_truth(" not in source
    assert "fitmas.legacy.domain.coaching.coach_voice" not in imports
    assert "DecisionOutcome" not in source
    assert "ReplyContract" not in source


def test_16c_readonly_reply_shrinks_below_grounding_cut_budget() -> None:
    assert len(_source(READONLY_REPLY).splitlines()) <= 210
