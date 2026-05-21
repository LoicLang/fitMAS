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
    assert "llm_runtime" not in source
    assert "conversation_decide_bridge.run_legacy_coach_decision" in source


def test_8l_conversation_pipeline_does_not_read_fitmas_message_directly() -> None:
    source = _source("conversation_pipeline.py")

    assert "decision.fitmas_message" not in source
    assert "readonly_reply.compose_coach_decision_reply" in source


def test_8l_legacy_provider_boundary_exists() -> None:
    provider = _source("legacy/coach_decision_provider.py")
    bridge = _source("legacy/conversation_decide_bridge.py")

    assert "class CoachDecisionRequest" in provider
    assert "class CoachDecisionResult" in provider
    assert "class LegacyCoachDecisionProvider" in provider
    assert "def run_legacy_coach_decision(" in bridge
    assert "clear_last_decide_none" in provider


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
        if path.name in {"command_application.py", "readonly_reply.py"}:
            continue
        imports = _imports(f"decision/{path.name}")
        assert not forbidden.intersection(imports), f"{path.name}: {forbidden.intersection(imports)}"


def test_8l_retired_planning_cutover_flag_is_not_read() -> None:
    source = _source("legacy/conversation_understanding_bridge.py")

    assert "FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER" not in source


def test_8l_smoke_wrapper_exists() -> None:
    script = ROOT / "scripts" / "smoke-decision-runtime-decide-shrink"

    assert script.exists()
    source = script.read_text(encoding="utf-8")
    assert "smoke-decision-runtime-canonical-defaults" in source
    assert "smoke-decision-runtime-canonical-planning" in source
    assert "test-backend -q" in source
