from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"
SEARCH_ROOTS = (
    SRC,
    ROOT / "tests",
    ROOT / "scripts",
)

ROOT_PLANNING_CORE_MODULES = {
    "plan_patch.py": "fitmas.plan_patch",
    "week_coherence.py": "fitmas.week_coherence",
}


def _python_like_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix == ".py" or (root.name == "scripts" and path.suffix == ""):
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


def test_11k_plan_patch_and_week_coherence_leave_root() -> None:
    assert all((SRC / "domain" / "planning" / filename).exists() for filename in ROOT_PLANNING_CORE_MODULES)
    assert [filename for filename in ROOT_PLANNING_CORE_MODULES if (SRC / filename).exists()] == []


def test_11k_no_python_imports_use_root_plan_patch_or_week_coherence() -> None:
    forbidden = set(ROOT_PLANNING_CORE_MODULES.values())
    offenders: list[str] = []

    for root in SEARCH_ROOTS:
        for path in _python_like_files(root):
            if path == Path(__file__):
                continue
            imports = _imports(path)
            matched = sorted(module for module in imports if module in forbidden)
            if matched:
                offenders.append(f"{path.relative_to(ROOT)}: {', '.join(matched)}")

    assert offenders == []
