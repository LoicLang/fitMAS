from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"


def _source(relative: str) -> str:
    return (SRC / relative).read_text(encoding="utf-8")


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


def test_8c1_conversation_has_no_active_mutationdecision_planning_routes() -> None:
    source = _source("conversation_pipeline.py")
    forbidden = {
        "from fitmas.llm import MutationDecision",
        "MutationDecision(",
        'response_type == "mutation_decision"',
        'response_type == "requires_confirmation"',
        'response_type == "plan_patch"',
        "_should_try_legacy_plan_adaptation_after_decide",
        "_apply_matching_legacy_pending_acceptance",
        "apply_decisions_for_user",
    }

    assert sorted(token for token in forbidden if token in source) == []


def test_8c2_only_legacy_modules_import_final_reply() -> None:
    offenders: list[str] = []
    allowed = {
        SRC / "final_reply.py",
        SRC / "legacy" / "final_reply_backend.py",
        SRC / "legacy" / "conversation_reply_adapter.py",
        SRC / "skills" / "heartbeat" / "reply_context.py",
        SRC / "skills" / "heartbeat" / "heartbeat.py",
    }

    for path in sorted(SRC.rglob("*.py")):
        if path in allowed:
            continue
        imports = _imports(path)
        imports_final_reply = "fitmas.final_reply" in imports
        if imports_final_reply:
            offenders.append(str(path.relative_to(SRC)))

    assert offenders == []


def test_8c3_telegram_heartbeat_defaults_to_runtime_adapter() -> None:
    source = _source("app/telegram/scheduler.py")

    assert "heartbeat_runtime_cutover_enabled()" not in source
    assert "run_heartbeat_trigger" in source
    assert "_heartbeat_draft_factory" in source


def test_8c4_tools_registry_does_not_offer_legacy_mutation_tools_by_default() -> None:
    source = _source("tools/registry.py")
    forbidden = {
        'name="propose_replan"',
        'name="draft_move_session"',
        'name="draft_swap_sessions"',
        'name="draft_replace_session"',
        'name="draft_lighten_day"',
        'name="draft_create_session"',
    }

    assert sorted(token for token in forbidden if token in source) == []


def test_8c5_runtime_files_do_not_read_weeklyplan_dayplan() -> None:
    checked = {
        "conversation_pipeline.py",
        "plan_mutation_service.py",
        "decision/context_builder.py",
        "domain/planning/mutation_service.py",
        "api_read.py",
    }
    forbidden = {
        "get_active_plan(",
        "get_active_plan_optional(",
        "get_day_plan(",
        "to_pydantic_plan(",
        "WeeklyPlan",
        "DayPlan",
    }
    offenders: list[str] = []
    for relative in checked:
        source = _source(relative)
        offenders.extend(f"{relative}: {token}" for token in forbidden if token in source)

    assert offenders == []
