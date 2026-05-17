from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"
SCRIPTS = ROOT / "scripts"


def _source(relative: str) -> str:
    return (SRC / relative).read_text(encoding="utf-8")


def test_8t_canonical_planning_bridge_exists_and_is_opt_in() -> None:
    source = _source("legacy/conversation_canonical_planning_bridge.py")

    assert "def canonical_planning_provider_enabled(" in source
    assert "FITMAS_CANONICAL_PLANNING_PROVIDER" in source
    assert 'default=False' in source
    assert "def should_use_canonical_planning_without_legacy(" in source
    assert "def handle_canonical_planning(" in source
    assert "run_planning_runtime_attempt_from_understanding" in source
    assert "run_legacy_coach_decision" not in source


def test_8t_pipeline_routes_canonical_planning_before_legacy_decide() -> None:
    source = _source("conversation_pipeline.py")

    planning_index = source.index("should_use_canonical_planning_without_legacy(")
    legacy_index = source.index("run_legacy_coach_decision(")
    assert planning_index < legacy_index
    assert "handle_canonical_planning(" in source


def test_8t_planning_adapter_has_direct_understanding_entrypoint() -> None:
    source = _source("legacy/planning_runtime_adapter.py")

    assert "def run_planning_runtime_attempt_from_understanding(" in source
    assert "coach_decision_artifact_to_understanding" in source


def test_8t_planning_command_service_reuses_matching_active_pending() -> None:
    source = _source("domain/planning/mutation_service.py")

    assert "get_active_pending_mutation_confirmation" in source
    assert "reused_pending_confirmation" in source


def test_8t_planning_outcome_adapter_requires_command_evidence() -> None:
    source = _source("legacy/planning_outcome_adapter.py")

    assert "missing_commit_event" in source
    assert "missing_pending_confirmation" in source


def test_8t_smoke_wrapper_is_deterministic_only() -> None:
    source = (SCRIPTS / "smoke-decision-runtime-canonical-planning-provider").read_text(encoding="utf-8")

    assert "tests/test_phase8t_canonical_planning_provider_architecture.py" in source
    assert "tests/test_conversation_canonical_planning_bridge.py" in source
    assert "tests/test_domain_planning_mutation_service.py" in source
    assert "smoke-decision-runtime-canonical-readonly" in source
    assert "smoke-a-plus-api" not in source
    assert "smoke-real-conversations" not in source
