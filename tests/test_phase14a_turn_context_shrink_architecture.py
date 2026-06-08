from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DECISION = ROOT / "backend" / "src" / "fitmas" / "decision"

PROMPT_CONTEXT_HELPERS = {
    "adaptation_context_for_prompt",
    "append_prompt_section",
    "availability_context_for_prompt",
    "pending_confirmation_context_for_prompt",
    "should_route_adaptation_context_to_llm",
    "should_route_availability_context_to_llm",
}

PAYLOAD_HELPERS = {
    "build_reply_grounding_packet",
    "fact_identity",
    "turn_plan_payload",
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
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def test_14a_turn_prompt_context_owner_contains_prompt_helpers() -> None:
    path = DECISION / "turn_prompt_context.py"

    assert path.exists()
    assert PROMPT_CONTEXT_HELPERS.issubset(_function_names(path))


def test_14a_turn_context_payload_owner_contains_trace_helpers() -> None:
    path = DECISION / "turn_context_payload.py"

    assert path.exists()
    assert PAYLOAD_HELPERS.issubset(_function_names(path))


def test_14a_turn_context_no_longer_defines_extracted_helpers() -> None:
    functions = _function_names(DECISION / "turn_context.py")

    assert PROMPT_CONTEXT_HELPERS.isdisjoint(functions)
    assert PAYLOAD_HELPERS.isdisjoint(functions)


def test_14a_turn_context_imports_extracted_context_owners() -> None:
    imports = _imports(DECISION / "turn_context.py")

    assert "fitmas.legacy.decision.turn_prompt_context" in imports
    assert "fitmas.legacy.decision.turn_context_payload" in imports


def test_14a_turn_context_stays_under_next_shrink_budget() -> None:
    assert len(_source(DECISION / "turn_context.py").splitlines()) <= 300
