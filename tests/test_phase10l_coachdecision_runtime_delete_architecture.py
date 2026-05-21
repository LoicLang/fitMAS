from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"


def _source(relative: str) -> str:
    return (SRC / relative).read_text(encoding="utf-8")


def _imports(relative: str) -> set[str]:
    modules: set[str] = set()
    tree = ast.parse(_source(relative), filename=relative)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def _backend_files() -> list[Path]:
    return sorted(SRC.rglob("*.py"))


def test_10l_understanding_runtime_no_longer_builds_coachdecision_artifacts() -> None:
    source = _source("decision/understanding_runtime.py")
    imports = _imports("decision/understanding_runtime.py")

    assert "fitmas.legacy.coach_decision_artifact" not in imports
    assert "LegacyCoachDecisionArtifact" not in source
    assert "coach_decision_artifact_from_understanding" not in source
    assert "trace_canonical_provider_artifact" not in source


def test_10l_conversation_pipeline_has_no_coachdecision_artifact_branch() -> None:
    source = _source("conversation_pipeline.py")

    assert "legacy_decision_artifact" not in source
    assert "is_coach_decision_artifact" not in source
    assert "is_legacy_readonly_artifact" not in source
    assert "coach_decision_payload" not in source
    assert "legacy_readonly_decision_payload" not in source
    assert "legacy_decision_reply_text" not in source


def test_10l_runtime_no_longer_imports_legacy_decision_provider_module() -> None:
    offenders: list[str] = []
    allowed = {
        "llm/decision_legacy.py",
        "llm/legacy_action_compile.py",
        "llm/legacy_parser.py",
        "llm/legacy_tool_loop.py",
        "legacy/coach_understanding_adapter.py",
    }
    for path in _backend_files():
        relative = path.relative_to(SRC).as_posix()
        if relative in allowed:
            continue
        imports = _imports(relative)
        if "fitmas.llm.decision_legacy" in imports:
            offenders.append(relative)

    assert offenders == []
