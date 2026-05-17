from __future__ import annotations

from fitmas.decision import CommandResult, DecisionExplanation, DecisionOutcome, ReplyContract
from fitmas.decision.output_verifier import DecisionOutputVerifier


def _outcome(kind: str, *, applied: bool) -> DecisionOutcome:
    return DecisionOutcome(
        kind=kind,  # type: ignore[arg-type]
        commands=(),
        applied_commands=(
            CommandResult(
                command_id="cmd_1",
                domain="planning",
                name="move_session",
                status="applied",
                event_id="evt_1",
                payload={"summary": "Footing deplace vendredi."},
            ),
        )
        if applied
        else (),
        candidates=(),
        selected_candidate_id=None,
        explanation=DecisionExplanation(
            decision_label="label",
            reason_summary="reason",
            evidence=(),
            tradeoff=None,
            impact={},
            protected=(),
            next_step=None,
        ),
        reply_contract=ReplyContract(
            mode=kind,
            audience="telegram",
            allowed_claims=("plan_committed",) if applied else (),
            forbidden_claims=() if applied else ("plan_committed",),
        ),
    )


def test_verifier_blocks_action_claim_without_applied_event() -> None:
    result = DecisionOutputVerifier().verify(
        "J'ai deplace la seance a vendredi.",
        _outcome("plan_pending", applied=False),
        None,
    )

    assert result.allowed is False
    assert result.reason == "uncommitted_action_claim"


def test_verifier_allows_action_claim_with_applied_event() -> None:
    result = DecisionOutputVerifier().verify(
        "C'est cale vendredi.",
        _outcome("plan_committed", applied=True),
        None,
    )

    assert result.allowed is True
    assert result.text == "C'est cale vendredi."


def test_verifier_blocks_internal_jargon() -> None:
    result = DecisionOutputVerifier().verify(
        "Le runtime a cree un patch.",
        _outcome("plan_blocked", applied=False),
        None,
    )

    assert result.allowed is False
    assert result.reason == "internal_jargon"
