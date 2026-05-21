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


def test_8i_canonical_flags_exist_and_match_current_default_policy() -> None:
    understanding = _source("decision/understanding_runtime.py")
    commands = _source("decision/command_application.py")
    pending = _source("decision/pending_resolution.py")

    assert "FITMAS_UNDERSTANDING_RUNTIME_SHADOW" in understanding
    assert "FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER" not in understanding
    assert "FITMAS_COMMANDS_FROM_UNDERSTANDING" in commands
    assert "FITMAS_PENDING_FROM_UNDERSTANDING" in pending
    assert 'FITMAS_UNDERSTANDING_RUNTIME_SHADOW", default=False' in understanding
    assert 'FITMAS_COMMANDS_FROM_UNDERSTANDING", default=True' in commands
    assert 'FITMAS_PENDING_FROM_UNDERSTANDING", default=True' in pending


def test_8i_dogfood_smoke_wrapper_exists() -> None:
    script = ROOT / "scripts" / "smoke-decision-runtime-canonical-flags"

    assert script.exists()
    source = script.read_text(encoding="utf-8")
    assert "FITMAS_UNDERSTANDING_RUNTIME_SHADOW=1" in source
    assert "FITMAS_COMMANDS_FROM_UNDERSTANDING=1" in source
    assert "FITMAS_PENDING_FROM_UNDERSTANDING=1" in source
    assert "FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER=1" not in source
    assert "smoke-real-conversations" in source
    assert "smoke-a-plus-api" in source


def test_8i_decision_package_stays_pure() -> None:
    forbidden = {
        "fitmas.legacy",
        "fitmas.llm",
        "fitmas.conversation_pipeline",
        "fitmas.memory_mutation_service",
        "fitmas.execution_mutation_service",
        "fitmas.plan_mutation_service",
    }
    for path in (SRC / "decision").glob("*.py"):
        if path.name in {"command_application.py", "readonly_reply.py", "understanding_runtime.py", "coach_decision_runtime.py"}:
            continue
        imports = _imports(f"decision/{path.name}")
        assert not forbidden.intersection(imports), f"{path.name}: {forbidden.intersection(imports)}"
