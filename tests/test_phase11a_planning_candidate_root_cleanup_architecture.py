from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "backend" / "src" / "fitmas"


def _python_sources() -> tuple[Path, ...]:
    return tuple(
        path
        for base in (ROOT / "backend" / "src", ROOT / "tests", ROOT / "scripts")
        for path in base.rglob("*.py")
    )


def _imports_module(path: Path, module_name: str) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == module_name for alias in node.names):
                return True
        if isinstance(node, ast.ImportFrom):
            if node.module == module_name:
                return True
    return False


def test_11a_backend_candidate_refs_root_module_is_deleted() -> None:
    assert not (SRC_ROOT / "plan_patch_backend_candidates.py").exists()


def test_11a_no_imports_of_deleted_backend_candidate_refs_module() -> None:
    offenders = [
        path.relative_to(ROOT).as_posix()
        for path in _python_sources()
        if path.name != Path(__file__).name
        and _imports_module(path, "fitmas.plan_patch_backend_candidates")
    ]

    assert offenders == []
