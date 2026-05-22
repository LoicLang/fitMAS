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


def test_8j_has_dedicated_canonical_planning_wrapper() -> None:
    script = ROOT / "scripts" / "smoke-decision-runtime-canonical-planning"

    assert script.exists()
    source = script.read_text(encoding="utf-8")
    assert "FITMAS_UNDERSTANDING_RUNTIME_SHADOW=1" in source
    assert "FITMAS_COMMANDS_FROM_UNDERSTANDING=1" in source
    assert "FITMAS_PENDING_FROM_UNDERSTANDING=1" in source
    assert "FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER" not in source
    assert "FITMAS_CANONICAL_PLANNING_PROVIDER" in source
    assert "move_easy_then_confirm" in source
    assert "swap_by_day" in source
    assert "lighten_tomorrow" in source
    assert "replace_swim_with_bike" in source
    assert "future_evening_unavailable" in source
    assert "fatigue_tomorrow" in source
    assert "avoid_back_to_back" in source
    assert "swim_unavailable_two_weeks" in source
    assert "confirm_without_pending" in source


def test_8j_keeps_8i_wrapper_without_planning_cutover() -> None:
    source = (ROOT / "scripts" / "smoke-decision-runtime-canonical-flags").read_text(encoding="utf-8")

    assert "FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER=1" not in source


def test_8j_retired_planning_cutover_flag_is_not_read() -> None:
    bridge = _source("decision/understanding_runtime.py")

    assert "FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER" not in bridge


def test_8j_decision_package_stays_pure() -> None:
    forbidden = {
        "fitmas.legacy",
        "fitmas.llm",
        "fitmas.conversation_pipeline",
        "fitmas.domain.memory.mutation_service",
        "fitmas.domain.execution.mutation_service",
        "fitmas.plan_mutation_service",
    }
    for path in (SRC / "decision").glob("*.py"):
        if path.name in {"command_application.py", "no_change_reply.py", "readonly_reply.py", "understanding_runtime.py", "coach_decision_runtime.py"}:
            continue
        imports = _imports(f"decision/{path.name}")
        assert not forbidden.intersection(imports), f"{path.name}: {forbidden.intersection(imports)}"
