from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"
ROOT_REPOSITORY = SRC / "repository.py"
MEMORY_REPOSITORY = SRC / "domain" / "memory" / "repository.py"

MEMORY_API = {
    "to_pydantic_fact",
    "to_pydantic_pattern",
    "get_active_facts",
    "get_active_working_memory",
    "get_active_patterns",
    "get_active_memory_items",
    "replace_user_facts",
    "upsert_facts",
    "upsert_working_memory",
    "purge_expired_working_memory",
    "sync_user_patterns",
}

MEMORY_DOMAIN_MODULES = {
    "profile_memory.py": SRC / "domain/memory/profile_memory.py",
    "mutation_service.py": SRC / "domain/memory/mutation_service.py",
    "maintenance.py": SRC / "domain/memory/maintenance.py",
}


def _function_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}


def _function_source(path: Path, name: str) -> str:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    lines = source.splitlines()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            end_lineno = node.end_lineno or node.lineno
            return "\n".join(lines[node.lineno - 1:end_lineno])
    raise AssertionError(f"{name} not found in {path}")


def test_12r_memory_repository_owns_profile_working_and_pattern_api() -> None:
    assert MEMORY_REPOSITORY.exists()

    assert MEMORY_API <= _function_names(MEMORY_REPOSITORY)


def test_12r_root_repository_keeps_only_facade_for_memory_api() -> None:
    assert not ROOT_REPOSITORY.exists()

def test_12r_memory_domain_uses_memory_repository_for_memory_storage() -> None:
    offenders: list[str] = []
    forbidden_root_calls = (
        "root_repo.get_active_facts",
        "root_repo.get_active_working_memory",
        "root_repo.get_active_patterns",
        "root_repo.get_active_memory_items",
        "root_repo.replace_user_facts",
        "root_repo.upsert_facts",
        "root_repo.upsert_working_memory",
        "root_repo.purge_expired_working_memory",
        "root_repo.sync_user_patterns",
    )
    for name, path in MEMORY_DOMAIN_MODULES.items():
        source = path.read_text(encoding="utf-8")
        if "fitmas.legacy.domain.memory import repository" not in source:
            offenders.append(f"{name}: missing memory repository import")
        offenders.extend(f"{name}: {token}" for token in forbidden_root_calls if token in source)

    assert offenders == []
