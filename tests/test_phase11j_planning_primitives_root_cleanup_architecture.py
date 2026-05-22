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

ROOT_PLANNING_PRIMITIVE_MODULES = {
    "intensity_distribution.py": "fitmas.intensity_distribution",
    "interference.py": "fitmas.interference",
    "periodization.py": "fitmas.periodization",
    "planner.py": "fitmas.planner",
    "planning_config.py": "fitmas.planning_config",
    "planning_decision.py": "fitmas.planning_decision",
    "planning_state.py": "fitmas.planning_state",
    "session_similarity.py": "fitmas.session_similarity",
    "session_templates.py": "fitmas.session_templates",
    "workout_content.py": "fitmas.workout_content",
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


def test_11j_planning_primitives_leave_root() -> None:
    assert all((SRC / "domain" / "planning" / filename).exists() for filename in ROOT_PLANNING_PRIMITIVE_MODULES)
    assert [filename for filename in ROOT_PLANNING_PRIMITIVE_MODULES if (SRC / filename).exists()] == []


def test_11j_no_python_imports_use_root_planning_primitives() -> None:
    forbidden = set(ROOT_PLANNING_PRIMITIVE_MODULES.values())
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
