from __future__ import annotations

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"
ROOT_REPOSITORY = SRC / "repository.py"
INTEGRATION_REPOSITORY = SRC / "integrations" / "repository.py"
STRAVA_SERVICE = SRC / "integrations" / "strava.py"

STRAVA_REPOSITORY_API = {
    "get_strava_connection",
    "upsert_strava_connection",
    "update_strava_tokens",
    "mark_strava_synced",
}

STRAVA_CONNECTION_CONSUMERS = {
    "integrations/strava.py": SRC / "integrations/strava.py",
    "app/api/routes_app.py": SRC / "app/api/routes_app.py",
    "app/api/routes_activities.py": SRC / "app/api/routes_activities.py",
    "app/api/routes_read.py": SRC / "app/api/routes_read.py",
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


def test_12u_integrations_repository_owns_strava_connection_storage_api() -> None:
    assert INTEGRATION_REPOSITORY.exists()
    assert STRAVA_REPOSITORY_API <= _function_names(INTEGRATION_REPOSITORY)


def test_12u_root_repository_keeps_only_strava_connection_facade() -> None:
    assert not ROOT_REPOSITORY.exists()

def test_12u_strava_connection_consumers_use_integration_repository() -> None:
    offenders: list[str] = []
    for name, path in STRAVA_CONNECTION_CONSUMERS.items():
        source = path.read_text(encoding="utf-8")
        if "fitmas.legacy.integrations import repository as integration_repo" not in source:
            offenders.append(f"{name}: missing integration repository import")
        if re.search(r"(?<!_)repo\.get_strava_connection", source):
            offenders.append(f"{name}: root repo get_strava_connection")

    strava_source = STRAVA_SERVICE.read_text(encoding="utf-8")
    assert "s.StravaConnection(" not in strava_source
    assert "connection.last_sync_at =" not in strava_source
    assert offenders == []
