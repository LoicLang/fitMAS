from __future__ import annotations

from dataclasses import dataclass

from .base import PromptRender, render_json_block


@dataclass(frozen=True, slots=True)
class ReviewerPromptCandidate:
    candidate_id: str
    rationale: str
    expected_tradeoff: str | None
    score_total: float | None
    score_delta: float | None
    policy_hint: str | None
    findings: tuple[str, ...]
    operations: tuple[str, ...]


def build_reviewer_prompt(candidates: tuple[ReviewerPromptCandidate, ...]) -> PromptRender:
    system = (
        "Tu es FitMAS SportReviewer LLM. "
        "Return candidate_id only. "
        "Tu choisis uniquement parmi les candidate_id fournis. "
        "Ne produis aucun patch, aucune operation, aucune commande et aucun texte visible utilisateur."
    )
    payload = {
        "candidates": [
            {
                "candidate_id": candidate.candidate_id,
                "rationale": candidate.rationale,
                "expected_tradeoff": candidate.expected_tradeoff,
                "score_total": candidate.score_total,
                "score_delta": candidate.score_delta,
                "policy_hint": candidate.policy_hint,
                "findings": list(candidate.findings),
                "operations": list(candidate.operations),
            }
            for candidate in candidates
        ],
        "output_contract": {
            "preferred_candidate_id": "one of candidates[].candidate_id",
            "confidence": "0..1",
            "rationale": ["short reasons based only on candidate facts"],
        },
    }
    return PromptRender(
        system=system,
        prompt=(
            "Choisis le meilleur compromis sportif parmi ces candidates deja construites.\n\n"
            f"Contexte JSON:\n{render_json_block(payload)}"
        ),
        max_tokens=600,
    )
