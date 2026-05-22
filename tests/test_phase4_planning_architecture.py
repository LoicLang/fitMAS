from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FITMAS = ROOT / "backend" / "src" / "fitmas"
PLANNING = FITMAS / "domain" / "planning"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_reference_resolver_does_not_import_llm_or_tools() -> None:
    imports = _imports(PLANNING / "reference_resolver.py")
    forbidden = {"fitmas.llm", "fitmas.tools", "fitmas.tools.registry"}

    assert imports.isdisjoint(forbidden)


def test_candidate_builder_never_writes() -> None:
    source = (PLANNING / "candidate_builder.py").read_text(encoding="utf-8")
    forbidden = (".add(", ".commit(", ".flush(", "apply_patch_for_user", "create_pending_mutation_confirmation")

    assert [token for token in forbidden if token in source] == []


def test_new_planning_writes_are_confined_to_planning_command_service() -> None:
    offenders: list[str] = []
    for path in sorted(PLANNING.glob("*.py")):
        if path.name in {"mutation_service.py", "patch_mutation_service.py"}:
            continue
        source = path.read_text(encoding="utf-8")
        if "apply_patch_for_user" in source or "create_pending_mutation_confirmation" in source:
            offenders.append(path.name)

    assert offenders == []
