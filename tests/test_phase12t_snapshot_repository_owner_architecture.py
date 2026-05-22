from __future__ import annotations

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"
ROOT_REPOSITORY = SRC / "repository.py"
ATHLETE_REPOSITORY = SRC / "domain" / "athlete" / "repository.py"
PLANNING_REPOSITORY = SRC / "domain" / "planning" / "repository.py"

ATHLETE_SNAPSHOT_API = {
    "to_domain_fitness_snapshot",
    "to_domain_readiness_snapshot",
    "get_latest_fitness_snapshot_record",
    "get_latest_readiness_snapshot_record",
    "save_fitness_snapshot",
    "save_readiness_snapshot",
}

PLANNING_DECISION_API = {
    "to_domain_planning_decision",
    "get_latest_planning_decision_record",
    "save_planning_decision",
}

SNAPSHOT_AND_DECISION_CONSUMERS = {
    "app/api/routes_app.py": SRC / "app/api/routes_app.py",
    "app/api/routes_stats.py": SRC / "app/api/routes_stats.py",
    "decision/context_builder.py": SRC / "decision/context_builder.py",
    "decision/turn_context.py": SRC / "decision/turn_context.py",
    "domain/planning/planning_state.py": SRC / "domain/planning/planning_state.py",
    "skills/heartbeat/heartbeat.py": SRC / "skills/heartbeat/heartbeat.py",
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


def test_12t_domain_repositories_own_snapshot_and_planning_decision_api() -> None:
    assert ATHLETE_REPOSITORY.exists()
    assert ATHLETE_SNAPSHOT_API <= _function_names(ATHLETE_REPOSITORY)
    assert PLANNING_DECISION_API <= _function_names(PLANNING_REPOSITORY)


def test_12t_root_repository_keeps_only_facades_for_snapshot_and_planning_decision_api() -> None:
    assert not ROOT_REPOSITORY.exists()

def test_12t_runtime_consumers_use_domain_repositories_for_snapshots_and_planning_decisions() -> None:
    offenders: list[str] = []
    forbidden_root_calls = (
        r"(?<!_)repo\.to_domain_fitness_snapshot",
        r"(?<!_)repo\.to_domain_readiness_snapshot",
        r"(?<!_)repo\.to_domain_planning_decision",
        r"(?<!_)repo\.get_latest_fitness_snapshot_record",
        r"(?<!_)repo\.get_latest_readiness_snapshot_record",
        r"(?<!_)repo\.get_latest_planning_decision_record",
        r"(?<!_)repo\.save_fitness_snapshot",
        r"(?<!_)repo\.save_readiness_snapshot",
        r"(?<!_)repo\.save_planning_decision",
        r"root_repo\.to_domain_fitness_snapshot",
        r"root_repo\.to_domain_readiness_snapshot",
        r"root_repo\.to_domain_planning_decision",
        r"root_repo\.get_latest_fitness_snapshot_record",
        r"root_repo\.get_latest_readiness_snapshot_record",
        r"root_repo\.get_latest_planning_decision_record",
        r"root_repo\.save_fitness_snapshot",
        r"root_repo\.save_readiness_snapshot",
        r"root_repo\.save_planning_decision",
    )
    for name, path in SNAPSHOT_AND_DECISION_CONSUMERS.items():
        source = path.read_text(encoding="utf-8")
        offenders.extend(
            f"{name}: {pattern}"
            for pattern in forbidden_root_calls
            if re.search(pattern, source)
        )

    assert offenders == []
