from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"
SCRIPTS = ROOT / "scripts"


def _source(relative: str) -> str:
    return (SRC / relative).read_text(encoding="utf-8")


def test_8q_understanding_bridge_exposes_provider_pivot_boundary() -> None:
    source = _source("decision/understanding_runtime.py")

    assert "def canonical_provider_pivot_enabled(" in source
    assert "FITMAS_CANONICAL_PROVIDER_NON_PLANNING" in source
    assert "def should_use_canonical_understanding_without_legacy(" in source
    assert "def coach_decision_artifact_from_understanding(" in source
    assert "commands_from_understanding(" in source


def test_8q_conversation_pipeline_runs_canonical_before_legacy_decide() -> None:
    source = _source("conversation_pipeline.py")

    canonical_index = source.index("run_canonical_understanding_shadow(")
    legacy_index = source.index("run_legacy_coach_decision(")
    assert canonical_index < legacy_index
    assert "should_use_canonical_understanding_without_legacy(" in source
    assert "coach_decision_artifact_from_understanding(" in source


def test_8q_smoke_wrapper_is_deterministic_only() -> None:
    source = (SCRIPTS / "smoke-decision-runtime-canonical-provider-pivot").read_text(encoding="utf-8")

    assert "tests/test_phase8q_canonical_provider_pivot_architecture.py" in source
    assert "tests/test_conversation_understanding_bridge.py" in source
    assert "smoke-decision-runtime-decision-legacy-support-split" in source
    assert "smoke-a-plus-api" not in source
    assert "smoke-real-conversations" not in source
