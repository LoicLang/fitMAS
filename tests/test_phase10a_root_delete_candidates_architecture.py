from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"
TESTS = ROOT / "tests"
SCRIPTS = ROOT / "scripts"

DELETED_ROOT_MODULES = {
    "api_messages.py",
    "plan_actions.py",
    "plan_patch_tools.py",
    "replan_proposal.py",
    "state.py",
}

FORBIDDEN_IMPORTS = {f"fitmas.{filename.removesuffix('.py')}" for filename in DELETED_ROOT_MODULES}


def _python_like_files(*roots: Path) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix == ".py" or (root == SCRIPTS and path.suffix == ""):
                files.append(path)
    return sorted(files)


def _imports(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return set()

    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def test_10a_deletes_simple_root_delete_candidates() -> None:
    existing = sorted(filename for filename in DELETED_ROOT_MODULES if (SRC / filename).exists())
    assert existing == []


def test_10a_no_imports_target_deleted_root_candidates() -> None:
    offenders: list[str] = []
    for path in _python_like_files(SRC, TESTS, SCRIPTS):
        hit = _imports(path) & FORBIDDEN_IMPORTS
        if hit:
            offenders.append(f"{path.relative_to(ROOT)}: {sorted(hit)}")
    assert offenders == []


def test_10a_rehomes_remaining_useful_code_outside_root() -> None:
    assert (SRC / "domain" / "planning" / "session_actions.py").exists()
    assert (SRC / "tools" / "replan_proposal.py").exists()
