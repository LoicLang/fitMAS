from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"
TESTS = ROOT / "tests"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _python_files(*roots: Path) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        files.extend(root.rglob("*.py"))
    return sorted(files)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(_source(path), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def test_9x_deletes_dead_legacy_compat_modules() -> None:
    assert not (SRC / "legacy" / "tools_compat.py").exists()
    assert not (SRC / "legacy" / "weekly_plan_compat.py").exists()


def test_9x_no_imports_of_deleted_legacy_compat_modules() -> None:
    forbidden = {
        "fitmas.legacy.tools_compat",
        "fitmas.legacy.weekly_plan_compat",
    }
    offenders: list[str] = []

    for path in _python_files(SRC, TESTS):
        hit = _imports(path) & forbidden
        if hit:
            offenders.append(f"{path.relative_to(ROOT)}: {sorted(hit)}")

    assert offenders == []


def test_9x_tool_runtime_tests_do_not_depend_on_deleted_plan_patch_tools() -> None:
    source = _source(TESTS / "test_tool_runtime.py")

    assert "legacy_planning_tool_specs" not in source
    assert "_legacy_planning_tool_registry" not in source
    assert "propose_replan_alias_remains_for_compatibility" not in source
    assert "plan_patch_tools" not in source
    assert "draft_move_session(" not in source
    assert "draft_swap_sessions(" not in source
    assert "draft_replace_session(" not in source
    assert "draft_create_session(" not in source


def test_9x_api_read_uses_runtime_week_models_directly() -> None:
    path = SRC / "app" / "api" / "routes_read.py"
    source = _source(path)
    imports = _imports(path)

    assert "fitmas.legacy.weekly_plan_compat" not in source
    assert "fitmas.legacy.app.api.read_models.RuntimeDay" in imports
    assert "fitmas.legacy.app.api.read_models.RuntimeWeek" in imports
    assert "WeeklyPlan" not in source
    assert "DayPlan" not in source
