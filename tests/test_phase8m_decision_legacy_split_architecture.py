from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"


def _source(relative: str) -> str:
    return (SRC / relative).read_text(encoding="utf-8")


def _tree(relative: str) -> ast.Module:
    return ast.parse(_source(relative), filename=relative)


def _defined_classes(relative: str) -> set[str]:
    return {node.name for node in ast.walk(_tree(relative)) if isinstance(node, ast.ClassDef)}


def _defined_functions(relative: str) -> set[str]:
    return {node.name for node in ast.walk(_tree(relative)) if isinstance(node, ast.FunctionDef)}


def _imports(relative: str) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(_tree(relative)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def test_8m_legacy_split_modules_exist() -> None:
    for relative in (
        "llm/legacy_models.py",
        "llm/legacy_parser.py",
        "llm/legacy_prompt.py",
        "llm/legacy_action_compile.py",
    ):
        assert (SRC / relative).exists(), relative


def test_8m_decision_legacy_imports_split_modules() -> None:
    imports = _imports("llm/decision_legacy.py")
    source = _source("llm/decision_legacy.py")

    assert "fitmas.legacy.decision_contracts" in imports
    assert "legacy_parser" in source
    assert "legacy_prompt" in source
    assert "legacy_action_compile" in source


def test_8m_decision_legacy_no_longer_defines_models_parser_or_compilers() -> None:
    assert not {
        "CoachDecision",
        "MutationDecision",
        "HealthSignalAction",
        "AvailabilityConstraintAction",
        "PreferenceSignalAction",
        "ExecutionUpdateAction",
    }.intersection(_defined_classes("llm/decision_legacy.py"))

    assert not {
        "parse_coach_decision_payload",
        "_parse_llm_decision_payload",
        "_normalize_memory_actions",
        "_normalize_execution_actions",
        "_maybe_compile_execution_actions_for_turn",
        "_maybe_compile_memory_actions_for_turn",
        "_compile_memory_actions_for_scope",
        "_maybe_repair_missing_execution_action_from_followup",
        "_maybe_repair_execution_action_consistency",
        "_maybe_repair_missing_availability_memory_action",
    }.intersection(_defined_functions("llm/decision_legacy.py"))


def test_8m_new_legacy_modules_do_not_import_conversation_pipeline() -> None:
    for relative in (
        "llm/legacy_models.py",
        "llm/legacy_parser.py",
        "llm/legacy_prompt.py",
        "llm/legacy_action_compile.py",
    ):
        assert "fitmas.conversation_pipeline" not in _imports(relative)


def test_8m_retired_planning_cutover_flag_is_not_read() -> None:
    source = _source("legacy/conversation_understanding_bridge.py")

    assert "FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER" not in source


def test_8m_smoke_wrapper_exists() -> None:
    script = ROOT / "scripts" / "smoke-decision-runtime-decision-legacy-split"

    assert script.exists()
    source = script.read_text(encoding="utf-8")
    assert "test_phase8m_decision_legacy_split_architecture.py" in source
    assert "smoke-decision-runtime-decide-shrink" in source
