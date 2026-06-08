from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"
ROOT_REPOSITORY = SRC / "repository.py"
PLANNING_REPOSITORY = SRC / "domain" / "planning" / "repository.py"

SCHEDULED_SESSION_API = {
    "get_scheduled_sessions",
    "get_scheduled_sessions_for_date",
    "get_scheduled_sessions_between_dates",
    "get_scheduled_session_for_date",
    "get_scheduled_session",
    "get_today_scheduled_session",
    "find_scheduled_session_for_activity",
    "mark_scheduled_session_completed",
    "set_scheduled_session_status",
}

PLANNING_AUDIT_API = {
    "add_plan_mutation_event",
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


def test_12q_planning_repository_owns_scheduled_session_and_audit_api() -> None:
    assert PLANNING_REPOSITORY.exists()

    functions = _function_names(PLANNING_REPOSITORY)

    assert SCHEDULED_SESSION_API <= functions
    assert PLANNING_AUDIT_API <= functions


def test_12q_root_repository_keeps_only_facade_for_planning_session_io() -> None:
    assert not ROOT_REPOSITORY.exists()

def test_12q_planning_runtime_uses_planning_repository_for_scheduled_sessions() -> None:
    sources = {
        "session_actions.py": SRC / "domain/planning/session_actions.py",
        "patch_mutation_service.py": SRC / "domain/planning/patch_mutation_service.py",
        "adaptation.py": SRC / "domain/planning/adaptation.py",
        "planning_state.py": SRC / "domain/planning/planning_state.py",
    }

    offenders: list[str] = []
    for name, path in sources.items():
        source = path.read_text(encoding="utf-8")
        if "fitmas.legacy.domain.planning import repository" not in source:
            offenders.append(f"{name}: missing planning repository import")
        if "root_repo.get_scheduled" in source:
            offenders.append(f"{name}: scheduled session read still goes through root repository")
        if "root_repo.add_plan_mutation_event" in source:
            offenders.append(f"{name}: planning audit write still goes through root repository")

    assert offenders == []
