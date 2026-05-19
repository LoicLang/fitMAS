from __future__ import annotations

import ast
from pathlib import Path


HISTORICAL_MODULES = frozenset(
    {
        "fitmas.planning_snapshot",
        "fitmas.adaptation_proposal",
        "fitmas.plan_patch_candidate_generator",
    }
)


def test_historical_planning_modules_are_physically_deleted() -> None:
    for module_name in HISTORICAL_MODULES:
        relative = module_name.removeprefix("fitmas.").replace(".", "/")
        assert not Path(f"backend/src/fitmas/{relative}.py").exists()


def test_backend_source_no_longer_imports_historical_planning_modules() -> None:
    offenders = _files_importing_historical_modules(Path("backend/src/fitmas"))

    assert offenders == {}


def test_tests_no_longer_preserve_historical_planning_module_contracts() -> None:
    offenders = _files_importing_historical_modules(
        Path("tests"),
        exclude={Path(__file__).name},
    )

    assert offenders == {}


def _files_importing_historical_modules(
    root: Path,
    *,
    exclude: set[str] | None = None,
) -> dict[str, tuple[str, ...]]:
    excluded_names = exclude or set()
    offenders: dict[str, tuple[str, ...]] = {}
    for path in root.rglob("*.py"):
        if path.name in excluded_names:
            continue
        imported = _historical_imports_in_file(path)
        if imported:
            offenders[str(path)] = imported
    return offenders


def _historical_imports_in_file(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(), filename=str(path))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            module = node.module
            if _is_historical_module(module):
                imports.append(module)
            continue
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_historical_module(alias.name):
                    imports.append(alias.name)
    return tuple(sorted(set(imports)))


def _is_historical_module(module_name: str) -> bool:
    return any(
        module_name == historical or module_name.startswith(f"{historical}.")
        for historical in HISTORICAL_MODULES
    )
