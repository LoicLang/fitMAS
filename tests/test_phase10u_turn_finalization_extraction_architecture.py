from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"
DECISION = SRC / "decision"
PIPELINE = SRC / "decision" / "conversation_pipeline.py"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _imports(path: Path) -> set[str]:
    tree = ast.parse(_source(path), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
            imports.update(f"{node.module}.{alias.name}" for alias in node.names)
    return imports


def test_10u_turn_finalization_owner_exists_under_decision() -> None:
    assert (DECISION / "turn_finalization.py").exists()


def test_10u_conversation_pipeline_imports_turn_finalization_owner() -> None:
    assert "fitmas.legacy.decision.turn_finalization" in _imports(DECISION / "turn_router.py")


def test_10u_conversation_pipeline_no_longer_records_turns_directly() -> None:
    source = _source(PIPELINE)

    assert "reply_and_record_turn" not in source
    assert "filter_legacy_extracted_facts" not in source
    assert "supersede_pending_if_replaced" not in source


def test_10u_turn_finalization_owner_does_not_import_conversation_pipeline() -> None:
    imports = _imports(DECISION / "turn_finalization.py")

    assert "fitmas.conversation_pipeline" not in imports


def test_10u_conversation_pipeline_shrinks_below_finalization_budget() -> None:
    assert len(_source(PIPELINE).splitlines()) <= 500
