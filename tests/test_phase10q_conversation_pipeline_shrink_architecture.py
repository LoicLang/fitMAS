from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"


PLAN_PATCH_REPLY_HELPERS = {
    "_applied_plan_patch_reply",
    "_blocked_mutation_reply",
    "_blocked_plan_patch_reply",
    "_build_plan_patch_clarification_prompt",
    "_build_plan_patch_confirmation_prompt",
    "_execution_applied_patch_blocked_reply",
    "_log_plan_patch_blocked",
    "_plan_patch_confirmation_reply_requests_clarification",
    "_plan_patch_confirmation_summary",
    "_plan_patch_needs_confirmation",
    "_plan_patch_pending_reason",
    "_plan_patch_pending_summary",
    "_plan_patch_service_result_requires_clarification",
}


def _source(relative: str) -> str:
    return (SRC / relative).read_text(encoding="utf-8")


def _function_names(relative: str) -> set[str]:
    tree = ast.parse(_source(relative), filename=relative)
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _imports(relative: str) -> set[str]:
    tree = ast.parse(_source(relative), filename=relative)
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def test_10q_plan_patch_reply_helpers_live_in_decision_owner() -> None:
    assert (SRC / "decision" / "plan_patch_reply.py").exists()

    pipeline_functions = _function_names("decision/conversation_pipeline.py")
    reply_functions = _function_names("decision/plan_patch_reply.py")

    assert PLAN_PATCH_REPLY_HELPERS.isdisjoint(pipeline_functions)
    assert PLAN_PATCH_REPLY_HELPERS.issubset(reply_functions)


def test_10q_conversation_pipeline_does_not_import_plan_patch_reply_internals() -> None:
    imports = _imports("decision/conversation_pipeline.py")
    prompt_context_imports = _imports("decision/turn_prompt_context.py")

    assert "fitmas.decision.plan_patch_reply" in prompt_context_imports
    assert "fitmas.decision.plan_patch_reply" not in imports
    assert "fitmas.domain.planning.patch_mutation_service.PlanPatchServiceResult" not in imports
    assert "fitmas.domain.planning.plan_patch.PlanPatch" not in imports
    assert "re" not in imports


def test_10q_plan_patch_reply_owner_does_not_depend_on_conversation_pipeline() -> None:
    imports = _imports("decision/plan_patch_reply.py")

    assert "fitmas.decision.conversation_pipeline" not in imports


def test_10q_conversation_pipeline_shrinks_below_next_budget() -> None:
    assert len(_source("decision/conversation_pipeline.py").splitlines()) <= 1500
