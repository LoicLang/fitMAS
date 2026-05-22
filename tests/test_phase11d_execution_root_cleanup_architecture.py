from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"
SEARCH_ROOTS = (
    SRC,
    ROOT / "tests",
)

ROOT_EXECUTION_MODULES = {
    "activities.py": "fitmas.activities",
    "activity_claims.py": "fitmas.activity_claims",
    "activity_helpers.py": "fitmas.activity_helpers",
    "execution_clarification.py": "fitmas.execution_clarification",
    "execution_context.py": "fitmas.execution_context",
    "execution_evidence.py": "fitmas.execution_evidence",
    "execution_mutation_service.py": "fitmas.execution_mutation_service",
    "recent_reality.py": "fitmas.recent_reality",
}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def test_11d_execution_modules_live_under_domain_package_only() -> None:
    expected_targets = {
        SRC / "domain" / "execution" / "activities.py",
        SRC / "domain" / "execution" / "claims.py",
        SRC / "domain" / "execution" / "helpers.py",
        SRC / "domain" / "execution" / "clarification.py",
        SRC / "domain" / "execution" / "context.py",
        SRC / "domain" / "execution" / "evidence.py",
        SRC / "domain" / "execution" / "mutation_service.py",
        SRC / "domain" / "execution" / "recent_reality.py",
    }

    assert all(path.exists() for path in expected_targets)
    assert [filename for filename in ROOT_EXECUTION_MODULES if (SRC / filename).exists()] == []


def test_11d_no_python_imports_use_root_execution_modules() -> None:
    forbidden = set(ROOT_EXECUTION_MODULES.values())
    offenders: list[str] = []

    for root in SEARCH_ROOTS:
        for path in sorted(root.rglob("*.py")):
            if path == Path(__file__):
                continue
            imports = _imports(path)
            matched = sorted(module for module in imports if module in forbidden)
            if matched:
                offenders.append(f"{path.relative_to(ROOT)}: {', '.join(matched)}")

    assert offenders == []
