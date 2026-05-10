from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from fitmas.plan_patch import PlanPatch
from fitmas.plan_patch_candidates import (
    PlanPatchCandidate,
    validate_plan_patch_candidate_contract,
)

RequestJsonFn = Callable[..., dict[str, Any] | None]


@dataclass(frozen=True, slots=True)
class CandidateGenerationInput:
    user_message: str
    parsed_user_intent: dict[str, Any]
    current_plan_summary: dict[str, Any]
    current_plan_id: str
    current_plan_version: int
    constraints: dict[str, Any]
    week_facts: dict[str, Any] | None
    coherence_findings: tuple[dict[str, Any], ...]
    allowed_operations: tuple[str, ...]
    forbidden_operations: tuple[str, ...]
    pending_context: dict[str, Any] | None
    backend_candidates: tuple[dict[str, Any], ...] = ()


def generate_plan_patch_candidates(
    input_payload: CandidateGenerationInput,
    *,
    request_json_fn: RequestJsonFn,
) -> tuple[PlanPatchCandidate, ...]:
    try:
        payload = request_json_fn(
            system=_candidate_generator_system(),
            prompt=_candidate_generator_prompt(input_payload),
            max_tokens=1200,
        )
    except Exception:
        return ()
    if not isinstance(payload, dict):
        return ()
    raw_candidates = payload.get("candidates")
    if not isinstance(raw_candidates, list):
        return ()

    effective_allowed_operations = tuple(
        operation
        for operation in input_payload.allowed_operations
        if operation not in set(input_payload.forbidden_operations)
    )
    candidates: list[PlanPatchCandidate] = []
    for index, raw_candidate in enumerate(raw_candidates, start=1):
        candidate = _parse_candidate(
            raw_candidate,
            index=index,
            current_plan_id=input_payload.current_plan_id,
            current_plan_version=input_payload.current_plan_version,
        )
        if candidate is None:
            continue
        validation = validate_plan_patch_candidate_contract(
            candidate,
            current_plan_id=input_payload.current_plan_id,
            current_plan_version=input_payload.current_plan_version,
            allowed_operations=effective_allowed_operations,
        )
        if validation.status != "valid":
            continue
        candidates.append(candidate)
        if len(candidates) >= 3:
            break
    return tuple(candidates)


def _candidate_generator_system() -> str:
    return (
        "Tu es LLMPlanPatchCandidateGenerator. "
        "Tu ne parles jamais a l'utilisateur. "
        "Tu ne commit rien. "
        "Tu produis uniquement des PlanPatchCandidate JSON bornes. "
        "Tu n'affirmes jamais qu'un changement est fait."
    )


def _candidate_generator_prompt(input_payload: CandidateGenerationInput) -> str:
    context = {
        "user_message": input_payload.user_message,
        "parsed_user_intent": input_payload.parsed_user_intent,
        "current_plan_summary": input_payload.current_plan_summary,
        "current_plan_id": input_payload.current_plan_id,
        "current_plan_version": input_payload.current_plan_version,
        "constraints": input_payload.constraints,
        "week_facts": input_payload.week_facts,
        "coherence_findings": list(input_payload.coherence_findings),
        "allowed_operations": list(input_payload.allowed_operations),
        "forbidden_operations": list(input_payload.forbidden_operations),
        "pending_context": input_payload.pending_context,
        "backend_candidates": list(input_payload.backend_candidates),
    }
    return (
        "Genere entre 0 et 3 candidats d'adaptation. "
        "Utilise uniquement allowed_operations et jamais forbidden_operations. "
        "Si backend_candidates contient une option utile, retourne son candidate_ref sans recopier son PlanPatch. "
        "Chaque candidat doit contenir patches, rationale, expected_tradeoff, confidence, assumptions, risk_notes. "
        "Un candidat peut contenir candidate_ref a la place de patches quand il reference une option backend. "
        "Si l'intention est insuffisante ou dangereuse, retourne {\"candidates\": []}.\n\n"
        f"Contexte JSON:\n{json.dumps(context, ensure_ascii=False, default=str)}"
    )


def _parse_candidate(
    raw_candidate: Any,
    *,
    index: int,
    current_plan_id: str,
    current_plan_version: int,
) -> PlanPatchCandidate | None:
    if not isinstance(raw_candidate, dict):
        return None
    candidate_ref = str(raw_candidate.get("candidate_ref") or "").strip() or None
    raw_patches = raw_candidate.get("patches")
    if raw_patches is None and candidate_ref:
        raw_patches = []
    if not isinstance(raw_patches, list):
        return None
    patches: list[PlanPatch] = []
    for raw_patch in raw_patches:
        if not isinstance(raw_patch, dict):
            return None
        try:
            patches.append(PlanPatch.model_validate(raw_patch))
        except Exception:
            return None
    try:
        confidence = float(raw_candidate.get("confidence"))
    except (TypeError, ValueError):
        return None
    return PlanPatchCandidate(
        id=f"llm_candidate_{index}",
        patches=tuple(patches),
        rationale=str(raw_candidate.get("rationale") or "").strip(),
        expected_tradeoff=str(raw_candidate.get("expected_tradeoff") or "").strip(),
        confidence=confidence,
        assumptions=_string_tuple(raw_candidate.get("assumptions")),
        risk_notes=_string_tuple(raw_candidate.get("risk_notes")),
        created_from_plan_id=current_plan_id,
        created_from_plan_version=current_plan_version,
        candidate_ref=candidate_ref,
    )


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())
