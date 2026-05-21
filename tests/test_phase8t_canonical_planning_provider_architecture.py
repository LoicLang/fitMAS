from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"
SCRIPTS = ROOT / "scripts"


def _source(relative: str) -> str:
    return (SRC / relative).read_text(encoding="utf-8")


def test_8t_canonical_planning_bridge_exists_and_is_default_on_with_opt_out() -> None:
    source = _source("decision/planning_runtime.py")

    assert "def canonical_planning_provider_enabled(" in source
    assert "FITMAS_CANONICAL_PLANNING_PROVIDER" in source
    assert 'default=True' in source
    assert "def should_use_canonical_planning_without_legacy(" in source
    assert "def handle_canonical_planning(" in source
    assert "run_planning_runtime_attempt_from_understanding" in source
    assert "run_legacy_coach_decision" not in source


def test_8t_pipeline_routes_canonical_planning_before_removed_provider_clarification() -> None:
    router = _source("decision/turn_router.py")
    planning_route = _source("decision/turn_planning_route.py")

    planning_index = router.index("route_with_existing_understanding(")
    clarification_index = router.index("canonical_provider_clarification_outcome(")
    assert planning_index < clarification_index
    assert "run_legacy_coach_decision(" not in router
    assert "handle_canonical_planning(" not in router
    assert "should_use_canonical_planning_without_legacy(" in planning_route
    assert "handle_canonical_planning(" in planning_route


def test_8t_planning_adapter_has_direct_understanding_entrypoint() -> None:
    source = _source("decision/planning_runtime.py")

    assert "def run_planning_runtime_attempt_from_understanding(" in source
    assert "coach_decision_artifact_to_understanding" not in source


def test_8t_planning_command_service_reuses_matching_active_pending() -> None:
    source = _source("domain/planning/mutation_service.py")

    assert "get_active_pending_mutation_confirmation" in source
    assert "reused_pending_confirmation" in source


def test_8t_planning_outcome_adapter_requires_command_evidence() -> None:
    source = _source("decision/planning_outcomes.py")

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


def test_8u_default_planning_smoke_wrapper_exists_without_provider_export() -> None:
    source = (SCRIPTS / "smoke-decision-runtime-canonical-planning-default").read_text(encoding="utf-8")

    assert "FITMAS_CANONICAL_PLANNING_PROVIDER=1" not in source
    assert "unset FITMAS_CANONICAL_PLANNING_PROVIDER" in source
    assert "smoke-a-plus-api" in source
    assert "move_hard_close" in source
    assert "move_easy_then_confirm" in source
