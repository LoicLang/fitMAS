from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"


def _source(relative: str) -> str:
    return (SRC / relative).read_text(encoding="utf-8")


def _backend_python_files() -> list[Path]:
    return sorted((SRC).rglob("*.py"))


def test_9s_coachdecision_runtime_exposes_removed_provider_trace() -> None:
    source = _source("decision/coach_decision_runtime.py")

    assert "def legacy_provider_skip_reason(" in source
    assert "def trace_legacy_provider_skipped(" in source
    assert "coach_decision_provider_removed" in source
    assert "def legacy_provider_allowed_for_turn(" not in source


def test_9s_pipeline_never_calls_legacy_decide_after_canonical_routes() -> None:
    source = _source("conversation_pipeline.py")

    clarification_index = source.index("canonical_provider_clarification_outcome(")
    assert source.index("compose_canonical_clarification_reply(") < clarification_index
    assert source.index("should_use_canonical_understanding_without_legacy(") < clarification_index
    assert source.index("should_use_canonical_readonly_without_legacy(") < clarification_index
    assert source.index("should_use_canonical_planning_without_legacy(") < clarification_index
    assert "run_legacy_coach_decision(" not in source
    assert "canonical_provider_clarification_outcome(" in source


def test_9s_legacy_decide_call_is_removed_from_backend_runtime() -> None:
    offenders: list[str] = []
    for path in _backend_python_files():
        relative = path.relative_to(SRC).as_posix()
        source = path.read_text(encoding="utf-8")
        if "run_legacy_coach_decision(" not in source:
            continue
        offenders.append(relative)

    assert offenders == []


def test_9s_no_direct_decision_legacy_decide_import_outside_llm_package() -> None:
    offenders: list[str] = []
    for path in _backend_python_files():
        relative = path.relative_to(SRC).as_posix()
        if relative in {"llm/__init__.py", "llm/decision_legacy.py"}:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "fitmas.llm.decision_legacy":
                names = {alias.name for alias in node.names}
                if "decide" in names:
                    offenders.append(relative)
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "fitmas.llm.decision_legacy":
                        offenders.append(relative)

    assert offenders == []


def test_9s_canonical_routes_still_precede_removed_provider_clarification() -> None:
    source = _source("conversation_pipeline.py")

    clarification_index = source.index("canonical_provider_clarification_outcome(")
    assert source.index("compose_canonical_clarification_reply(") < clarification_index
    assert source.index("should_use_canonical_understanding_without_legacy(") < clarification_index
    assert source.index("should_use_canonical_readonly_without_legacy(") < clarification_index
    assert source.index("should_use_canonical_planning_without_legacy(") < clarification_index


def test_9s_decision_legacy_is_marked_provider_compat_only() -> None:
    source = _source("llm/decision_legacy.py")

    assert "Legacy CoachDecision provider compatibility only." in source
    assert "Do not add new conversation runtime authority here." in source
