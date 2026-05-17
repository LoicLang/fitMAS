from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"


def _source(relative: str) -> str:
    return (SRC / relative).read_text(encoding="utf-8")


def _imports(relative: str) -> set[str]:
    tree = ast.parse((SRC / relative).read_text(encoding="utf-8"), filename=relative)
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def _function_defs(relative: str) -> set[str]:
    tree = ast.parse((SRC / relative).read_text(encoding="utf-8"), filename=relative)
    return {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}


def test_8g_conversation_pipeline_delegates_pending_resolution() -> None:
    source = _source("conversation_pipeline.py")
    functions = _function_defs("conversation_pipeline.py")

    forbidden_helpers = {
        "_apply_pending_resolution",
        "_verify_pending_accept_resolution",
        "_accept_pending_confirmation",
        "_accept_pending_plan_patch_choice",
        "_pending_accept_recheck_blocked_outcome",
        "_pending_confirmation_unavailable_outcome",
        "_outcome_keeps_pending_confirmation",
        "_keep_pending_for_non_mutating_turn",
    }

    assert not forbidden_helpers.intersection(functions)
    assert "conversation_pending_bridge" in source
    assert "decision.pending_resolution" not in source


def test_8g_pending_bridge_owns_pending_application_boundary() -> None:
    source = _source("legacy/conversation_pending_bridge.py")
    imports = _imports("legacy/conversation_pending_bridge.py")

    assert "def apply_pending_resolution" in source
    assert "def verify_pending_accept_resolution" in source
    assert "def accept_pending_confirmation" in source
    assert "def keep_pending_for_non_mutating_turn" in source
    assert "def supersede_pending_if_replaced" in source
    assert "pending_resolution_from_sources" in source
    assert "FITMAS_PENDING_FROM_UNDERSTANDING" in source
    assert "fitmas.conversation_pipeline" not in imports
    assert "fitmas.decision" in imports
    assert "fitmas.plan_mutation_service" in imports


def test_8g_pending_bridge_does_not_parse_free_user_text_deterministically() -> None:
    source = _source("legacy/conversation_pending_bridge.py")

    assert "re.search" not in source
    assert "re.findall" not in source
    assert ".lower() == \"oui\"" not in source
    assert ".lower() == 'oui'" not in source
    assert "startswith(\"oui\")" not in source
    assert "startswith('oui')" not in source


def test_8g_decision_package_stays_pure() -> None:
    forbidden = {
        "fitmas.legacy",
        "fitmas.llm",
        "fitmas.plan_mutation_service",
        "fitmas.conversation_pipeline",
    }
    for path in (SRC / "decision").glob("*.py"):
        imports = _imports(f"decision/{path.name}")
        assert not forbidden.intersection(imports), f"{path.name}: {forbidden.intersection(imports)}"
