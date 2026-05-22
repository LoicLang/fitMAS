from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"
ROOT_REPOSITORY = SRC / "repository.py"
ATHLETE_REPOSITORY = SRC / "domain" / "athlete" / "repository.py"
PLANNING_REPOSITORY = SRC / "domain" / "planning" / "repository.py"
COACHING_REPOSITORY = SRC / "domain" / "coaching" / "repository.py"


ATHLETE_PROFILE_API = {
    "to_pydantic_profile",
    "get_user",
    "get_user_optional",
    "replace_user_lists",
}

PLANNING_VIEW_API = {
    "to_pydantic_scheduled_session",
}

COACHING_ADAPTATION_API = {
    "to_domain_adaptation_event",
    "add_adaptation_event",
    "get_latest_adaptation_event",
    "get_recent_adaptation_events",
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


def test_12w_domain_repositories_own_remaining_root_storage_api() -> None:
    assert ATHLETE_PROFILE_API <= _function_names(ATHLETE_REPOSITORY)
    assert PLANNING_VIEW_API <= _function_names(PLANNING_REPOSITORY)
    assert COACHING_REPOSITORY.exists()
    assert COACHING_ADAPTATION_API <= _function_names(COACHING_REPOSITORY)


def test_12w_root_repository_has_no_direct_storage_or_query_logic() -> None:
    assert not ROOT_REPOSITORY.exists()

def test_12w_root_repository_remaining_facades_delegate_to_real_owners() -> None:
    assert not ROOT_REPOSITORY.exists()
