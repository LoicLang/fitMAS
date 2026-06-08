from __future__ import annotations

from typing import Any, Sequence

from sqlalchemy.orm import Session

from fitmas.legacy.domain.planning.models import PlanningCommandResult, PlanningDecisionResult
from fitmas.legacy.domain.planning.mutation_permissions import (
    default_confirmation_expiry,
    serialize_plan_patch_choice_confirmation,
    serialize_plan_patch_confirmation,
)
from fitmas.legacy.domain.planning.patch_mutation_service import apply_patch_for_user
from fitmas.legacy.domain.planning.candidates import PlanPatchCandidate
from fitmas.legacy.domain.coaching import repo_conversation


class PlanningCommandService:
    def __init__(self, *, db: Session, user: Any):
        self._db = db
        self._user = user

    def apply(
        self,
        decision: PlanningDecisionResult,
        *,
        source_text: str,
        coach_state_bundle: Any | None,
        activities: Sequence[Any],
        active_facts: Sequence[Any],
    ) -> PlanningCommandResult:
        if decision.kind == "commit":
            return self._commit(
                decision,
                coach_state_bundle=coach_state_bundle,
                activities=activities,
                active_facts=active_facts,
            )
        if decision.kind == "pending_confirmation":
            return self._pending_confirmation(decision, source_text=source_text)
        if decision.kind == "pending_choice":
            return self._pending_choice(decision, source_text=source_text)
        return PlanningCommandResult(
            status="blocked",
            event_count=0,
            pending_confirmation_id=None,
            service_result=None,
            payload={"reason": decision.reason},
        )

    def _commit(
        self,
        decision: PlanningDecisionResult,
        *,
        coach_state_bundle: Any | None,
        activities: Sequence[Any],
        active_facts: Sequence[Any],
    ) -> PlanningCommandResult:
        if decision.selected_patch is None:
            return _blocked_result("missing_selected_patch")
        service_result = apply_patch_for_user(
            self._db,
            user=self._user,
            patch=decision.selected_patch,
            source="conversation",
            trigger_type="planning_decision_runtime",
            explained_to_user=True,
            coach_state_bundle=coach_state_bundle,
            activities=activities,
            active_facts=active_facts,
        )
        event_count = _event_count(service_result)
        payload = {
            "selected_candidate_id": decision.selected_candidate_id,
            "event_count": event_count,
        }
        if event_count <= 0:
            payload["reason"] = "missing_commit_event"
        return PlanningCommandResult(
            status="applied" if event_count > 0 else "blocked",
            event_count=event_count,
            pending_confirmation_id=None,
            service_result=service_result,
            payload=payload,
        )

    def _pending_confirmation(self, decision: PlanningDecisionResult, *, source_text: str) -> PlanningCommandResult:
        if decision.selected_patch is None:
            return _blocked_result("missing_selected_patch")
        decision_json = serialize_plan_patch_confirmation(decision.selected_patch)
        existing = _matching_active_pending(
            self._db,
            user_id=self._user.id,
            mutation_type="plan_patch",
            decision_json=decision_json,
        )
        if existing is not None:
            return PlanningCommandResult(
                status="pending",
                event_count=0,
                pending_confirmation_id=existing.id,
                service_result=None,
                payload={
                    "selected_candidate_id": decision.selected_candidate_id,
                    "reused_pending_confirmation": True,
                },
            )
        row = repo_conversation.create_pending_mutation_confirmation(
            self._db,
            user_id=self._user.id,
            impact_level="high",
            reason=decision.reason,
            mutation_type="plan_patch",
            summary=decision.reason,
            source_text=source_text,
            decision_json=decision_json,
            expires_at=default_confirmation_expiry(),
        )
        return PlanningCommandResult(
            status="pending",
            event_count=0,
            pending_confirmation_id=row.id,
            service_result=None,
            payload={"selected_candidate_id": decision.selected_candidate_id},
        )

    def _pending_choice(self, decision: PlanningDecisionResult, *, source_text: str) -> PlanningCommandResult:
        selected_ids = set(decision.candidate_options)
        choice_candidates = tuple(
            _candidate_with_evaluated_patch(evaluated)
            for evaluated in decision.evaluated_candidates
            if evaluated.candidate.id in selected_ids
            and getattr(evaluated, "patch", None) is not None
        )
        decision_json = serialize_plan_patch_choice_confirmation(choice_candidates)
        existing = _matching_active_pending(
            self._db,
            user_id=self._user.id,
            mutation_type="plan_patch_choice",
            decision_json=decision_json,
        )
        if existing is not None:
            return PlanningCommandResult(
                status="pending",
                event_count=0,
                pending_confirmation_id=existing.id,
                service_result=None,
                payload={
                    "candidate_options": decision.candidate_options,
                    "reused_pending_confirmation": True,
                },
            )
        row = repo_conversation.create_pending_mutation_confirmation(
            self._db,
            user_id=self._user.id,
            impact_level="medium",
            reason=decision.reason,
            mutation_type="plan_patch_choice",
            summary=decision.reason,
            source_text=source_text,
            decision_json=decision_json,
            expires_at=default_confirmation_expiry(),
        )
        return PlanningCommandResult(
            status="pending",
            event_count=0,
            pending_confirmation_id=row.id,
            service_result=None,
            payload={"candidate_options": decision.candidate_options},
        )


def _event_count(service_result: Any) -> int:
    mutation_result = getattr(service_result, "mutation_result", None)
    return int(getattr(mutation_result, "event_count", 0) or 0)


def _blocked_result(reason: str) -> PlanningCommandResult:
    return PlanningCommandResult(
        status="blocked",
        event_count=0,
        pending_confirmation_id=None,
        service_result=None,
        payload={"reason": reason},
    )


def _matching_active_pending(db: Session, *, user_id: int, mutation_type: str, decision_json: str) -> Any | None:
    row = repo_conversation.get_active_pending_mutation_confirmation(db, user_id)
    if row is None:
        return None
    if str(getattr(row, "status", "") or "") != "pending":
        return None
    if str(getattr(row, "mutation_type", "") or "") != mutation_type:
        return None
    if str(getattr(row, "decision_json", "") or "") != decision_json:
        return None
    if getattr(row, "id", None) is None:
        return None
    return row


def _candidate_with_evaluated_patch(evaluated: Any) -> PlanPatchCandidate:
    candidate = evaluated.candidate
    return PlanPatchCandidate(
        id=candidate.id,
        patches=(evaluated.patch,),
        rationale=candidate.rationale,
        expected_tradeoff=candidate.expected_tradeoff,
        confidence=candidate.confidence,
        assumptions=candidate.assumptions,
        risk_notes=candidate.risk_notes,
        created_from_plan_id=candidate.created_from_plan_id,
        created_from_plan_version=candidate.created_from_plan_version,
        candidate_ref=None,
    )
