from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"


DELETED_MODULES = {
    "legacy/coach_command_adapter.py",
    "legacy/coach_decision_artifact.py",
    "legacy/coach_understanding_adapter.py",
    "legacy/understanding_shadow.py",
    "llm/decision_legacy.py",
    "llm/legacy_action_compile.py",
    "llm/legacy_parser.py",
    "llm/legacy_prompt.py",
    "llm/legacy_provider.py",
    "llm/legacy_schema_repair.py",
    "llm/legacy_tool_loop.py",
}


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


def test_10m_deletes_coachdecision_compat_modules() -> None:
    for relative in DELETED_MODULES:
        assert not (SRC / relative).exists(), relative


def test_10m_no_backend_imports_deleted_coachdecision_modules() -> None:
    forbidden = {
        "fitmas." + relative.removesuffix(".py").replace("/", ".")
        for relative in DELETED_MODULES
    }
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        relative = path.relative_to(SRC).as_posix()
        if relative in DELETED_MODULES:
            continue
        imports = _imports(path)
        hit = forbidden.intersection(imports)
        if hit:
            offenders.append(f"{relative}: {sorted(hit)}")

    assert offenders == []


def test_10m_legacy_decision_contracts_are_deleted() -> None:
    assert not (SRC / "legacy" / "decision_contracts.py").exists()

    source = _source("domain/planning/mutation_decision.py")
    assert "class CoachDecision" not in source
    assert "PendingResolution" not in source
    assert "MemoryAction" not in source
    assert "class MutationDecision" in source
