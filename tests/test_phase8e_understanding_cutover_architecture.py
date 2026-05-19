from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"


def _source(relative: str) -> str:
    return (SRC / relative).read_text(encoding="utf-8")


def _imports(relative: str) -> set[str]:
    path = SRC / relative
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def test_8e_llm_understanding_service_exists_without_legacy_contracts() -> None:
    source = _source("llm/understanding_service.py")
    imports = _imports("llm/understanding_service.py")

    assert "class LLMUnderstandingService" in source
    assert "parse_coach_understanding_payload" in source
    assert "fitmas.decision" in imports
    assert "fitmas.llm.prompts.understanding" in imports
    assert "fitmas.llm.gateway" in imports
    assert "fitmas.llm.decision_legacy" not in imports
    assert "fitmas.legacy" not in imports
    assert "fitmas.conversation_pipeline" not in imports
    assert "PlanPatch" not in source
    assert "MutationDecision" not in source
    assert "fitmas_message" not in source
    assert "reply_text" not in source


def test_8e_conversation_uses_understanding_bridge_not_direct_llm_service() -> None:
    source = _source("conversation_pipeline.py")

    assert "conversation_understanding_bridge" in source
    assert "LLMUnderstandingService" not in source
    assert "build_understanding_prompt" not in source
    assert "canonical_understanding" in source


def test_8e_understanding_bridge_is_legacy_boundary() -> None:
    source = _source("legacy/conversation_understanding_bridge.py")

    assert "FITMAS_UNDERSTANDING_RUNTIME_SHADOW" in source
    assert "FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER" not in source
    assert "run_canonical_understanding_shadow" in source
    assert "understanding_to_turn_context_payload" in source
    assert "from fitmas.llm.understanding_service import" in source


def test_8e_planning_runtime_accepts_canonical_understanding_input() -> None:
    adapter = _source("legacy/planning_runtime_adapter.py")
    bridge = _source("legacy/conversation_canonical_planning_bridge.py")

    assert "understanding: CoachUnderstanding | None" in adapter
    assert "if understanding is None" in adapter
    assert "understanding.requested_change" in adapter
    assert "run_planning_runtime_attempt_from_understanding" in bridge


def test_8e_decision_package_still_has_no_llm_or_legacy_imports() -> None:
    offenders: list[str] = []
    for path in sorted((SRC / "decision").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            module = None
            if isinstance(node, ast.ImportFrom):
                module = node.module
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(("fitmas.llm", "fitmas.legacy", "fitmas.conversation_pipeline")):
                        offenders.append(f"{path.name}:{alias.name}")
                continue
            if module and module.startswith(("fitmas.llm", "fitmas.legacy", "fitmas.conversation_pipeline")):
                offenders.append(f"{path.name}:{module}")

    assert offenders == []


def test_8e_understanding_prompt_schema_matches_canonical_signal_types() -> None:
    source = _source("llm/prompts/understanding.py")

    assert "health | availability | preference | execution | readiness | planning | pending | other" in source
    assert "fatigue | pain | availability" not in source
    assert "accept_pending | reject_pending | modify_pending | ignore | needs_clarification" in source
