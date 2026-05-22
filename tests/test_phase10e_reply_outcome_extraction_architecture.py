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


def test_10e_b_planning_reply_outcome_lives_in_decision() -> None:
    source = _source("decision/planning_outcomes.py")

    for marker in (
        "def planning_decision_to_outcome",
        "def plan_patch_service_result_to_outcome",
        "def canonical_planning_blocked_outcome",
        "def conversation_outcome_from_planning_runtime_result",
    ):
        assert marker in source

    assert "fitmas.legacy" not in source


def test_10e_b_pending_reply_lives_in_decision() -> None:
    source = _source("decision/pending_reply.py")

    assert "def compose_pending_reply" in source
    assert "def pending_reply_outcome" in source
    assert "fitmas.legacy" not in source


def test_10e_b_runtime_no_longer_imports_legacy_reply_outcome_adapters() -> None:
    banned = {
        "fitmas.legacy.conversation_planning_bridge",
        "fitmas.legacy.planning_outcome_adapter",
        "fitmas.legacy.plan_patch_reply_adapter",
        "fitmas.legacy.pending_reply_adapter",
    }
    offenders: list[str] = []

    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        if rel in {
            "legacy/conversation_planning_bridge.py",
            "legacy/planning_outcome_adapter.py",
            "legacy/plan_patch_reply_adapter.py",
            "legacy/pending_reply_adapter.py",
        }:
            continue
        imported = set(_imports(rel))
        if imported & banned:
            offenders.append(f"{rel}: {sorted(imported & banned)}")

    assert offenders == []
