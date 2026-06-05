from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"


def _source(relative: str) -> str:
    return (SRC / relative).read_text(encoding="utf-8")


def _imports(path: Path) -> set[str]:
    modules: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def test_10o_patch_mutation_writer_is_owned_by_planning_domain() -> None:
    assert not (SRC / "plan_mutation_service.py").exists()

    source = _source("domain/planning/patch_mutation_service.py")
    assert "def apply_patch_for_user(" in source
    assert "def apply_decisions_for_user(" in source
    assert "class PlanPatchServiceResult" in source
    assert "class PlanMutationServiceResult" in source


def test_10o_no_backend_imports_root_plan_mutation_service() -> None:
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        imports = _imports(path)
        hits = sorted(
            module
            for module in imports
            if module == "fitmas.plan_mutation_service"
            or module.startswith("fitmas.plan_mutation_service.")
        )
        if hits:
            offenders.append(f"{path.relative_to(SRC).as_posix()}: {hits}")

    assert offenders == []


def test_10o_planning_command_service_calls_domain_writer_not_root_wrapper() -> None:
    source = _source("domain/planning/mutation_service.py")

    assert "fitmas.plan_mutation_service" not in source
    assert "patch_mutation_service" in source
