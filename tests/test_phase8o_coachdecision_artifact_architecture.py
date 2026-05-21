from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"
SCRIPTS = ROOT / "scripts"


def _source(relative: str) -> str:
    return (SRC / relative).read_text(encoding="utf-8")


def _tree(relative: str) -> ast.Module:
    return ast.parse(_source(relative), filename=relative)


def _imports(relative: str) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(_tree(relative)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def _attribute_names(relative: str) -> set[str]:
    return {
        node.attr
        for node in ast.walk(_tree(relative))
        if isinstance(node, ast.Attribute)
    }


def _constant_strings(relative: str) -> tuple[str, ...]:
    return tuple(
        str(node.value)
        for node in ast.walk(_tree(relative))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    )


def _script_source(name: str) -> str:
    return (SCRIPTS / name).read_text(encoding="utf-8")


def test_8o_artifact_module_exists() -> None:
    assert (SRC / "legacy" / "coach_decision_artifact.py").exists()


def test_8o_provider_runtime_is_removed_but_artifact_boundary_remains() -> None:
    runtime = _source("decision/coach_decision_runtime.py")
    artifact = _source("legacy/coach_decision_artifact.py")

    assert not (SRC / "legacy/coach_decision_provider.py").exists()
    assert "run_legacy_coach_decision" not in runtime
    assert "build_legacy_coach_decision_request" not in runtime
    assert "class LegacyCoachDecisionArtifact" in artifact


def test_8o_conversation_facing_modules_do_not_access_fitmas_message_directly() -> None:
    for relative in (
        "conversation_pipeline.py",
        "decision/command_application.py",
        "decision/command_mapping.py",
        "legacy/coach_command_adapter.py",
        "decision/pending_resolution.py",
        "decision/planning_outcomes.py",
        "decision/readonly_reply.py",
        "decision/planning_runtime.py",
        "legacy/understanding_shadow.py",
    ):
        assert "fitmas_message" not in _attribute_names(relative), relative
        assert "fitmas_message" not in _constant_strings(relative), relative


def test_8o_conversation_facing_modules_do_not_import_raw_legacy_models() -> None:
    forbidden = {
        "fitmas.llm.CoachDecision",
        "fitmas.llm.MutationDecision",
    }
    for relative in (
        "conversation_pipeline.py",
        "decision/coach_decision_runtime.py",
        "decision/command_application.py",
        "decision/command_mapping.py",
        "decision/pending_resolution.py",
        "decision/planning_outcomes.py",
        "decision/readonly_reply.py",
        "decision/planning_runtime.py",
        "legacy/understanding_shadow.py",
    ):
        assert not forbidden.intersection(_imports(relative)), relative


def test_8o_raw_legacy_model_imports_stay_in_compat_zone() -> None:
    allowed = {
        "llm/legacy_parser.py",
        "llm/legacy_action_compile.py",
        "llm/decision_legacy.py",
        "legacy/coach_understanding_adapter.py",
        "legacy/decision_contracts.py",
    }
    offenders: list[str] = []
    for path in SRC.rglob("*.py"):
        relative = path.relative_to(SRC).as_posix()
        if relative in allowed:
            continue
        imports = _imports(relative)
        if {
            "fitmas.llm.CoachDecision",
            "fitmas.llm.MutationDecision",
        }.intersection(imports):
            offenders.append(relative)
    assert offenders == []


def test_8o_conversation_pipeline_names_artifact_boundary() -> None:
    source = _source("conversation_pipeline.py")

    assert "legacy_decision_artifact = understanding_runtime.coach_decision_artifact_from_understanding" in source
    assert "legacy_decision_artifact = coach_decision_runtime.run_legacy_coach_decision" not in source
    assert "shadow_understanding_from_legacy_decision(user_id=user.id, decision=decision)" not in source
    assert "decision = coach_decision_runtime.run_legacy_coach_decision" not in source


def test_8o_conversation_pipeline_does_not_pass_raw_decision_to_bridges() -> None:
    source = _source("conversation_pipeline.py")

    assert "apply_coach_decision_commands(\n        db=db,\n        user=user,\n        decision=decision" not in source
    assert "apply_pending_resolution(\n            db=db,\n            user=user,\n            decision=decision" not in source
    assert "maybe_handle_planning_runtime_cutover(\n            decision=decision" not in source
    assert "compose_coach_decision_reply(\n            db=db,\n            user=user,\n            user_text=payload.text,\n            decision=decision" not in source


def test_8o_coach_decision_result_decision_property_is_not_runtime_consumed() -> None:
    offenders: list[str] = []
    for relative in (
        "conversation_pipeline.py",
        "decision/coach_decision_runtime.py",
        "decision/command_application.py",
        "decision/command_mapping.py",
        "decision/pending_resolution.py",
        "decision/planning_outcomes.py",
        "decision/readonly_reply.py",
    ):
        source = _source(relative)
        if "result.decision" in source or "CoachDecisionResult(decision=" in source:
            offenders.append(relative)
    assert offenders == []


def test_8o_retired_planning_cutover_flag_is_not_read() -> None:
    source = _source("decision/understanding_runtime.py")

    assert "FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER" not in source


def test_8o_smoke_wrapper_is_deterministic_only() -> None:
    source = _script_source("smoke-decision-runtime-coachdecision-artifact")

    assert "tests/test_phase8o_coachdecision_artifact_architecture.py" in source
    assert "tests/test_coach_decision_artifact.py" in source
    assert "tests/test_phase8n_provider_tool_loop_architecture.py" in source
    assert "tests/test_llm_legacy_tool_loop.py" in source
    assert 'echo "RESULT: OK"' in source

    forbidden_live_smokes = (
        "smoke-decision-runtime-provider-tool-loop",
        "smoke-decision-runtime-decision-legacy-split",
        "smoke-decision-runtime-decide-shrink",
        "smoke-decision-runtime-canonical-defaults",
        "smoke-decision-runtime-canonical-planning",
        "smoke-real-conversations",
        "smoke-a-plus-api",
        "smoke_a_plus_api.py",
    )
    for forbidden in forbidden_live_smokes:
        assert forbidden not in source
