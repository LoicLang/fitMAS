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


def test_8l_conversation_pipeline_does_not_call_decide_directly() -> None:
    source = _source("conversation_pipeline.py")

    assert "dependencies.decide(" not in source
    assert "dependencies.decide" not in source
    assert "llm_runtime" not in source
    assert "coach_decision_runtime.run_legacy_coach_decision" not in source


def test_8l_conversation_pipeline_does_not_read_fitmas_message_directly() -> None:
    source = _source("conversation_pipeline.py")

    assert "decision.fitmas_message" not in source
    assert "readonly_reply.compose_understanding_command_reply" in source


def test_8l_legacy_provider_boundary_is_removed() -> None:
    runtime = _source("decision/coach_decision_runtime.py")

    assert not (SRC / "legacy/coach_decision_provider.py").exists()
    assert "def run_legacy_coach_decision(" not in runtime
    assert "def build_legacy_coach_decision_request(" not in runtime
    assert "canonical_provider_clarification_outcome" in runtime


def test_8l_decision_package_stays_pure() -> None:
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


def test_8l_retired_planning_cutover_flag_is_not_read() -> None:
    source = _source("decision/understanding_runtime.py")

    assert "FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER" not in source


def test_8l_smoke_wrapper_exists() -> None:
    script = ROOT / "scripts" / "smoke-decision-runtime-decide-shrink"

    assert script.exists()
    source = script.read_text(encoding="utf-8")
    assert "smoke-decision-runtime-canonical-defaults" in source
    assert "smoke-decision-runtime-canonical-planning" in source
    assert "test-backend -q" in source
