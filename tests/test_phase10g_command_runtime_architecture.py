from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"


def _source(relative: str) -> str:
    return (SRC / relative).read_text(encoding="utf-8")


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


def test_10g_conversation_pipeline_uses_canonical_command_application() -> None:
    pipeline = _source("conversation_pipeline.py")

    assert "from fitmas.decision import command_application" in pipeline
    assert "conversation_command_bridge" not in pipeline
    assert not (SRC / "legacy/conversation_command_bridge.py").exists()
    assert not (SRC / "legacy/conversation_command_bus.py").exists()


def test_10g_command_application_is_the_only_conversation_command_writer() -> None:
    source = _source("decision/command_application.py")
    imports = _imports("decision/command_application.py")

    assert "class RuntimeCommandBus" in source
    assert "def apply_coach_decision_commands(" in source
    assert "def apply_turn_plan_memory_commands(" in source
    assert "fitmas.memory_mutation_service" in imports
    assert "fitmas.execution_mutation_service" in imports
    assert "fitmas.legacy" not in imports
    assert "fitmas.conversation_pipeline" not in imports


def test_10g_command_mapping_is_canonical_and_legacy_free() -> None:
    source = _source("decision/command_mapping.py")
    imports = _imports("decision/command_mapping.py")

    assert "def commands_from_understanding(" in source
    assert "def commands_from_legacy_decision(" in source
    assert "def memory_action_from_command(" in source
    assert "def execution_action_from_command(" in source
    assert "fitmas.legacy" not in imports
    assert "fitmas.memory_mutation_service" not in imports
    assert "fitmas.execution_mutation_service" not in imports


def test_10g_action_contracts_are_not_owned_by_legacy_decision_contracts() -> None:
    actions = _source("decision/command_actions.py")
    legacy_contracts = _source("legacy/decision_contracts.py")

    assert "class AvailabilityConstraintAction" in actions
    assert "class ExecutionUpdateAction" in actions
    assert "from fitmas.decision.command_actions import" in legacy_contracts
    assert "class AvailabilityConstraintAction" not in legacy_contracts
    assert "class ExecutionUpdateAction" not in legacy_contracts


def test_10g_legacy_coach_command_adapter_is_only_compat_reexport() -> None:
    adapter = _source("legacy/coach_command_adapter.py")

    assert "from fitmas.decision.command_mapping import" in adapter
    assert "def commands_from_understanding(" not in adapter
    assert "def commands_from_legacy_decision(" not in adapter
    assert "memory_mutation_service" not in adapter
    assert "execution_mutation_service" not in adapter
