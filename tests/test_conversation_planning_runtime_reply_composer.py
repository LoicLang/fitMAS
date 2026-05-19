from __future__ import annotations

from types import SimpleNamespace

from fitmas import conversation_pipeline
from fitmas.decision import DecisionExplanation, DecisionReplyComposer, ReplyContract
from fitmas.decision.reply_request import ReplyRequest, ReplyResult
from fitmas.domain.planning.models import PlanningCommandResult, PlanningDecisionResult
from fitmas.legacy import conversation_planning_bridge
from fitmas.legacy.final_reply_backend import LegacyFinalReplyBackend
from fitmas.plan_mutation_service import PlanPatchServiceResult
from fitmas.plan_patch import PlanPatch, PlanPatchOperation, PlanPatchValidation


def _planning_result(kind: str) -> PlanningDecisionResult:
    return PlanningDecisionResult(
        kind=kind,  # type: ignore[arg-type]
        selected_candidate_id="cand_1",
        candidate_options=(),
        reason="Option possible, confirmation recommandee.",
        policy_decision=None,
        selected_patch=None,
        evaluated_candidates=(),
        command_result=PlanningCommandResult(
            status="pending" if kind.startswith("pending") else "blocked",
            event_count=0,
            pending_confirmation_id=55 if kind.startswith("pending") else None,
            service_result=None,
            payload={"reason": "Option possible, confirmation recommandee."},
        ),
        pending_confirmation_id=55 if kind.startswith("pending") else None,
    )


def test_planning_runtime_mapper_uses_reply_composer(monkeypatch) -> None:
    calls = []

    class FakeComposer:
        def compose(self, outcome, context, *, user_text="", grounding_facts=()):
            calls.append((outcome, user_text))
            return ReplyResult(text="Je te propose vendredi. Tu confirmes ?", verified=True, fallback_used=False, reason=None)

    outcome = conversation_planning_bridge.conversation_outcome_from_planning_runtime_result(
        _planning_result("pending_confirmation"),
        user_text="deplace demain",
        grounding_facts=("date locale: 2026-05-14",),
        decision_reply_composer_fn=lambda: FakeComposer(),
    )

    assert calls
    assert calls[0][0].kind == "plan_pending"
    assert outcome.reply_text == "Je te propose vendredi. Tu confirmes ?"
    assert outcome.pending_confirmation is True
    assert outcome.pending_confirmation_id == 55


def test_planning_runtime_pending_reply_uses_machine_candidate_over_grounding_drift() -> None:
    backend = LegacyFinalReplyBackend(request_text_fn=lambda **_kwargs: "Je propose lundi 18. Tu confirmes ?")
    composer = DecisionReplyComposer(reply_backend=backend)
    result = _planning_result("pending_confirmation")
    result = PlanningDecisionResult(
        kind=result.kind,
        selected_candidate_id=result.selected_candidate_id,
        candidate_options=result.candidate_options,
        reason=result.reason,
        policy_decision=result.policy_decision,
        selected_patch=PlanPatch(
            coach_message="Deplacer Recuperation mobilite au lundi suivant.",
            operations=[
                PlanPatchOperation(
                    operation_type="move_session",
                    target_session_id=3,
                    target_date="2026-05-25",
                    rationale="Deplacer Recuperation mobilite au lundi suivant.",
                )
            ]
        ),
        evaluated_candidates=(
            SimpleNamespace(
                candidate=SimpleNamespace(rationale="Deplacer Recuperation mobilite au 2026-05-25")
            ),
        ),
        command_result=result.command_result,
        pending_confirmation_id=result.pending_confirmation_id,
    )

    outcome = conversation_planning_bridge.conversation_outcome_from_planning_runtime_result(
        result,
        user_text="deplace lundi prochain",
        grounding_facts=("TemporalRefs: target monday -> 2026-05-18",),
        decision_reply_composer_fn=lambda: composer,
    )

    assert "2026-05-25" in outcome.reply_text
    assert "2026-05-18" not in outcome.reply_text


def test_planning_runtime_pending_reply_uses_multi_move_machine_summary() -> None:
    backend = LegacyFinalReplyBackend(request_text_fn=lambda **_kwargs: "Je propose une seance ciblee. Tu confirmes ?")
    composer = DecisionReplyComposer(reply_backend=backend)
    result = _planning_result("pending_confirmation")
    result = PlanningDecisionResult(
        kind=result.kind,
        selected_candidate_id=result.selected_candidate_id,
        candidate_options=result.candidate_options,
        reason="Fenetre large: confirmation requise avant de deplacer plusieurs seances.",
        policy_decision=result.policy_decision,
        selected_patch=PlanPatch(
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
        ),
        evaluated_candidates=(),
        command_result=result.command_result,
        pending_confirmation_id=result.pending_confirmation_id,
    )

    outcome = conversation_planning_bridge.conversation_outcome_from_planning_runtime_result(
        result,
        user_text="je voyage de mercredi a vendredi, adapte si besoin",
        grounding_facts=(),
        decision_reply_composer_fn=lambda: composer,
    )

    assert "2 seances touchees" in outcome.reply_text
    assert "2026-05-23" in outcome.reply_text
    assert "2026-05-25" in outcome.reply_text
    assert "seance ciblee" not in outcome.reply_text
    assert "confirmes" in outcome.reply_text.lower()


def test_canonical_plan_committed_reply_uses_committed_event_summary() -> None:
    backend = LegacyFinalReplyBackend(request_text_fn=lambda **_kwargs: "J'ai remplace la seance.")
    request = ReplyRequest(
        kind="plan_committed",
        user_text="deplace lundi prochain",
        committed_events=("Recuperation mobilite deplacee au 2026-05-25.",),
        blocked_reasons=(),
        pending_summary=None,
        memory_updates=(),
        execution_updates=(),
        candidate_summaries=(),
        explanation=DecisionExplanation(
            decision_label="Adaptation appliquee",
            reason_summary="Deplacement applique.",
            evidence=(),
            tradeoff=None,
            impact={},
            protected=("verite planning",),
            next_step=None,
        ),
        contract=ReplyContract(
            mode="plan_committed",
            audience="telegram",
            allowed_claims=("plan_committed",),
            forbidden_claims=(),
        ),
    )

    reply = backend.compose(request)

    assert reply == "Recuperation mobilite deplacee au 2026-05-25."


def test_plan_patch_pending_helper_uses_decision_reply_composer(monkeypatch) -> None:
    calls = []

    class FakeComposer:
        def compose(self, outcome, context, *, user_text="", grounding_facts=()):
            calls.append(outcome)
            return ReplyResult(
                text="Je te propose ce changement. Tu confirmes ?",
                verified=True,
                fallback_used=False,
                reason=None,
            )

    monkeypatch.setattr(conversation_pipeline, "_decision_reply_composer", lambda: FakeComposer())

    service_result = PlanPatchServiceResult(
        validation=PlanPatchValidation(status="valid", operation_results=(), summary="valid"),
        patch=PlanPatch(
            coach_message="patch",
            operations=[
                PlanPatchOperation(
                    operation_type="move_session",
                    target_session_id=42,
                    target_date="2026-05-15",
                    rationale="move",
                )
            ],
        ),
    )

    reply = conversation_pipeline._build_plan_patch_confirmation_prompt(service_result)

    assert calls
    assert calls[0].kind == "plan_pending"
    assert reply == "Je te propose ce changement. Tu confirmes ?"


def test_planning_runtime_mapper_uses_fallback_if_composer_rejects(monkeypatch) -> None:
    class FakeComposer:
        def compose(self, outcome, context, *, user_text="", grounding_facts=()):
            return ReplyResult(text=None, verified=False, fallback_used=True, reason="voice")

    outcome = conversation_planning_bridge.conversation_outcome_from_planning_runtime_result(
        _planning_result("block"),
        user_text="force la seance",
        grounding_facts=(),
        decision_reply_composer_fn=lambda: FakeComposer(),
    )

    assert outcome.response_mode == "planning_runtime_block"
    assert outcome.reply_text == "Option possible, confirmation recommandee."


def test_planning_runtime_mapper_downgrades_commit_without_event_evidence() -> None:
    result = PlanningDecisionResult(
        kind="commit",
        selected_candidate_id="cand_1",
        candidate_options=(),
        reason="Aucun event de mutation n'a ete produit.",
        policy_decision=None,
        selected_patch=None,
        evaluated_candidates=(),
        command_result=PlanningCommandResult(
            status="blocked",
            event_count=0,
            pending_confirmation_id=None,
            service_result=None,
            payload={"reason": "missing_commit_event"},
        ),
        pending_confirmation_id=None,
    )

    class FakeComposer:
        def compose(self, outcome, context, *, user_text="", grounding_facts=()):
            assert outcome.kind == "plan_blocked"
            assert "plan_committed" in outcome.reply_contract.forbidden_claims
            return ReplyResult(text="Je bloque.", verified=True, fallback_used=False, reason=None)

    outcome = conversation_planning_bridge.conversation_outcome_from_planning_runtime_result(
        result,
        user_text="deplace",
        grounding_facts=(),
        decision_reply_composer_fn=lambda: FakeComposer(),
    )

    assert outcome.response_mode == "planning_runtime_block"
    assert outcome.mutation_applied is False
    assert outcome.pending_confirmation is False
