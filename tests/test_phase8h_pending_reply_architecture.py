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


def test_8h_pending_bridge_no_longer_uses_legacy_decision_message_for_visible_reply() -> None:
    source = _source("legacy/conversation_pending_bridge.py")

    assert "pending_reply_adapter" in source
    assert "_decision_reply(" not in source
    assert "fitmas_message" not in source
    assert "La proposition reste en attente" not in source
    assert "Je ne l'applique pas" not in source


def test_8h_pending_reply_adapter_owns_pending_decision_outcomes() -> None:
    source = _source("legacy/pending_reply_adapter.py")
    imports = _imports("legacy/pending_reply_adapter.py")

    assert "PendingReplyMode" in source
    assert "def pending_reply_outcome" in source
    assert "def compose_pending_reply" in source
    assert "DecisionOutcome" in source
    assert "DecisionReplyComposer" in source
    assert "fitmas.conversation_pipeline" not in imports
    assert "fitmas.final_reply" not in imports
    assert "fitmas.llm" not in imports


def test_8h_decision_package_stays_pure() -> None:
    forbidden = {
        "fitmas.legacy",
        "fitmas.llm",
        "fitmas.final_reply",
        "fitmas.conversation_pipeline",
    }
    for path in (SRC / "decision").glob("*.py"):
        imports = _imports(f"decision/{path.name}")
        assert not forbidden.intersection(imports), f"{path.name}: {forbidden.intersection(imports)}"
