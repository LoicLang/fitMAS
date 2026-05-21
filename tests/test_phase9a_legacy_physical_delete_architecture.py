from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text()


def test_conversation_pipeline_no_longer_calls_legacy_planning_runtime_cutover() -> None:
    source = _read("backend/src/fitmas/conversation_pipeline.py")

    assert "maybe_handle_planning_runtime_cutover" not in source
    assert "understanding_runtime_planning_cutover_enabled" not in source
    assert "_planning_runtime_cutover_enabled" not in source


def test_conversation_planning_bridge_is_physically_removed() -> None:
    assert not (ROOT / "backend/src/fitmas/legacy/conversation_planning_bridge.py").exists()


def test_understanding_bridge_no_longer_reads_retired_planning_cutover_flag() -> None:
    source = _read("backend/src/fitmas/decision/understanding_runtime.py")

    assert "understanding_runtime_planning_cutover_enabled" not in source
    assert "FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER" not in source


def test_active_smoke_scripts_no_longer_use_retired_planning_cutover_flag() -> None:
    retired_flag = "FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER"
    active_scripts = (
        "scripts/smoke_a_plus_api.py",
        "scripts/smoke-decision-runtime-canonical-defaults",
        "scripts/smoke-decision-runtime-canonical-planning",
        "scripts/smoke-decision-runtime-canonical-planning-default",
    )

    for path in active_scripts:
        assert retired_flag not in _read(path)


def test_empty_availability_candidate_route_is_physically_removed_from_conversation_pipeline() -> None:
    source = _read("backend/src/fitmas/conversation_pipeline.py")

    assert "availability_no_affected_session" not in source
    assert "_availability_no_affected_sport_session" not in source
    assert "_availability_no_affected_session_reply" not in source
