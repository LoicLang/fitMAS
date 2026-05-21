from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"
PLANNING = SRC / "domain" / "planning"


DELETED_ROOT_MODULES = {
    "mutations.py",
    "mutation_hooks.py",
    "mutation_permissions.py",
}


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


def test_10p_planning_executor_modules_are_no_longer_root_modules() -> None:
    for filename in DELETED_ROOT_MODULES:
        assert not (SRC / filename).exists(), filename

    assert (PLANNING / "mutation_executor.py").exists()
    assert (PLANNING / "mutation_hooks.py").exists()
    assert (PLANNING / "mutation_permissions.py").exists()


def test_10p_no_backend_imports_root_planning_executor_modules() -> None:
    forbidden = {
        "fitmas.mutations",
        "fitmas.mutation_hooks",
        "fitmas.mutation_permissions",
    }
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        hits = sorted(
            module
            for module in _imports(path)
            if module in forbidden or any(module.startswith(f"{item}.") for item in forbidden)
        )
        if hits:
            offenders.append(f"{path.relative_to(SRC).as_posix()}: {hits}")

    assert offenders == []


def test_10p_patch_mutation_service_uses_planning_executor_boundary() -> None:
    source = (PLANNING / "patch_mutation_service.py").read_text(encoding="utf-8")

    assert "from fitmas.domain.planning import mutation_executor" in source
    assert "fitmas.mutations" not in source
    assert "fitmas.mutation_hooks" not in source


def test_10p_root_module_census_no_longer_tracks_planning_executor_modules() -> None:
    census = (ROOT / "docs" / "ROOT-MODULE-CENSUS.md").read_text(encoding="utf-8")

    for filename in DELETED_ROOT_MODULES:
        assert f"| `{filename}` |" not in census
