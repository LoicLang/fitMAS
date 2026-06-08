from __future__ import annotations

from fitmas.legacy.llm.prompts.reviewer import ReviewerPromptCandidate, build_reviewer_prompt


def test_reviewer_prompt_only_allows_candidate_id_selection() -> None:
    rendered = build_reviewer_prompt(
        (
            ReviewerPromptCandidate(
                candidate_id="candidate_a",
                rationale="préserve la séance clé",
                expected_tradeoff="moins de charge ce soir",
                score_total=0.82,
                score_delta=0.2,
                policy_hint="commit",
                findings=("charge stable",),
                operations=("replace_session target_session_id=12",),
            ),
            ReviewerPromptCandidate(
                candidate_id="candidate_b",
                rationale="force l'intensité",
                expected_tradeoff="risque fatigue",
                score_total=0.41,
                score_delta=-0.1,
                policy_hint="pending",
                findings=("fatigue proche",),
                operations=("move_session target_session_id=12 target_date=2026-05-16",),
            ),
        )
    )

    text = f"{rendered.system}\n{rendered.prompt}"
    assert "preferred_candidate_id" in text
    assert "candidate_a" in text
    assert "candidate_b" in text
    assert "Ne produis aucun patch" in text
    assert "user-facing" not in text
    assert "fitmas_message" not in text
