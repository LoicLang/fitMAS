from __future__ import annotations

from fitmas.domain.planning.patch_summary import summarize_plan_patch_for_user
from fitmas.plan_patch import PlanPatch, PlanPatchOperation


def test_summarizes_multi_move_patch_without_single_target_language() -> None:
    patch = PlanPatch(
        coach_message="patch",
        operations=[
            PlanPatchOperation(
                operation_type="move_session",
                target_session_id=1,
                target_date="2026-05-23",
                rationale="travel",
            ),
            PlanPatchOperation(
                operation_type="move_session",
                target_session_id=2,
                target_date="2026-05-25",
                rationale="travel",
            ),
        ],
    )

    summary = summarize_plan_patch_for_user(patch)

    assert summary == (
        "deplacer les 2 seances touchees apres la fenetre, en gardant leur ordre: "
        "2026-05-23 (samedi), puis 2026-05-25 (lundi)"
    )
    assert "seance ciblee" not in summary


def test_summarizes_single_move_patch() -> None:
    patch = PlanPatch(
        coach_message="patch",
        operations=[
            PlanPatchOperation(
                operation_type="move_session",
                target_session_id=3,
                target_date="2026-05-25",
                rationale="move",
            ),
        ],
    )

    assert summarize_plan_patch_for_user(patch) == "deplacer la seance ciblee au 2026-05-25 (lundi)"
