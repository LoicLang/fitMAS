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

ROOT_PLANNING_METADATA_MODULES = {
    "session_metadata.py": "fitmas.session_metadata",
    "week_metadata.py": "fitmas.week_metadata",
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


def test_11m_planning_metadata_modules_are_merged_not_moved() -> None:
    assert not (SRC / "session_metadata.py").exists()
    assert not (SRC / "week_metadata.py").exists()
    assert not (SRC / "domain" / "planning" / "session_metadata.py").exists()
    assert not (SRC / "domain" / "planning" / "week_metadata.py").exists()


def test_11m_no_python_imports_use_root_planning_metadata_modules() -> None:
    forbidden = set(ROOT_PLANNING_METADATA_MODULES.values())
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


def test_11m_planning_metadata_functions_live_with_domain_owners() -> None:
    models_source = (SRC / "domain" / "planning" / "models.py").read_text(encoding="utf-8")
    periodization_source = (SRC / "domain" / "planning" / "periodization.py").read_text(encoding="utf-8")

    assert "def compute_load_band(" in models_source
    assert "def build_week_label(" in periodization_source
