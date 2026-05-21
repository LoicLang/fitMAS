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


def test_8f_conversation_pipeline_no_longer_imports_action_writers() -> None:
    source = _source("decision/turn_router.py")
    imports = _imports("decision/turn_router.py")

    assert "fitmas.memory_mutation_service" not in imports
    assert "fitmas.execution_mutation_service" not in imports
    assert "apply_memory_actions_for_user" not in source
    assert "apply_execution_actions_for_user" not in source
    assert "command_application" in source


def test_8f_command_application_is_the_only_conversation_action_application_boundary() -> None:
    source = _source("decision/command_application.py")
    imports = _imports("decision/command_application.py")

    assert "apply_coach_decision_commands" in source
    assert "apply_turn_plan_memory_commands" in source
    assert "RuntimeCommandBus" in source
    assert "fitmas.conversation_pipeline" not in imports
    assert "fitmas.memory_mutation_service" in imports
    assert "fitmas.execution_mutation_service" in imports


def test_8f_deleted_legacy_command_bridges_do_not_return() -> None:
    assert not (SRC / "legacy/conversation_command_bridge.py").exists()
    assert not (SRC / "legacy/conversation_command_bus.py").exists()

def test_8f_command_mapping_does_not_write_or_parse_user_text() -> None:
    source = _source("decision/command_mapping.py")
    imports = _imports("decision/command_mapping.py")

    assert "commands_from_legacy_decision" in source
    assert "commands_from_understanding" in source
    assert "fitmas.decision" in imports
    assert "fitmas.memory_mutation_service" not in imports
    assert "fitmas.execution_mutation_service" not in imports
    assert ".commit(" not in source
    assert "re.search" not in source
    assert "regex" not in source.lower()


def test_8f_decision_package_stays_pure() -> None:
    forbidden = {
        "fitmas.legacy",
        "fitmas.llm",
        "fitmas.memory_mutation_service",
        "fitmas.execution_mutation_service",
        "fitmas.conversation_pipeline",
    }
    for path in (SRC / "decision").glob("*.py"):
        if path.name in {"command_application.py", "readonly_reply.py", "understanding_runtime.py", "coach_decision_runtime.py"}:
            continue
        imports = _imports(f"decision/{path.name}")
        assert not forbidden.intersection(imports), f"{path.name}: {forbidden.intersection(imports)}"
