from __future__ import annotations

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"
ROOT_REPOSITORY = SRC / "repository.py"
EXECUTION_REPOSITORY = SRC / "domain" / "execution" / "repository.py"

ACTIVITY_API = {
    "to_pydantic_activity",
    "get_activities",
    "get_recent_activity_for_sport",
    "get_activity_by_external_id",
    "add_activity",
}

ACTIVITY_CONSUMERS = {
    "domain/execution/helpers.py": SRC / "domain/execution/helpers.py",
    "domain/memory/maintenance.py": SRC / "domain/memory/maintenance.py",
    "domain/planning/patch_mutation_service.py": SRC / "domain/planning/patch_mutation_service.py",
    "domain/planning/adaptation.py": SRC / "domain/planning/adaptation.py",
    "domain/planning/planning_state.py": SRC / "domain/planning/planning_state.py",
    "integrations/strava.py": SRC / "integrations/strava.py",
    "app/api/routes_activities.py": SRC / "app/api/routes_activities.py",
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


def test_12s_execution_repository_owns_activity_api() -> None:
    assert EXECUTION_REPOSITORY.exists()

    assert ACTIVITY_API <= _function_names(EXECUTION_REPOSITORY)


def test_12s_root_repository_keeps_only_facade_for_activity_api() -> None:
    source = ROOT_REPOSITORY.read_text(encoding="utf-8")
    assert "from fitmas.domain.execution import repository as execution_repo" in source

    for name in sorted(ACTIVITY_API):
        body = _function_source(ROOT_REPOSITORY, name)
        assert f"execution_repo.{name}" in body
        assert "db.query" not in body
        assert "s.Activity(" not in body
        assert "Activity(" not in body


def test_12s_activity_consumers_use_execution_repository_for_activity_storage() -> None:
    offenders: list[str] = []
    forbidden_root_activity_calls = (
        r"root_repo\.to_pydantic_activity",
        r"root_repo\.get_activities",
        r"root_repo\.get_recent_activity_for_sport",
        r"root_repo\.get_activity_by_external_id",
        r"root_repo\.add_activity",
        r"(?<!execution_)repo\.to_pydantic_activity",
        r"(?<!execution_)repo\.get_activities",
        r"(?<!execution_)repo\.get_recent_activity_for_sport",
        r"(?<!execution_)repo\.get_activity_by_external_id",
        r"(?<!execution_)repo\.add_activity",
    )
    for name, path in ACTIVITY_CONSUMERS.items():
        source = path.read_text(encoding="utf-8")
        if "fitmas.domain.execution import repository" not in source:
            offenders.append(f"{name}: missing execution repository import")
        offenders.extend(
            f"{name}: {pattern}"
            for pattern in forbidden_root_activity_calls
            if re.search(pattern, source)
        )

    assert offenders == []
