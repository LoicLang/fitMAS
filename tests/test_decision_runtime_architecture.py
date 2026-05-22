from __future__ import annotations

import ast
from dataclasses import fields
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DECISION = ROOT / "backend" / "src" / "fitmas" / "decision"
PURE_DECISION_MODULES = {
    "__init__.py",
    "command_actions.py",
    "command_bus.py",
    "command_mapping.py",
    "context.py",
    "explanation.py",
    "fallback_census.py",
    "input_event.py",
    "outcome.py",
    "output_verifier.py",
    "reply_composer.py",
    "reply_request.py",
    "runtime.py",
    "turn_recording.py",
    "understanding.py",
}


def _python_files() -> list[Path]:
    return sorted(path for path in DECISION.glob("*.py") if path.name != "__pycache__")


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _field_names(cls: type) -> set[str]:
    return {field.name for field in fields(cls)}


def test_decision_runtime_phase1_modules_exist() -> None:
    expected = {
        "__init__.py",
        "activity_highlight.py",
        "clarification_reply.py",
        "command_actions.py",
        "command_application.py",
        "coach_decision_runtime.py",
        "input_event.py",
        "context.py",
        "understanding.py",
        "explanation.py",
        "fallback_census.py",
        "outcome.py",
        "command_bus.py",
        "command_mapping.py",
        "runtime.py",
        "reply_composer.py",
        "readonly_reply.py",
        "reply_request.py",
        "output_verifier.py",
        "context_builder.py",
        "turn_calibration.py",
        "turn_context.py",
        "turn_finalization.py",
        "turn_recording.py",
        "turn_idempotency.py",
        "turn_persistence.py",
        "turn_planning_route.py",
        "turn_state.py",
        "turn_router.py",
        "understanding_runtime.py",
        "pending_reply.py",
        "pending_resolution.py",
        "plan_patch_reply.py",
        "planning_outcomes.py",
        "planning_runtime.py",
    }

    assert DECISION.exists()
    assert {path.name for path in _python_files()} == expected


def test_pure_decision_modules_have_no_database_or_legacy_imports() -> None:
    forbidden_exact = {
        "sqlalchemy",
        "fitmas.core.db",
        "fitmas.repository",
        "fitmas.schema",
        "fitmas.models",
        "fitmas.legacy",
    }
    forbidden_prefixes = (
        "sqlalchemy.",
        "fitmas.legacy.",
    )

    offenders: list[str] = []
    for path in _python_files():
        if path.name not in PURE_DECISION_MODULES:
            continue
        for module in _imports(path):
            if module in forbidden_exact or module.startswith(forbidden_prefixes):
                offenders.append(f"{path.name}: {module}")

    assert offenders == []


def test_context_builder_is_the_only_decision_module_allowed_to_read_repository() -> None:
    builder = DECISION / "context_builder.py"
    assert builder.exists()

    allowed = {
        "sqlalchemy.orm",
        "fitmas.repository",
        "fitmas.schema",
        "fitmas.coach_state_bundle",
        "fitmas.core.time_context",
    }
    imports = _imports(builder)
    read_imports = {module for module in imports if module in allowed}

    assert read_imports
    assert all(
        module in allowed or not module.startswith(("sqlalchemy", "fitmas.repository", "fitmas.schema"))
        for module in imports
    )


def test_context_builder_is_read_only_and_not_runtime_wired() -> None:
    source = (DECISION / "context_builder.py").read_text(encoding="utf-8")
    forbidden = (
        ".add(",
        ".delete(",
        ".commit(",
        ".flush(",
        "PlanMutationService",
        "MemoryMutationService",
        "ExecutionCommandService",
        "conversation_pipeline",
        "final_reply",
        "fitmas.llm",
        "fitmas.tools",
        "PlanPatch",
        "MutationDecision",
        "WeeklyPlan",
        "DayPlan",
        "get_active_plan",
        "to_pydantic_plan",
    )

    offenders = [token for token in forbidden if token in source]

    assert offenders == []


def test_phase2_does_not_wire_existing_runtime_to_context_builder() -> None:
    root = ROOT / "backend" / "src" / "fitmas"
    files = [
        root / "conversation_pipeline.py",
        root / "skills" / "heartbeat" / "heartbeat.py",
        root / "app" / "api" / "routes_app.py",
        root / "app" / "api" / "routes_messages.py",
    ]
    offenders: list[str] = []
    for path in files:
        source = path.read_text(encoding="utf-8")
        if "DecisionContextBuilder" in source or "fitmas.decision.context_builder" in source:
            offenders.append(path.name)

    assert offenders == []


def test_decision_package_root_does_not_import_context_builder() -> None:
    source = (DECISION / "__init__.py").read_text(encoding="utf-8")

    assert "context_builder" not in source


def test_decision_package_stays_free_of_legacy_understanding_adapter() -> None:
    forbidden_exact = {
        "fitmas.legacy",
        "fitmas.legacy.coach_understanding_adapter",
        "fitmas.llm",
        "fitmas.conversation_pipeline",
        "fitmas.final_reply",
        "fitmas.tools.registry",
    }
    forbidden_prefixes = (
        "fitmas.legacy.",
        "fitmas.tools.",
    )

    offenders: list[str] = []
    for path in _python_files():
        if path.name in {"command_application.py", "readonly_reply.py", "understanding_runtime.py", "coach_decision_runtime.py"}:
            continue
        for module in _imports(path):
            if module in forbidden_exact or module.startswith(forbidden_prefixes):
                offenders.append(f"{path.name}: {module}")

    assert offenders == []


def test_legacy_package_has_no_runtime_source_modules() -> None:
    legacy = ROOT / "backend" / "src" / "fitmas" / "legacy"
    assert list(legacy.glob("*.py")) == []


def test_decision_understanding_has_no_legacy_contract_fields() -> None:
    from fitmas.decision import CoachUnderstanding, PendingResolution, RequestedPlanChange, UserSignal

    checked = (CoachUnderstanding, PendingResolution, RequestedPlanChange, UserSignal)
    forbidden = {
        "fitmas_message",
        "reply_text",
        "final_reply",
        "plan_patch",
        "mutation_decision",
        "coach_decision",
        "operations",
        "command",
        "event_id",
    }

    for cls in checked:
        assert _field_names(cls).isdisjoint(forbidden), cls


def test_decision_understanding_source_does_not_mention_reply_or_patch_contracts() -> None:
    source = (DECISION / "understanding.py").read_text(encoding="utf-8")
    forbidden = (
        "fitmas_message",
        "reply_text",
        "final_reply",
        "PlanPatch",
        "MutationDecision",
        "plan_patch",
        "mutation_decision",
    )

    offenders = [token for token in forbidden if token in source]

    assert offenders == []


def test_decision_runtime_shell_has_no_behavioral_adapters_yet() -> None:
    source = (DECISION / "runtime.py").read_text(encoding="utf-8")
    forbidden = (
        "conversation_pipeline",
        "heartbeat",
        "telegram",
        "PlanMutationService",
        "MemoryMutationService",
        "ExecutionCommandService",
    )

    offenders = [token for token in forbidden if token in source]

    assert offenders == []


def test_domain_planning_package_exists_without_free_text_parsers() -> None:
    planning = ROOT / "backend" / "src" / "fitmas" / "domain" / "planning"
    assert planning.exists()
    forbidden_tokens = (
        "user_text",
        "payload.text",
        "re.search",
        "re.match",
        ".lower() in",
    )
    offenders: list[str] = []
    for path in sorted(planning.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        for token in forbidden_tokens:
            if token in source:
                offenders.append(f"{path.name}: {token}")
    assert offenders == []
