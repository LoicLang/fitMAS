from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"
DECISION = SRC / "decision"
PIPELINE = SRC / "decision" / "conversation_pipeline.py"

PIPELINE_ROUTER_IMPORTS_TO_REMOVE = {
    "fitmas.decision.activity_highlight",
    "fitmas.decision.clarification_reply",
    "fitmas.decision.coach_decision_runtime",
    "fitmas.decision.command_application",
    "fitmas.decision.pending_resolution",
    "fitmas.decision.planning_runtime",
    "fitmas.decision.readonly_reply",
    "fitmas.decision.understanding_runtime",
    "fitmas.llm.gateway",
    "fitmas.llm.reply_backend",
    "fitmas.llm.reply_decision_backend",
}


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _imports(path: Path) -> set[str]:
    tree = ast.parse(_source(path), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
            imports.update(f"{node.module}.{alias.name}" for alias in node.names)
    return imports


def test_10v_turn_router_owner_exists_under_decision() -> None:
    assert (DECISION / "turn_router.py").exists()


def test_10v_conversation_pipeline_imports_turn_router_owner() -> None:
    assert "fitmas.decision.turn_router" in _imports(PIPELINE)


def test_10v_conversation_pipeline_no_longer_imports_router_dependencies_directly() -> None:
    imports = _imports(PIPELINE)

    assert PIPELINE_ROUTER_IMPORTS_TO_REMOVE.isdisjoint(imports)


def test_10v_turn_router_owner_does_not_import_conversation_pipeline() -> None:
    imports = _imports(DECISION / "turn_router.py")

    assert "fitmas.conversation_pipeline" not in imports


def test_10v_conversation_pipeline_shrinks_below_router_budget() -> None:
    assert len(_source(PIPELINE).splitlines()) <= 140
