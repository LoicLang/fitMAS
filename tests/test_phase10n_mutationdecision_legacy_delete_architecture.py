from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"


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


def _python_files(*roots: Path) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if root.exists():
            files.extend(root.rglob("*.py"))
    return sorted(files)


def test_10n_mutation_decision_contract_lives_in_planning_domain() -> None:
    assert not (SRC / "legacy").exists()

    source = (SRC / "domain" / "planning" / "mutation_decision.py").read_text(
        encoding="utf-8"
    )
    assert "class MutationDecision" in source
    assert "fitmas.legacy" not in source


def test_10n_no_runtime_or_tests_import_fitmas_legacy() -> None:
    offenders: list[str] = []
    for path in _python_files(SRC, ROOT / "tests"):
        relative = path.relative_to(ROOT).as_posix()
        imports = _imports(path)
        hits = sorted(module for module in imports if module == "fitmas.legacy" or module.startswith("fitmas.legacy."))
        if hits:
            offenders.append(f"{relative}: {hits}")

    assert offenders == []
