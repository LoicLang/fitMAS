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


def test_8k_defaults_commands_and_pending_from_understanding_on() -> None:
    command_bridge = _source("legacy/conversation_command_bridge.py")
    pending_bridge = _source("legacy/conversation_pending_bridge.py")

    assert 'FITMAS_COMMANDS_FROM_UNDERSTANDING", default=True' in command_bridge
    assert 'FITMAS_PENDING_FROM_UNDERSTANDING", default=True' in pending_bridge
    assert "return _env_flag_enabled(" in command_bridge
    assert "return _env_flag_enabled(" in pending_bridge


def test_8k_keeps_planning_cutover_default_off() -> None:
    understanding = _source("legacy/conversation_understanding_bridge.py")

    assert 'FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER", default=False' in understanding


def test_8k_has_scoped_non_planning_understanding_gate() -> None:
    understanding = _source("legacy/conversation_understanding_bridge.py")

    assert "FITMAS_CANONICAL_NON_PLANNING_CUTOVER" in understanding
    assert "def should_run_canonical_understanding(" in understanding
    assert "pending_confirmation" in understanding
    assert "_turn_plan_can_produce_non_planning_commands" in understanding


def test_8k_default_smoke_wrapper_proves_defaults_without_exporting_command_or_pending_flags() -> None:
    script = ROOT / "scripts" / "smoke-decision-runtime-canonical-defaults"

    assert script.exists()
    source = script.read_text(encoding="utf-8")
    assert "FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER=0" in source
    assert "FITMAS_COMMANDS_FROM_UNDERSTANDING=1" not in source
    assert "FITMAS_PENDING_FROM_UNDERSTANDING=1" not in source
    assert "smoke-real-conversations" in source
    assert "smoke-a-plus-api" in source


def test_8k_decision_package_stays_pure() -> None:
    forbidden = {
        "fitmas.legacy",
        "fitmas.llm",
        "fitmas.conversation_pipeline",
        "fitmas.memory_mutation_service",
        "fitmas.execution_mutation_service",
        "fitmas.plan_mutation_service",
    }
    for path in (SRC / "decision").glob("*.py"):
        imports = _imports(f"decision/{path.name}")
        assert not forbidden.intersection(imports), f"{path.name}: {forbidden.intersection(imports)}"
