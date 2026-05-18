from __future__ import annotations

from typing import Any

from fitmas.domain.planning.models import PlanningCandidateSet, ResolvedPlanChange
from fitmas.plan_patch import PlanPatch, PlanPatchOperation
from fitmas.plan_patch_candidates import PlanPatchCandidate

_PLAN_ID = "plan_current"
_PLAN_VERSION = 1
_USER_SAFE_PATCH_MESSAGE = "Je te propose un ajustement prudent, a confirmer avant application."


class PlanCandidateBuilder:
    def __init__(self, context: Any):
        self._context = context

    def build(self, resolved_change: ResolvedPlanChange) -> PlanningCandidateSet:
        patch = self._patch_for_change(resolved_change)
        if patch is None:
            return PlanningCandidateSet(candidates=(), backend_candidate_patches={})
        ref = _candidate_ref(resolved_change, patch)
        candidate = PlanPatchCandidate(
            id=ref,
            patches=(),
            rationale=resolved_change.reason or "Adaptation planning demandee.",
            expected_tradeoff="Option backend construite puis evaluee avant application.",
            confidence=0.85,
            assumptions=(),
            risk_notes=resolved_change.requested_change.risk_signals,
            created_from_plan_id=_PLAN_ID,
            created_from_plan_version=_PLAN_VERSION,
            candidate_ref=ref,
        )
        return PlanningCandidateSet(candidates=(candidate,), backend_candidate_patches={ref: patch})

    def _patch_for_change(self, resolved_change: ResolvedPlanChange) -> PlanPatch | None:
        if resolved_change.kind == "move":
            return self._move_patch(resolved_change)
        if resolved_change.kind == "lighten":
            return self._lighten_patch(resolved_change)
        if resolved_change.kind == "replace":
            return self._replace_patch(resolved_change)
        if resolved_change.kind == "swap":
            return self._swap_patch(resolved_change)
        if resolved_change.kind == "create":
            return self._create_patch(resolved_change)
        return None

    def _move_patch(self, resolved_change: ResolvedPlanChange) -> PlanPatch | None:
        session_id = resolved_change.source.session_id
        target_date = resolved_change.target.date
        if session_id is None or target_date is None:
            return None
        target_session = _single_session_on_date(self._context, target_date.isoformat(), excluding_session_id=session_id)
        if target_session is not None:
            second_session_id = _value(target_session, "id")
            try:
                second_session_id = int(second_session_id)
            except (TypeError, ValueError):
                return None
            return PlanPatch(
                operations=[
                    PlanPatchOperation(
                        operation_type="swap_sessions",
                        target_session_id=session_id,
                        second_session_id=second_session_id,
                        rationale=resolved_change.reason,
                    )
                ],
                coach_message=_USER_SAFE_PATCH_MESSAGE,
            )
        return PlanPatch(
            operations=[
                PlanPatchOperation(
                    operation_type="move_session",
                    target_session_id=session_id,
                    target_date=target_date.isoformat(),
                    rationale=resolved_change.reason,
                )
            ],
            coach_message=_USER_SAFE_PATCH_MESSAGE,
        )

    def _lighten_patch(self, resolved_change: ResolvedPlanChange) -> PlanPatch | None:
        session_id = resolved_change.source.session_id
        if session_id is None:
            return None
        duration = _light_duration(_session_by_id(self._context, session_id))
        return PlanPatch(
            operations=[
                PlanPatchOperation(
                    operation_type="lighten_day",
                    target_session_id=session_id,
                    new_title="Seance allegee",
                    new_goal="Garder le geste sans accumuler de fatigue.",
                    new_duration_min=duration,
                    new_intensity="easy",
                    new_description="Version facile et raccourcie, sans chercher la performance.",
                    rationale=resolved_change.reason,
                )
            ],
            coach_message=_USER_SAFE_PATCH_MESSAGE,
        )

    def _replace_patch(self, resolved_change: ResolvedPlanChange) -> PlanPatch | None:
        session_id = resolved_change.source.session_id
        if session_id is None:
            return None
        requested = resolved_change.requested_change
        duration = requested.desired_duration_min or _light_duration(_session_by_id(self._context, session_id))
        return PlanPatch(
            operations=[
                PlanPatchOperation(
                    operation_type="replace_session",
                    target_session_id=session_id,
                    new_title="Seance remplacee",
                    new_goal="Adapter la charge sans perdre la continuite.",
                    new_sport_type=requested.desired_sport or "mobility",
                    new_session_type="recovery" if requested.desired_sport is None else "support",
                    new_duration_min=duration,
                    new_intensity=requested.desired_intensity or "easy",
                    new_description="Remplacement backend borne avant evaluation sportive.",
                    rationale=resolved_change.reason,
                )
            ],
            coach_message=_USER_SAFE_PATCH_MESSAGE,
        )

    def _swap_patch(self, resolved_change: ResolvedPlanChange) -> PlanPatch | None:
        source_id = resolved_change.source.session_id
        target_id = resolved_change.target.session_id
        if source_id is None or target_id is None:
            return None
        return PlanPatch(
            operations=[
                PlanPatchOperation(
                    operation_type="swap_sessions",
                    target_session_id=source_id,
                    second_session_id=target_id,
                    rationale=resolved_change.reason,
                )
            ],
            coach_message=_USER_SAFE_PATCH_MESSAGE,
        )

    def _create_patch(self, resolved_change: ResolvedPlanChange) -> PlanPatch | None:
        target_date = resolved_change.target.date
        requested = resolved_change.requested_change
        if target_date is None or requested.desired_sport is None:
            return None
        return PlanPatch(
            operations=[
                PlanPatchOperation(
                    operation_type="create_session",
                    target_date=target_date.isoformat(),
                    new_title="Seance ajoutee",
                    new_goal="Ajouter une seance bornee depuis une intention structuree.",
                    new_sport_type=requested.desired_sport,
                    new_session_type="easy",
                    new_duration_min=requested.desired_duration_min or 30,
                    new_intensity=requested.desired_intensity or "easy",
                    new_description="Seance creee depuis RequestedPlanChange, avant validation.",
                    rationale=resolved_change.reason,
                )
            ],
            coach_message=_USER_SAFE_PATCH_MESSAGE,
        )


def _candidate_ref(resolved_change: ResolvedPlanChange, patch: PlanPatch) -> str:
    operation = patch.operations[0]
    if operation.operation_type == "move_session":
        return f"backend:move_session:{operation.target_session_id}:{operation.target_date}"
    if operation.operation_type == "swap_sessions":
        return f"backend:swap_sessions:{operation.target_session_id}:{operation.second_session_id}"
    if operation.operation_type == "lighten_day":
        return f"backend:lighten_day:{operation.target_session_id}:easy_{operation.new_duration_min}"
    if operation.operation_type == "replace_session":
        return f"backend:replace_session:{operation.target_session_id}:{operation.new_sport_type}_{operation.new_duration_min}"
    if operation.operation_type == "create_session":
        return f"backend:create_session:{operation.target_date}:{operation.new_sport_type}_{operation.new_duration_min}"
    return f"backend:{resolved_change.kind}:unknown"


def _session_by_id(context: Any, session_id: int) -> Any | None:
    sessions = tuple(getattr(getattr(context, "plan", None), "scheduled_sessions", ()) or ())
    return next((session for session in sessions if _value(session, "id") == session_id), None)


def _single_session_on_date(context: Any, target_date: str, *, excluding_session_id: int) -> Any | None:
    sessions = tuple(getattr(getattr(context, "plan", None), "scheduled_sessions", ()) or ())
    matches = tuple(
        session
        for session in sessions
        if str(_value(session, "scheduled_date") or "")[:10] == target_date
        and _value(session, "id") != excluding_session_id
    )
    return matches[0] if len(matches) == 1 else None


def _light_duration(session: Any | None) -> int:
    raw = _value(session, "duration_min") if session is not None else None
    try:
        duration = int(raw or 30)
    except (TypeError, ValueError):
        duration = 30
    return max(15, min(duration, 30))


def _value(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)
