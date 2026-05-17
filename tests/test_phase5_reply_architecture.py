from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FITMAS = ROOT / "backend" / "src" / "fitmas"
DECISION = FITMAS / "decision"
LEGACY = FITMAS / "legacy"
CONVERSATION = FITMAS / "conversation_pipeline.py"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_decision_reply_modules_do_not_import_legacy_final_reply() -> None:
    offenders = []
    for path in sorted(DECISION.glob("*.py")):
        imports = _imports(path)
        if "fitmas.final_reply" in imports or "fitmas.legacy" in imports:
            offenders.append(path.name)

    assert offenders == []


def test_only_legacy_final_reply_backend_imports_final_reply_for_new_phase5_path() -> None:
    offenders = []
    for path in sorted(LEGACY.glob("*.py")):
        imports = _imports(path)
        if "fitmas.final_reply" in imports and path.name != "final_reply_backend.py":
            offenders.append(path.name)

    assert offenders == []


def test_conversation_planning_runtime_mapper_uses_reply_composer() -> None:
    source = (LEGACY / "conversation_planning_bridge.py").read_text(encoding="utf-8")
    conversation_source = CONVERSATION.read_text(encoding="utf-8")

    assert "_decision_reply_composer().compose" in conversation_source
    assert "decision_reply_composer_fn().compose" in source
    assert "planning_runtime_block" in source
