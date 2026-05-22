from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "backend" / "src" / "fitmas"
DELETED_ROOT_MODULES = (
    "fitmas.domain.planning.plan_patch_adaptation_policy",
    "fitmas.domain.planning.plan_patch_candidate_evaluator",
    "fitmas.domain.planning.plan_patch_candidate_reviewer",
    "fitmas.domain.planning.plan_patch_candidates",
    "fitmas.domain.planning.plan_patch_backend_candidates",
)


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


def test_11a_old_planning_candidate_root_modules_are_deleted() -> None:
    offenders = [
        module.removeprefix("fitmas.") + ".py"
        for module in DELETED_ROOT_MODULES
        if (SRC_ROOT / f"{module.removeprefix('fitmas.')}.py").exists()
    ]

    assert offenders == []


def test_11a_no_imports_of_deleted_planning_candidate_root_modules() -> None:
    offenders = [
        f"{path.relative_to(ROOT).as_posix()}: {module}"
        for path in _python_sources()
        for module in DELETED_ROOT_MODULES
        if path.name != Path(__file__).name and _imports_module(path, module)
    ]

    assert offenders == []
