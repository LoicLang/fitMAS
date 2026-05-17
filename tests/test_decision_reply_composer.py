from __future__ import annotations

from fitmas.decision import CommandResult, DecisionExplanation, DecisionOutcome, ReplyContract
from fitmas.decision.output_verifier import DecisionOutputVerifier
from fitmas.decision.reply_composer import DecisionReplyComposer
from fitmas.decision.reply_request import ReplyRequest, ReplyResult


def test_reply_request_carries_machine_truth_not_legacy_objects() -> None:
    request = ReplyRequest(
        kind="plan_pending",
        user_text="deplace demain",
        committed_events=(),
        blocked_reasons=(),
        pending_summary="Deplacer la seance a vendredi.",
        memory_updates=(),
        execution_updates=(),
        candidate_summaries=("move_friday: seance vendredi",),
        explanation=DecisionExplanation(
            decision_label="Changement a confirmer",
            reason_summary="La semaine change sensiblement.",
            evidence=("seance cible resolue",),
            tradeoff="moins de friction",
            impact={"risk": "medium"},
            protected=("coherence semaine",),
            next_step="attendre confirmation",
        ),
        contract=ReplyContract(
            mode="plan_pending",
            audience="telegram",
            allowed_claims=("pending_created",),
            forbidden_claims=("plan_committed",),
        ),
    )

    assert request.kind == "plan_pending"
    assert request.pending_summary == "Deplacer la seance a vendredi."
    assert "PlanPatch" not in repr(request)
    assert "CoachDecision" not in repr(request)


def test_reply_result_knows_if_output_is_verified() -> None:
    result = ReplyResult(text="Tu confirmes ?", verified=True, fallback_used=False, reason=None)

    assert result.text == "Tu confirmes ?"
    assert result.verified is True


class FakeReplyBackend:
    def __init__(self, text: str | None):
        self.text = text
        self.requests = []

    def compose(self, request):
        self.requests.append(request)
        return self.text


def _outcome(kind: str, *, applied: bool = False) -> DecisionOutcome:
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
        candidates=("move_friday: deplacer vendredi",),
        selected_candidate_id="move_friday",
        explanation=DecisionExplanation(
            decision_label="Adaptation planning",
            reason_summary="On protege la coherence.",
            evidence=("session cible resolue",),
            tradeoff="moins de charge demain",
            impact={"weekly_load_delta": "-8%"},
            protected=("recuperation",),
            next_step="confirmer",
        ),
        reply_contract=ReplyContract(
            mode=kind,
            audience="telegram",
            allowed_claims=("plan_committed",) if applied else ("pending_created",),
            forbidden_claims=() if applied else ("plan_committed",),
        ),
    )


def test_composer_builds_pending_request_from_outcome() -> None:
    backend = FakeReplyBackend("Je te propose vendredi. Tu confirmes ?")
    composer = DecisionReplyComposer(reply_backend=backend, verifier=DecisionOutputVerifier())

    result = composer.compose(_outcome("plan_pending"), context=None, user_text="deplace demain")

    assert result.text == "Je te propose vendredi. Tu confirmes ?"
    assert result.verified is True
    assert backend.requests[0].kind == "plan_pending"
    assert backend.requests[0].pending_summary == "On protege la coherence."
    assert backend.requests[0].candidate_summaries == ("move_friday: deplacer vendredi",)


def test_composer_falls_back_to_outcome_explanation_when_backend_fails() -> None:
    backend = FakeReplyBackend(None)
    composer = DecisionReplyComposer(reply_backend=backend, verifier=DecisionOutputVerifier())

    result = composer.compose(_outcome("plan_blocked"), context=None, user_text="force la seance dure")

    assert result.fallback_used is True
    assert result.verified is True
    assert result.text is not None
    assert "On protege la coherence" in result.text


def test_composer_rejects_backend_uncommitted_action_claim() -> None:
    backend = FakeReplyBackend("J'ai deplace la seance a vendredi.")
    composer = DecisionReplyComposer(reply_backend=backend, verifier=DecisionOutputVerifier())

    result = composer.compose(_outcome("plan_pending"), context=None, user_text="deplace demain")

    assert result.verified is True
    assert result.fallback_used is True
    assert result.text != "J'ai deplace la seance a vendredi."


def test_composer_plan_pending_created_requires_confirmation_step() -> None:
    backend = FakeReplyBackend("Option possible, confirmation recommandee.")
    composer = DecisionReplyComposer(reply_backend=backend, verifier=DecisionOutputVerifier())
    outcome = _outcome("plan_pending")
    outcome = DecisionOutcome(
        kind=outcome.kind,
        commands=outcome.commands,
        applied_commands=outcome.applied_commands,
        candidates=outcome.candidates,
        selected_candidate_id=outcome.selected_candidate_id,
        explanation=DecisionExplanation(
            decision_label="Adaptation a confirmer",
            reason_summary="Option possible, confirmation recommandee.",
            evidence=("pending_id=1",),
            tradeoff=None,
            impact={},
            protected=("coherence semaine",),
            next_step="Tu confirmes ?",
        ),
        reply_contract=outcome.reply_contract,
    )

    result = composer.compose(outcome, context=None, user_text="force la seance dure")

    assert result.verified is True
    assert result.fallback_used is True
    assert result.text == "Option possible, confirmation recommandee. Tu confirmes ?"


def test_composer_plan_pending_fallback_uses_next_step() -> None:
    backend = FakeReplyBackend(None)
    composer = DecisionReplyComposer(reply_backend=backend, verifier=DecisionOutputVerifier())
    outcome = _outcome("plan_pending")
    outcome = DecisionOutcome(
        kind=outcome.kind,
        commands=outcome.commands,
        applied_commands=outcome.applied_commands,
        candidates=outcome.candidates,
        selected_candidate_id=outcome.selected_candidate_id,
        explanation=DecisionExplanation(
            decision_label="Proposition gardee",
            reason_summary="La proposition reste en attente.",
            evidence=("pending_id=1",),
            tradeoff=None,
            impact={},
            protected=("coherence semaine",),
            next_step="Dis-moi si tu veux l'appliquer ou la modifier.",
        ),
        reply_contract=outcome.reply_contract,
    )

    result = composer.compose(outcome, context=None, user_text="j'attends")

    assert result.fallback_used is True
    assert result.text == "La proposition reste en attente. Dis-moi si tu veux l'appliquer ou la modifier."


def test_composer_plan_choice_pending_fallback_uses_next_step() -> None:
    backend = FakeReplyBackend(None)
    composer = DecisionReplyComposer(reply_backend=backend, verifier=DecisionOutputVerifier())
    outcome = _outcome("plan_choice_pending")
    outcome = DecisionOutcome(
        kind=outcome.kind,
        commands=outcome.commands,
        applied_commands=outcome.applied_commands,
        candidates=outcome.candidates,
        selected_candidate_id=None,
        explanation=DecisionExplanation(
            decision_label="Choix requis",
            reason_summary="Je ne retrouve pas cette option.",
            evidence=("pending_id=1",),
            tradeoff=None,
            impact={},
            protected=("coherence semaine",),
            next_step="Rechoisis parmi les options proposees.",
        ),
        reply_contract=ReplyContract(
            mode="pending_choice_invalid_selection",
            audience="telegram",
            allowed_claims=("pending_kept",),
            forbidden_claims=("plan_committed",),
        ),
    )

    result = composer.compose(outcome, context=None, user_text="l'autre")

    assert result.fallback_used is True
    assert result.text == "Je ne retrouve pas cette option. Rechoisis parmi les options proposees."
