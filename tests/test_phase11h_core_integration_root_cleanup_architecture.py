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

ROOT_CORE_MODULES = {
    "calendar_resolution.py": "fitmas.calendar_resolution",
    "db.py": "fitmas.db",
    "seed.py": "fitmas.seed",
    "temporal_resolver.py": "fitmas.temporal_resolver",
    "time_context.py": "fitmas.time_context",
}
ROOT_INTEGRATION_MODULES = {
    "strava.py": "fitmas.strava",
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


def test_11h_core_and_integration_modules_leave_root() -> None:
    assert all((SRC / "core" / filename).exists() for filename in ROOT_CORE_MODULES)
    assert (SRC / "integrations" / "strava.py").exists()
    assert [filename for filename in ROOT_CORE_MODULES if (SRC / filename).exists()] == []
    assert [filename for filename in ROOT_INTEGRATION_MODULES if (SRC / filename).exists()] == []


def test_11h_no_python_imports_use_root_core_or_integration_modules() -> None:
    forbidden = set(ROOT_CORE_MODULES.values()) | set(ROOT_INTEGRATION_MODULES.values())
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


def test_11h_db_move_keeps_default_database_filename() -> None:
    forbidden_literal = "fitmas" + ".core.db"
    checked_paths = [
        SRC / "core" / "db.py",
        SRC / "app" / "telegram" / "bot.py",
        ROOT / "scripts" / "smoke_real_profile.py",
    ]
    offenders: list[str] = []

    for path in checked_paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value == forbidden_literal:
                offenders.append(str(path.relative_to(ROOT)))

    assert offenders == []
