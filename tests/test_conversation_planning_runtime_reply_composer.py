from __future__ import annotations

from fitmas import conversation_pipeline
from fitmas.decision.reply_request import ReplyResult
from fitmas.domain.planning.models import PlanningCommandResult, PlanningDecisionResult
from fitmas.legacy import conversation_planning_bridge
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


def test_planning_runtime_cutover_is_enabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("FITMAS_PLANNING_RUNTIME_CUTOVER", raising=False)

    assert conversation_pipeline._planning_runtime_cutover_enabled() is True


def test_planning_runtime_cutover_can_be_disabled_explicitly(monkeypatch) -> None:
    monkeypatch.setenv("FITMAS_PLANNING_RUNTIME_CUTOVER", "0")

    assert conversation_pipeline._planning_runtime_cutover_enabled() is False


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
