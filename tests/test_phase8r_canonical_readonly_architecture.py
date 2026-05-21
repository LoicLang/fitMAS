from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"
SCRIPTS = ROOT / "scripts"


def _source(relative: str) -> str:
    return (SRC / relative).read_text(encoding="utf-8")


def test_8r_canonical_readonly_bridge_exists() -> None:
    source = _source("decision/readonly_reply.py")

    assert "def canonical_readonly_provider_enabled(" in source
    assert "FITMAS_CANONICAL_READONLY_PROVIDER" in source
    assert "def should_use_canonical_readonly_without_legacy(" in source
    assert "def compose_canonical_readonly_reply(" in source
    assert "DecisionOutcome(" in source
    assert "DecisionReplyComposer" not in source


def test_8r_pipeline_routes_readonly_before_removed_provider_clarification() -> None:
    source = _source("conversation_pipeline.py")

    readonly_index = source.index("should_use_canonical_readonly_without_legacy(")
    clarification_index = source.index("canonical_provider_clarification_outcome(")
    assert readonly_index < clarification_index
    assert "run_legacy_coach_decision(" not in source
    assert "compose_canonical_readonly_reply(" in source


def test_8s_readonly_provider_default_on_but_opt_out_supported() -> None:
    source = _source("decision/readonly_reply.py")

    assert 'return _env_flag_enabled("FITMAS_CANONICAL_READONLY_PROVIDER", default=True)' in source
    assert 'raw.strip().lower() in {"1", "true", "yes", "on"}' in source


def test_8r_smoke_wrapper_is_deterministic_only() -> None:
    source = (SCRIPTS / "smoke-decision-runtime-canonical-readonly").read_text(encoding="utf-8")

    assert "tests/test_phase8r_canonical_readonly_architecture.py" in source
    assert "tests/test_conversation_canonical_readonly_bridge.py" in source
    assert "smoke-decision-runtime-canonical-provider-pivot" in source
    assert "smoke-a-plus-api" not in source
    assert "smoke-real-conversations" not in source
