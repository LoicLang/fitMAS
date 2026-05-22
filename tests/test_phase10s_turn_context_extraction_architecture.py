from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"
DECISION = SRC / "decision"
PIPELINE = SRC / "conversation_pipeline.py"

PIPELINE_CONTEXT_HELPERS_TO_REMOVE = {
    "_adaptation_context_for_prompt",
    "_append_prompt_section",
    "_availability_context_for_prompt",
    "_build_reply_grounding_packet",
    "_fact_identity",
    "_pending_confirmation_context_for_prompt",
    "_planning_context_from_turn_state",
    "_should_route_adaptation_context_to_llm",
    "_should_route_availability_context_to_llm",
    "_turn_plan_payload",
}

PIPELINE_CONTEXT_IMPORTS_TO_REMOVE = {
    "fitmas.coach_reading_digest",
    "fitmas.coach_state_bundle",
    "fitmas.conversation_context",
    "fitmas.domain.execution.clarification",
    "fitmas.grounding_contract",
    "fitmas.domain.memory.profile_summary",
    "fitmas.signals",
}


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
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
            imports.update(f"{node.module}.{alias.name}" for alias in node.names)
    return imports


def test_10s_turn_context_owner_exists_under_decision() -> None:
    assert (DECISION / "turn_context.py").exists()


def test_10s_conversation_pipeline_no_longer_defines_context_helpers() -> None:
    assert PIPELINE_CONTEXT_HELPERS_TO_REMOVE.isdisjoint(_function_names(PIPELINE))


def test_10s_conversation_pipeline_imports_turn_context_owner() -> None:
    imports = _imports(PIPELINE)

    assert "fitmas.decision.turn_context" in imports


def test_10s_conversation_pipeline_no_longer_imports_context_builders_directly() -> None:
    imports = _imports(PIPELINE)

    assert PIPELINE_CONTEXT_IMPORTS_TO_REMOVE.isdisjoint(imports)


def test_10s_turn_context_owner_does_not_import_conversation_pipeline() -> None:
    imports = _imports(DECISION / "turn_context.py")

    assert "fitmas.conversation_pipeline" not in imports


def test_10s_conversation_pipeline_shrinks_below_context_budget() -> None:
    assert len(_source(PIPELINE).splitlines()) <= 900
