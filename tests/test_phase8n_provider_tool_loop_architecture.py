from __future__ import annotations

import ast
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"


def _source(relative: str) -> str:
    return (SRC / relative).read_text(encoding="utf-8")


def _tree(relative: str) -> ast.Module:
    return ast.parse(_source(relative), filename=relative)


def _imports(relative: str) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(_tree(relative)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def _defined_functions(relative: str) -> dict[str, ast.FunctionDef]:
    return {
        node.name: node
        for node in ast.walk(_tree(relative))
        if isinstance(node, ast.FunctionDef)
    }


def _string_constants(node: ast.AST) -> list[str]:
    return [
        constant.value
        for constant in ast.walk(node)
        if isinstance(constant, ast.Constant) and isinstance(constant.value, str)
    ]


def test_8n_modules_exist() -> None:
    for relative in (
        "llm/legacy_provider.py",
        "llm/legacy_schema_repair.py",
        "llm/legacy_tool_loop.py",
    ):
        assert (SRC / relative).exists(), relative


def test_8n_decision_legacy_imports_provider_repair_and_tool_loop_modules() -> None:
    imports = _imports("llm/decision_legacy.py")

    assert "fitmas.llm.legacy_provider" in imports
    assert "fitmas.llm.legacy_schema_repair" in imports
    assert "fitmas.llm.legacy_tool_loop" in imports


def test_8n_decision_legacy_no_longer_owns_tool_loop_helper_bodies() -> None:
    functions = _defined_functions("llm/decision_legacy.py")

    assert not {
        "_compile_tool_decision_json",
        "_retry_tool_followup_json_format",
        "_tool_result_blocks",
        "_tool_followup_content",
        "_tool_execution_names",
        "_any_tool_called",
        "_all_executed_tools_ok",
        "_all_tool_results_ok",
        "_sum_tool_latency",
        "_tool_errors",
        "_sum_optional_ints",
        "_tool_use_blocks",
        "_log_tool_session_trace",
    }.intersection(functions)


def test_8n_decision_legacy_compatibility_shims_stay_short() -> None:
    functions = _defined_functions("llm/decision_legacy.py")

    for name in (
        "_request_json_with_tools",
        "_repair_invalid_decision_payload",
        "_request_claude_decision_fallback",
        "_repair_decision_json_from_text",
        "_repair_tool_result_summary",
    ):
        assert name in functions
        constants = _string_constants(functions[name])
        assert all(len(value) <= 500 for value in constants), name


def test_8n_new_legacy_modules_do_not_import_runtime_or_app_or_heartbeat_layers() -> None:
    forbidden = {
        "fitmas.conversation_pipeline",
        "fitmas.api",
        "fitmas.api_messages",
        "fitmas.skills.heartbeat",
        "fitmas.skills.heartbeat.heartbeat",
    }
    for relative in (
        "llm/legacy_provider.py",
        "llm/legacy_schema_repair.py",
        "llm/legacy_tool_loop.py",
    ):
        assert not forbidden.intersection(_imports(relative)), relative


def test_8n_retired_planning_cutover_flag_is_not_read() -> None:
    source = _source("legacy/conversation_understanding_bridge.py")

    assert "FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER" not in source


def test_8n_retired_planning_cutover_env_not_forced_on_by_tests() -> None:
    assert os.getenv("FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER") not in {"1", "true", "yes", "on"}
