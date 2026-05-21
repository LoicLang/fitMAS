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


def test_8d_decision_runtime_service_exists_without_legacy_imports() -> None:
    source = _source("decision/runtime.py")

    assert "class DecisionRuntimeService" in source
    assert "fitmas.legacy" not in source
    assert "conversation_pipeline" not in source
    assert "fitmas.final_reply" not in source
    assert "decision_legacy" not in source


def test_8d_conversation_pipeline_stays_under_bridge_shrink_budget() -> None:
    line_count = len(_source("conversation_pipeline.py").splitlines())

    assert line_count <= 3600


def test_8d_message_route_lives_under_target_app_api_package() -> None:
    source = _source("app/api/routes_messages.py")

    assert "router = APIRouter()" in source
    assert "run_conversation_turn" in source
    assert "ConversationTurnInput" in source


def test_8d_root_api_messages_wrapper_has_been_deleted() -> None:
    assert not (SRC / "api_messages.py").exists()


def test_8d_no_active_heartbeat_skill_imports_outside_legacy() -> None:
    offenders: list[str] = []
    allowed_prefixes = {
        "legacy/",
        "skills/heartbeat/",
    }
    allowed_files = {
        "app/telegram/scheduler.py",
        "telegram_commands.py",
        "app/api/routes_debug.py",
        "app/api/routes_ops.py",
    }
    for path in sorted(SRC.rglob("*.py")):
        relative = str(path.relative_to(SRC))
        if relative in allowed_files or any(relative.startswith(prefix) for prefix in allowed_prefixes):
            continue
        imports = _imports(path)
        if any(module.startswith("fitmas.skills.heartbeat") for module in imports):
            offenders.append(relative)

    assert offenders == []


def test_8d_conversation_pipeline_uses_decision_owners_not_legacy_bridges() -> None:
    source = _source("decision/turn_router.py")

    assert "readonly_reply" in source
    assert "legacy_decision_contract_disabled" not in source
    assert 'response_type == "plan_patch"' not in source
    assert 'response_type == "requires_confirmation"' not in source
    assert 'response_type == "mutation_decision"' not in source


def test_8d_planning_reply_helpers_live_in_legacy_bridge_without_old_cutover() -> None:
    pipeline = _source("conversation_pipeline.py")
    outcomes = _source("decision/planning_outcomes.py")

    assert "def maybe_handle_planning_runtime_cutover" not in pipeline
    assert not (SRC / "legacy/conversation_planning_bridge.py").exists()
    assert "canonical_planning_blocked" in outcomes
    assert "legacy_decision_contract_disabled" in outcomes


def test_8d_readonly_reply_helpers_live_in_decision_owner() -> None:
    pipeline = _source("conversation_pipeline.py")
    bridge = _source("decision/readonly_reply.py")

    assert not (SRC / "legacy/conversation_readonly_reply_bridge.py").exists()
    assert "def compose_no_change_reply_for_turn" in bridge
    assert "def _compose_no_change_reply_for_turn" not in pipeline
    assert "compose_plan_lookup_reply" in bridge
    assert "compose_execution_report_reply" in bridge


def test_8d_legacy_decision_helpers_are_deleted_with_artifact_owner() -> None:
    pipeline = _source("conversation_pipeline.py")

    assert not (SRC / "legacy/conversation_decision_bridge.py").exists()
    assert not (SRC / "legacy/coach_decision_artifact.py").exists()
    assert "def _is_coach_decision" not in pipeline
    assert "def _is_legacy_readonly_decision" not in pipeline


def test_8d_active_heartbeat_entrypoints_import_runtime_adapter_not_skill_loop() -> None:
    checked = {
        "app/telegram/scheduler.py",
        "telegram_commands.py",
        "app/api/routes_debug.py",
        "app/api/routes_ops.py",
    }
    offenders: list[str] = []
    for relative in checked:
        source = _source(relative)
        if "from fitmas import heartbeat" in source or "fitmas.heartbeat" in source:
            offenders.append(relative)
        if "run_heartbeat_trigger" not in source and relative != "app/api/routes_debug.py":
            offenders.append(f"{relative}:missing_runtime_adapter")

    assert offenders == []
