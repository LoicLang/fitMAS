from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Literal

from pydantic import BaseModel, Field

from fitmas.plan_patch import PlanPatch, PlanPatchOperation
from fitmas.planning_snapshot import PlanningSnapshot, PlanningSnapshotItem

AdaptationProposalResponseType = Literal["adaptation_proposal", "needs_clarification"]
AdaptationProposalOperationType = Literal["move", "swap", "keep", "replace", "lighten"]


class AdaptationProposalOperation(BaseModel):
    op: AdaptationProposalOperationType
    source_ref: str
    second_ref: str | None = None
    target_date: str | None = None
    target_slot: str | None = None
    reason: str


class AdaptationProposal(BaseModel):
    response_type: AdaptationProposalResponseType
    summary: str
    operations: list[AdaptationProposalOperation] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    clarification_question: str | None = None
    requires_confirmation: bool = True
    confidence: float = 0.0


@dataclass(frozen=True, slots=True)
class AdaptationProposalCompileResult:
    ok: bool
    patch: PlanPatch | None
    errors: tuple[str, ...] = ()


ADAPTATION_PROPOSAL_SCHEMA_HINT = """
AdaptationProposal JSON object:
{
  "response_type": "adaptation_proposal | needs_clarification",
  "summary": "short planning summary when response_type=adaptation_proposal",
  "operations": [
    {
      "op": "move | swap | keep | replace | lighten",
      "source_ref": "session:<id>",
      "second_ref": "session:<id> only for swap",
      "target_date": "YYYY-MM-DD only when useful",
      "target_slot": "optional",
      "reason": "short sport reason"
    }
  ],
  "assumptions": [],
  "clarification_question": null,
  "requires_confirmation": true,
  "confidence": 0.0
}
""".strip()


def compile_adaptation_proposal(
    proposal: AdaptationProposal,
    *,
    snapshot: PlanningSnapshot,
) -> AdaptationProposalCompileResult:
    if proposal.response_type != "adaptation_proposal":
        return AdaptationProposalCompileResult(ok=False, patch=None, errors=("NOT_ADAPTATION_PROPOSAL",))

    refs = _snapshot_refs(snapshot)
    move_operations = {
        operation.source_ref: operation
        for operation in proposal.operations
        if operation.op == "move" and operation.target_date
    }
    refs_by_date = {
        item.scheduled_date: item
        for item in refs.values()
        if item.scheduled_date and not _is_unscored_recovery_filler(item)
    }
    operations: list[PlanPatchOperation] = []
    errors: list[str] = []
    consumed_refs: set[str] = set()
    for operation in proposal.operations:
        if operation.source_ref in consumed_refs:
            continue
        item = refs.get(operation.source_ref)
        if item is None:
            errors.append(f"UNKNOWN_REF:{operation.source_ref}")
            continue
        if operation.op == "keep":
            continue
        if operation.op == "move":
            if _is_unscored_recovery_filler(item):
                continue
            if not operation.target_date:
                errors.append(f"MISSING_TARGET_DATE:{operation.source_ref}")
                continue
            occupant = refs_by_date.get(operation.target_date)
            occupant_move = move_operations.get(occupant.ref) if occupant is not None else None
            if (
                occupant is not None
                and occupant.ref != operation.source_ref
                and occupant_move is not None
                and occupant_move.target_date
                and occupant_move.target_date != item.scheduled_date
            ):
                operations.append(
                    PlanPatchOperation(
                        operation_type="swap_sessions",
                        target_session_id=item.session_id,
                        second_session_id=occupant.session_id,
                        rationale=operation.reason,
                    )
                )
                operations.append(
                    PlanPatchOperation(
                        operation_type="move_session",
                        target_session_id=occupant.session_id,
                        target_date=occupant_move.target_date,
                        rationale=occupant_move.reason,
                    )
                )
                consumed_refs.update({operation.source_ref, occupant.ref})
                continue
            if occupant is not None and occupant.ref != operation.source_ref and occupant_move is None:
                operations.append(
                    PlanPatchOperation(
                        operation_type="swap_sessions",
                        target_session_id=item.session_id,
                        second_session_id=occupant.session_id,
                        rationale=operation.reason,
                    )
                )
                consumed_refs.add(operation.source_ref)
                continue
            operations.append(
                PlanPatchOperation(
                    operation_type="move_session",
                    target_session_id=item.session_id,
                    target_date=operation.target_date,
                    rationale=operation.reason,
                )
            )
            continue
        if operation.op == "swap":
            if not operation.second_ref:
                errors.append(f"MISSING_SECOND_REF:{operation.source_ref}")
                continue
            second = refs.get(operation.second_ref)
            if second is None:
                errors.append(f"UNKNOWN_REF:{operation.second_ref}")
                continue
            operations.append(
                PlanPatchOperation(
                    operation_type="swap_sessions",
                    target_session_id=item.session_id,
                    second_session_id=second.session_id,
                    rationale=operation.reason,
                )
            )
            continue
        errors.append(f"UNSUPPORTED_OP:{operation.op}")

    if errors:
        return AdaptationProposalCompileResult(ok=False, patch=None, errors=tuple(errors))
    if not operations:
        return AdaptationProposalCompileResult(ok=False, patch=None, errors=("EMPTY_PATCH",))
    return AdaptationProposalCompileResult(
        ok=True,
        patch=PlanPatch(
            operations=operations,
            coach_message=proposal.summary,
            confirmation_reason=proposal.summary if proposal.requires_confirmation else None,
        ),
    )


def generate_adaptation_proposal(
    *,
    user_message: str,
    parsed_user_intent: dict,
    snapshot: PlanningSnapshot,
    request_json_fn,
    model: str | None = None,
) -> AdaptationProposal | None:
    try:
        request_kwargs = {
            "system": _proposal_system(),
            "prompt": _proposal_prompt(
                user_message=user_message,
                parsed_user_intent=parsed_user_intent,
                snapshot=snapshot,
            ),
            "max_tokens": 1400,
            "schema_hint": ADAPTATION_PROPOSAL_SCHEMA_HINT,
        }
        if model is not None:
            request_kwargs["model"] = model
        payload = request_json_fn(**request_kwargs)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    payload = _normalize_proposal_payload(payload)
    try:
        return AdaptationProposal(**payload)
    except Exception:
        return None


def _proposal_system() -> str:
    return (
        "Tu es PlanningSnapshot AdaptationProposal. "
        "Tu ne parles pas a l'utilisateur. "
        "Tu lis une semaine complete et tu proposes une adaptation sportive structuree. "
        "Tu ne commit rien, tu n'inventes pas d'ID, tu utilises seulement les refs `session:*` du snapshot. "
        "Si une info manque vraiment, retourne needs_clarification avec une question unique."
    )


def _proposal_prompt(
    *,
    user_message: str,
    parsed_user_intent: dict,
    snapshot: PlanningSnapshot,
) -> str:
    context = {
        "user_message": user_message,
        "parsed_user_intent": parsed_user_intent,
        "planning_snapshot": snapshot.to_dict(),
        "output_contract": {
            "response_type": "adaptation_proposal | needs_clarification",
            "operations": [
                {
                    "op": "move | swap | keep | replace | lighten",
                    "source_ref": "session:<id>",
                    "second_ref": "session:<id> optionnel pour swap",
                    "target_date": "YYYY-MM-DD optionnel pour move",
                    "reason": "raison courte",
                }
            ],
            "requires_confirmation": True,
            "confidence": "0..1",
        },
    }
    return (
        "Propose le meilleur compromis avec la semaine donnee. "
        "Preserve les repos explicites quand ils sont utiles. "
        "Ne transforme pas un rest_total en entrainement sauf raison forte. "
        "Un active_recovery ou un unscored_recovery n'est pas un repos total. "
        "Retourne uniquement un JSON valide conforme au contrat.\n\n"
        f"Contexte JSON:\n{json.dumps(context, ensure_ascii=False, default=str)}"
    )


def _normalize_proposal_payload(payload: dict) -> dict:
    normalized = dict(payload)
    if str(normalized.get("response_type") or "") == "adaptation_proposal":
        summary = str(normalized.get("summary") or "").strip()
        operations = normalized.get("operations")
        if not summary and isinstance(operations, list):
            reasons = [
                str(operation.get("reason") or "").strip()
                for operation in operations
                if isinstance(operation, dict) and str(operation.get("reason") or "").strip()
            ]
            if reasons:
                normalized["summary"] = " ; ".join(reasons[:2])
    return normalized


def _snapshot_refs(snapshot: PlanningSnapshot) -> dict[str, PlanningSnapshotItem]:
    refs: dict[str, PlanningSnapshotItem] = {}
    for day in snapshot.days:
        for item in day.items:
            refs[item.ref] = item
    return refs


def _is_unscored_recovery_filler(item: PlanningSnapshotItem) -> bool:
    return item.sport_type in {"rest", "off"} and item.load_kind == "unscored_recovery"
