from __future__ import annotations

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"
ROOT_REPOSITORY = SRC / "repository.py"
TEMPLATE_REPOSITORY = SRC / "domain" / "planning" / "template_repository.py"

TEMPLATE_API = {
    "to_pydantic_day",
    "to_pydantic_plan",
    "get_active_plan_optional",
    "get_active_plan",
    "get_plan_optional",
    "get_day_plan",
    "replace_plan",
    "sync_scheduled_sessions_for_plan",
    "mark_day_completed",
    "get_current_week_day_plan_for_session",
    "resync_plan_sessions",
    "get_yesterday_status",
    "move_session",
    "set_change_notes",
}

TEMPLATE_CONSUMERS = {
    "app/api/routes_onboarding.py": SRC / "app" / "api" / "routes_onboarding.py",
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


def test_12v_template_repository_owns_weeklyplan_dayplan_api() -> None:
    assert TEMPLATE_REPOSITORY.exists()
    assert TEMPLATE_API <= _function_names(TEMPLATE_REPOSITORY)


def test_12v_root_repository_keeps_only_template_facades() -> None:
    assert not ROOT_REPOSITORY.exists()

def test_12v_onboarding_uses_template_repository_for_week_templates() -> None:
    offenders: list[str] = []
    forbidden_root_calls = (
        r"(?<!_)repo\.to_pydantic_day",
        r"(?<!_)repo\.to_pydantic_plan",
        r"(?<!_)repo\.get_active_plan_optional",
        r"(?<!_)repo\.get_active_plan",
        r"(?<!_)repo\.get_plan_optional",
        r"(?<!_)repo\.get_day_plan",
        r"(?<!_)repo\.replace_plan",
        r"(?<!_)repo\.sync_scheduled_sessions_for_plan",
        r"(?<!_)repo\.mark_day_completed",
        r"(?<!_)repo\.get_current_week_day_plan_for_session",
        r"(?<!_)repo\.resync_plan_sessions",
        r"(?<!_)repo\.get_yesterday_status",
        r"(?<!_)repo\.move_session",
        r"(?<!_)repo\.set_change_notes",
    )
    for name, path in TEMPLATE_CONSUMERS.items():
        source = path.read_text(encoding="utf-8")
        if "fitmas.legacy.domain.planning import template_repository as template_repo" not in source:
            offenders.append(f"{name}: missing template repository import")
        offenders.extend(
            f"{name}: {pattern}"
            for pattern in forbidden_root_calls
            if re.search(pattern, source)
        )

    assert offenders == []
