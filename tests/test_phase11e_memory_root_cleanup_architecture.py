from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"
SEARCH_ROOTS = (
    SRC,
    ROOT / "tests",
)

ROOT_MEMORY_MODULES = {
    "availability_constraints.py": "fitmas.availability_constraints",
    "fact_memory.py": "fitmas.fact_memory",
    "memory_maintenance.py": "fitmas.memory_maintenance",
    "memory_mutation_service.py": "fitmas.memory_mutation_service",
    "memory_patterns.py": "fitmas.memory_patterns",
    "memory_profile.py": "fitmas.memory_profile",
    "memory_routing.py": "fitmas.memory_routing",
    "profile_summary.py": "fitmas.profile_summary",
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


def test_11e_memory_modules_live_under_domain_package_only() -> None:
    expected_targets = {
        SRC / "domain" / "memory" / "availability_constraints.py",
        SRC / "domain" / "memory" / "fact_memory.py",
        SRC / "domain" / "memory" / "maintenance.py",
        SRC / "domain" / "memory" / "mutation_service.py",
        SRC / "domain" / "memory" / "patterns.py",
        SRC / "domain" / "memory" / "profile_memory.py",
        SRC / "domain" / "memory" / "routing.py",
        SRC / "domain" / "memory" / "profile_summary.py",
    }

    assert all(path.exists() for path in expected_targets)
    assert [filename for filename in ROOT_MEMORY_MODULES if (SRC / filename).exists()] == []


def test_11e_no_python_imports_use_root_memory_modules() -> None:
    forbidden = set(ROOT_MEMORY_MODULES.values())
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
