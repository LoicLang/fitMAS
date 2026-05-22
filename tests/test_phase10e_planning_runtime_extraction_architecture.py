from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"


def _source(rel: str) -> str:
    return (SRC / rel).read_text(encoding="utf-8")


def _imports(rel: str) -> list[str]:
    tree = ast.parse(_source(rel), filename=rel)
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
        elif isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
    return modules


def test_10e_c_planning_runtime_lives_in_decision_without_legacy_imports() -> None:
    source = _source("decision/planning_runtime.py")

    for marker in (
        "def should_prepare_canonical_planning_understanding",
        "def planning_understanding_for_provider",
        "def should_use_canonical_planning_without_legacy",
        "def handle_canonical_planning",
        "def run_planning_runtime_attempt_from_understanding",
    ):
        assert marker in source

    assert "fitmas.legacy" not in source


def test_10e_c_runtime_no_longer_imports_legacy_planning_runtime_bridge() -> None:
    banned = {
        "fitmas.legacy.conversation_canonical_planning_bridge",
        "fitmas.legacy.planning_runtime_adapter",
    }
    offenders: list[str] = []

    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        if rel in {
            "legacy/conversation_canonical_planning_bridge.py",
            "legacy/planning_runtime_adapter.py",
        }:
            continue
        imported = set(_imports(rel))
        if imported & banned:
            offenders.append(f"{rel}: {sorted(imported & banned)}")

    assert offenders == []
