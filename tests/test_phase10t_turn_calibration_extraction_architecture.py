from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"
DECISION = SRC / "decision"
PIPELINE = SRC / "conversation_pipeline.py"

PIPELINE_CALIBRATION_IMPORTS_TO_REMOVE = {
    "fitmas.calibration_llm",
    "fitmas.calibration_needs",
}


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


def test_10t_turn_calibration_owner_exists_under_decision() -> None:
    assert (DECISION / "turn_calibration.py").exists()


def test_10t_conversation_pipeline_imports_calibration_owner() -> None:
    assert "fitmas.decision.turn_calibration" in _imports(PIPELINE)


def test_10t_conversation_pipeline_no_longer_imports_calibration_builders_directly() -> None:
    imports = _imports(PIPELINE)

    assert PIPELINE_CALIBRATION_IMPORTS_TO_REMOVE.isdisjoint(imports)


def test_10t_turn_calibration_owner_does_not_import_conversation_pipeline() -> None:
    imports = _imports(DECISION / "turn_calibration.py")

    assert "fitmas.conversation_pipeline" not in imports


def test_10t_conversation_pipeline_shrinks_below_calibration_budget() -> None:
    assert len(_source(PIPELINE).splitlines()) <= 620
