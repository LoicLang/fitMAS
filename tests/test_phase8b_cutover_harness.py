from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "smoke-decision-runtime-cutover"


def test_cutover_harness_exists_and_sets_runtime_flags() -> None:
    assert SCRIPT.exists()
    source = SCRIPT.read_text(encoding="utf-8")

    assert "FITMAS_PLANNING_RUNTIME_CUTOVER=1" not in source
    assert "FITMAS_HEARTBEAT_RUNTIME_CUTOVER=1" in source
    assert "FITMAS_HEARTBEAT_RUNTIME_VERIFY_ENFORCE=1" in source


def test_cutover_harness_runs_targeted_tests_before_real_smokes() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    test_index = source.index("tests/test_phase9a_legacy_physical_delete_architecture.py")
    smoke_index = source.index("smoke-real-conversations")
    assert test_index < smoke_index


def test_cutover_harness_covers_critical_smoke_scenarios() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    required = {
        "heartbeat_non_completion",
        "compound_non_completion_swap",
        "golden_case_autonomy",
        "today_unavailability",
        "move_easy_then_confirm",
    }

    assert sorted(token for token in required if token not in source) == []
