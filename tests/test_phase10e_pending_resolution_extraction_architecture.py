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


def test_10e_pending_resolution_lives_in_decision_without_legacy_or_llm_imports() -> None:
    source = _source("decision/pending_resolution.py")
    imports = _imports("decision/pending_resolution.py")

    assert "class PendingResolutionArtifact" in source
    assert "def apply_pending_resolution(" in source
    assert "def verify_pending_accept_resolution(" in source
    assert "def keep_pending_for_non_mutating_turn(" in source
    assert "def supersede_pending_if_replaced(" in source
    assert not any(module.startswith("fitmas.legacy") for module in imports)
    assert not any(module.startswith("fitmas.llm") for module in imports)


def test_10e_runtime_uses_decision_pending_resolution_not_legacy_bridge() -> None:
    runtime_sources = {
        "decision/turn_router.py": _source("decision/turn_router.py"),
        "decision/command_application.py": _source("decision/command_application.py"),
    }

    for source in runtime_sources.values():
        assert "decision import pending_resolution" in source
        assert "legacy import conversation_pending_bridge" not in source
