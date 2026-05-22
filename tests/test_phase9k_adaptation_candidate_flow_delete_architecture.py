from __future__ import annotations

from pathlib import Path


def test_conversation_runtime_no_longer_uses_adaptation_candidate_flow() -> None:
    source = Path("backend/src/fitmas/decision/conversation_pipeline.py").read_text()

    forbidden = (
        "adaptation_candidate_flow",
        "_maybe_handle_plan_adaptation_candidates",
        "_should_use_plan_adaptation_candidate_flow",
        "generate_plan_patch_candidates",
        "CandidateGenerationInput",
        "plan_patch_candidate_generator",
        "plan_patch_candidate_reviewer",
        "decide_adaptation_policy",
        "evaluate_plan_patch_candidate",
        "plan_adaptation_candidates",
    )

    for marker in forbidden:
        assert marker not in source
