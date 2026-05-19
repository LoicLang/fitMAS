from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CONVERSATION_PIPELINE = REPO_ROOT / "backend/src/fitmas/conversation_pipeline.py"


def test_conversation_pipeline_no_longer_calls_planning_snapshot_flow() -> None:
    source = CONVERSATION_PIPELINE.read_text()

    forbidden = (
        "build_planning_snapshot",
        "generate_adaptation_proposal",
        "compile_adaptation_proposal",
        "_maybe_handle_plan_adaptation_snapshot_proposal",
        "_record_planning_snapshot_fallback",
        '"planning_snapshot_flow"',
        "source=\"planning_snapshot_flow\"",
    )
    offenders = [item for item in forbidden if item in source]

    assert offenders == []
