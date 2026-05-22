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


def test_12m_coach_state_bundle_is_owned_by_coaching_domain() -> None:
    assert not (SRC / "coach_state_bundle.py").exists()
    assert (SRC / "domain/coaching/coach_state.py").exists()


def test_12m_no_backend_imports_root_coach_state_bundle() -> None:
    offenders: list[str] = []
    for path in _backend_python_files():
        imports = _imports(path)
        if "fitmas.coach_state_bundle" in imports:
            offenders.append(path.relative_to(ROOT).as_posix())

    assert offenders == []
