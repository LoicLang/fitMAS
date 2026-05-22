from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"


def _backend_python_files() -> list[Path]:
    return sorted(SRC.rglob("*.py"))


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def test_12i_adaptation_decision_is_owned_by_planning_domain() -> None:
    assert not (SRC / "adaptation_decision.py").exists()
    assert (SRC / "domain/planning/adaptation_decision.py").exists()


def test_12i_no_backend_imports_root_adaptation_decision() -> None:
    offenders: list[str] = []
    for path in _backend_python_files():
        imports = _imports(path)
        if "fitmas.adaptation_decision" in imports:
            offenders.append(path.relative_to(ROOT).as_posix())

    assert offenders == []
