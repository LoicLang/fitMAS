from __future__ import annotations

import logging
from typing import Any

from fitmas import coach_voice
from fitmas.legacy.decision_contracts import (
    AvailabilityConstraintAction,
    CoachDecision,
    ExecutionUpdateAction,
    HealthSignalAction,
    MemoryAction,
    MutationDecision,
    PreferenceSignalAction,
)

logger = logging.getLogger("fitmas.llm")

_DAYS_FR_TO_EN = {
    "lundi": "monday",
    "mardi": "tuesday",
    "mercredi": "wednesday",
    "jeudi": "thursday",
    "vendredi": "friday",
    "samedi": "saturday",
    "dimanche": "sunday",
}
_ALLOWED_MUTATION_TYPES = {
    "move_session",
    "lighten_day",
    "swap_sessions",
    "update_session",
    "replace_session",
    "create_session",
    "no_change",
}
_MUTATIONS_REQUIRING_TARGET_SESSION = {
    "move_session",
    "lighten_day",
    "update_session",
    "replace_session",
}
_NO_CHANGE_ACTION_CLAIM_PATTERNS = (
    "le plan sera ajuste",
    "calendrier sera ajuste",
    "planning sera ajuste",
    "sera reprogramme",
    "je vais ajuster",
    "je vais modifier",
    "je vais construire",
    "je construis",
    "je vais creer",
    "je vais devoir creer",
    "je dois creer",
    "je cree",
    "j ajoute",
    "j ajoute la seance",
    "je pose",
    "je place",
    "je modifie le plan",
    "je modifie le calendrier",
    "je deplace",
    "je libere",
    "je mets a jour",
    "j ai mis a jour",
    "a ete enregistre",
    "est enregistre",
    "est enregistree",
    "nouveau plan coherent",
    "nouvelle seance",
)
_TRUNCATED_MESSAGE_SUFFIXES = (
    "confirme que c est bien",
    "dis moi si",
    "a quelle intensite",
    "ou tu veux",
    "si tu veux",
)
_ALLOWED_COACH_RESPONSE_TYPES = {
    "reply",
    "no_change",
    "mutation_decision",
    "plan_patch",
    "requires_confirmation",
}

_message_violates_coach_voice = coach_voice.message_violates_coach_voice
_message_looks_receipt_style = coach_voice.message_looks_receipt_style
_message_has_user_facing_internal_jargon = coach_voice.message_has_user_facing_internal_jargon
_normalize_for_guard = coach_voice.normalize_for_voice_guard

_last_invalid_decision_payload: dict[str, Any] | None = None


def normalize_day(raw: str | None) -> str | None:
    if not raw:
        return None
    key = raw.strip().lower()
    return _DAYS_FR_TO_EN.get(key, key)


def remember_invalid_decision(data: dict[str, Any] | None) -> None:
    global _last_invalid_decision_payload
    _last_invalid_decision_payload = dict(data) if isinstance(data, dict) else None


def get_last_invalid_decision_payload() -> dict[str, Any] | None:
    return dict(_last_invalid_decision_payload) if isinstance(_last_invalid_decision_payload, dict) else None


def parse_llm_decision_payload(data: dict[str, Any] | None) -> CoachDecision | MutationDecision | None:
    if not isinstance(data, dict):
        return None
    if "response_type" in data:
        return parse_coach_decision_payload(data)

    data["from_day"] = normalize_day(data.get("from_day"))
    data["to_day"] = normalize_day(data.get("to_day"))
    validated = validate_decision_payload(data)
    if validated is None:
        return None
    return MutationDecision(**validated)


def validate_decision_payload(data: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        remember_invalid_decision(data)
        logger.warning("llm.decision_invalid reason=not_dict")
        return None
    mutation_type = str(data.get("mutation_type") or "").strip()
    if mutation_type not in _ALLOWED_MUTATION_TYPES:
        remember_invalid_decision(data)
        logger.warning("llm.decision_invalid reason=unknown_mutation_type mutation_type=%r", mutation_type)
        return None
    if _looks_like_targetless_replace_create(data, mutation_type=mutation_type):
        data["mutation_type"] = "create_session"
        mutation_type = "create_session"
    if not str(data.get("rationale") or "").strip() and mutation_type != "no_change":
        message_rationale = str(data.get("fitmas_message") or "").strip()
        if message_rationale:
            data["rationale"] = message_rationale[:180]
    if not str(data.get("rationale") or "").strip():
        remember_invalid_decision(data)
        logger.warning("llm.decision_invalid reason=missing_rationale mutation_type=%s", mutation_type)
        return None
    fitmas_message = str(data.get("fitmas_message") or "").strip()
    if not fitmas_message:
        remember_invalid_decision(data)
        logger.warning("llm.decision_invalid reason=missing_fitmas_message mutation_type=%s", mutation_type)
        return None
    if mutation_type == "no_change" and message_claims_plan_action_without_mutation(fitmas_message):
        remember_invalid_decision(data)
        logger.warning("llm.decision_invalid reason=no_change_action_claim mutation_type=%s", mutation_type)
        return None
    if mutation_type == "no_change" and message_claims_execution_receipt_without_action(
        fitmas_message,
        rationale=str(data.get("rationale") or ""),
    ):
        remember_invalid_decision(data)
        logger.warning("llm.decision_invalid reason=no_change_execution_receipt_without_action")
        return None
    if _message_violates_coach_voice(fitmas_message):
        remember_invalid_decision(data)
        logger.warning("llm.decision_invalid reason=coach_voice_violation mutation_type=%s", mutation_type)
        return None
    if _message_has_user_facing_internal_jargon(fitmas_message):
        remember_invalid_decision(data)
        logger.warning("llm.decision_invalid reason=user_facing_internal_jargon mutation_type=%s", mutation_type)
        return None
    if _message_looks_receipt_style(fitmas_message):
        logger.warning("llm.coach_voice_receipt_style mutation_type=%s message=%r", mutation_type, fitmas_message[:120])
    if looks_truncated_fitmas_message(fitmas_message):
        remember_invalid_decision(data)
        logger.warning("llm.decision_invalid reason=truncated_fitmas_message mutation_type=%s", mutation_type)
        return None
    if mutation_type in _MUTATIONS_REQUIRING_TARGET_SESSION and data.get("target_session_id") is None:
        remember_invalid_decision(data)
        logger.warning("llm.decision_invalid reason=missing_target_session mutation_type=%s", mutation_type)
        return None
    if mutation_type == "swap_sessions" and (data.get("target_session_id") is None or data.get("second_session_id") is None):
        remember_invalid_decision(data)
        logger.warning("llm.decision_invalid reason=missing_swap_sessions")
        return None
    if mutation_type == "create_session" and missing_create_session_fields(data):
        remember_invalid_decision(data)
        logger.warning("llm.decision_invalid reason=missing_create_session_fields")
        return None
    remember_invalid_decision(None)
    return data


def parse_coach_decision_payload(data: dict[str, Any] | None) -> CoachDecision | None:
    if not isinstance(data, dict):
        remember_invalid_decision(data)
        logger.warning("llm.coach_decision_invalid reason=not_dict")
        return None
    remember_invalid_decision(data)
    response_type = str(data.get("response_type") or "").strip()
    if response_type not in _ALLOWED_COACH_RESPONSE_TYPES:
        logger.warning("llm.coach_decision_invalid reason=unknown_response_type response_type=%r", response_type)
        return None
    rationale = str(data.get("rationale") or "").strip()
    if not rationale:
        logger.warning("llm.coach_decision_invalid reason=missing_rationale response_type=%s", response_type)
        return None
    fitmas_message = str(data.get("fitmas_message") or "").strip()
    raw_patch = data.get("plan_patch")
    raw_mutation = data.get("mutation_decision")
    free_requires_confirmation = (
        response_type == "requires_confirmation"
        and not isinstance(raw_patch, dict)
        and not isinstance(raw_mutation, dict)
    )
    if free_requires_confirmation:
        logger.warning("llm.coach_decision_invalid reason=free_requires_confirmation_without_action")
        return None
    if not valid_coach_message(fitmas_message, response_type=response_type):
        return None
    if has_unknown_memory_action(data.get("memory_actions")):
        logger.info("llm.coach_decision_action_dropped reason=unknown_memory_action")
    if has_unknown_execution_action(data.get("execution_actions")):
        logger.warning("llm.coach_decision_invalid reason=unknown_execution_action")
        return None

    memory_actions = normalize_memory_actions(data.get("memory_actions"))
    execution_actions = normalize_execution_actions(data.get("execution_actions"))
    if not execution_actions and message_claims_execution_receipt_without_action(fitmas_message, rationale=rationale):
        logger.warning("llm.coach_decision_invalid reason=execution_receipt_without_action")
        return None

    payload: dict[str, Any] = {
        "response_type": response_type,
        "rationale": rationale,
        "fitmas_message": fitmas_message,
        "confirmation_reason": optional_str(data.get("confirmation_reason")),
        "memory_actions": memory_actions,
        "execution_actions": execution_actions,
        "pending_resolution": normalize_pending_resolution(data.get("pending_resolution")),
    }
    if response_type == "mutation_decision":
        mutation = parse_nested_mutation_decision(
            data.get("mutation_decision"),
            fallback_rationale=rationale,
            fallback_fitmas_message=fitmas_message,
        )
        if mutation is None:
            logger.warning("llm.coach_decision_invalid reason=invalid_mutation_decision")
            return None
        payload["mutation_decision"] = mutation
    elif response_type == "plan_patch":
        patch = parse_nested_plan_patch(
            data.get("plan_patch"),
            fallback_coach_message=fitmas_message,
            fallback_confirmation_reason=payload.get("confirmation_reason"),
        )
        if patch is None:
            logger.warning("llm.coach_decision_invalid reason=invalid_plan_patch")
            return None
        payload["plan_patch"] = patch
    elif response_type == "requires_confirmation":
        if not payload["confirmation_reason"]:
            payload["confirmation_reason"] = rationale
            logger.info("llm.coach_decision_semantic_repair reason=missing_confirmation_reason")
        if isinstance(raw_patch, dict):
            patch = parse_nested_plan_patch(
                raw_patch,
                fallback_coach_message=fitmas_message,
                fallback_confirmation_reason=payload.get("confirmation_reason"),
            )
            if patch is None:
                logger.warning("llm.coach_decision_invalid reason=invalid_confirmation_plan_patch")
                return None
            payload["plan_patch"] = patch
        elif isinstance(raw_mutation, dict):
            patch_from_misplaced_mutation = parse_nested_plan_patch(
                raw_mutation,
                fallback_coach_message=fitmas_message,
                fallback_confirmation_reason=payload.get("confirmation_reason"),
            )
            if patch_from_misplaced_mutation is not None:
                payload["plan_patch"] = patch_from_misplaced_mutation
            else:
                mutation = parse_nested_mutation_decision(
                    raw_mutation,
                    fallback_rationale=rationale,
                    fallback_fitmas_message=fitmas_message,
                )
                if mutation is None:
                    logger.warning("llm.coach_decision_invalid reason=invalid_confirmation_mutation_decision")
                    return None
                payload["mutation_decision"] = mutation
    return build_coach_decision_from_payload(payload)


def parse_nested_mutation_decision(
    raw: Any,
    *,
    fallback_rationale: str | None = None,
    fallback_fitmas_message: str | None = None,
) -> MutationDecision | None:
    if not isinstance(raw, dict):
        return None
    payload = dict(raw)
    if fallback_rationale and not str(payload.get("rationale") or "").strip():
        payload["rationale"] = fallback_rationale
    if fallback_fitmas_message and not str(payload.get("fitmas_message") or "").strip():
        payload["fitmas_message"] = fallback_fitmas_message
    validated = validate_decision_payload(payload)
    if validated is None:
        return None
    try:
        return MutationDecision(**validated)
    except Exception:
        logger.warning("llm.coach_decision_invalid reason=mutation_model_validation_failed")
        return None


def parse_nested_plan_patch(
    raw: Any,
    *,
    fallback_coach_message: str | None = None,
    fallback_confirmation_reason: str | None = None,
) -> Any | None:
    from fitmas.plan_patch import PlanPatch

    if not isinstance(raw, dict):
        return None
    raw = unwrap_plan_patch_payload(raw)
    raw = normalize_plan_patch_payload(
        raw,
        fallback_coach_message=fallback_coach_message,
        fallback_confirmation_reason=fallback_confirmation_reason,
    )
    try:
        patch = PlanPatch(**raw)
    except Exception:
        logger.warning("llm.coach_decision_invalid reason=plan_patch_model_validation_failed")
        return None
    if not patch.operations:
        logger.warning("llm.coach_decision_invalid reason=empty_plan_patch")
        return None
    if not valid_coach_message(patch.coach_message, response_type="plan_patch"):
        return None
    return patch


def unwrap_plan_patch_payload(raw: dict[str, Any]) -> dict[str, Any]:
    current = raw
    for _ in range(4):
        if "operations" in current and "coach_message" in current:
            return current
        review = current.get("review")
        if isinstance(review, dict) and isinstance(review.get("revised_patch"), dict):
            return dict(review["revised_patch"])
        nested = next(
            (
                current.get(key)
                for key in ("patch", "plan_patch", "payload")
                if isinstance(current.get(key), dict)
            ),
            None,
        )
        if not isinstance(nested, dict):
            return current
        current = nested
    return current


def normalize_plan_patch_payload(
    raw: dict[str, Any],
    *,
    fallback_coach_message: str | None,
    fallback_confirmation_reason: str | None,
) -> dict[str, Any]:
    payload = dict(raw)
    operations = payload.get("operations")
    if isinstance(operations, dict):
        operations = [operations]
    if isinstance(operations, list):
        payload["operations"] = [
            normalize_plan_patch_operation(operation)
            for operation in operations
            if isinstance(operation, dict)
        ]
    if not str(payload.get("coach_message") or "").strip() and fallback_coach_message:
        payload["coach_message"] = fallback_coach_message
    if not str(payload.get("confirmation_reason") or "").strip() and fallback_confirmation_reason:
        payload["confirmation_reason"] = fallback_confirmation_reason
    return payload


def normalize_plan_patch_operation(operation: dict[str, Any]) -> dict[str, Any]:
    payload = dict(operation)
    if "operation_type" not in payload:
        alias = payload.get("operation") or payload.get("type") or payload.get("mutation_type")
        if alias:
            payload["operation_type"] = alias
    if "target_session_id" not in payload:
        alias_target = payload.get("session_id") or payload.get("target_session")
        if alias_target is not None:
            payload["target_session_id"] = alias_target
    return payload


def valid_coach_message(message: str, *, response_type: str) -> bool:
    if not message:
        logger.warning("llm.coach_decision_invalid reason=missing_fitmas_message response_type=%s", response_type)
        return False
    if response_type in {"reply", "no_change", "requires_confirmation"} and message_claims_plan_action_without_mutation(message):
        logger.warning("llm.coach_decision_invalid reason=action_claim_without_patch response_type=%s", response_type)
        return False
    if _message_violates_coach_voice(message):
        logger.warning("llm.coach_decision_invalid reason=coach_voice_violation response_type=%s", response_type)
        return False
    if _message_has_user_facing_internal_jargon(message):
        logger.warning("llm.coach_decision_invalid reason=user_facing_internal_jargon response_type=%s", response_type)
        return False
    if _message_looks_receipt_style(message):
        logger.warning("llm.coach_voice_receipt_style response_type=%s message=%r", response_type, message[:120])
    if looks_truncated_fitmas_message(message):
        logger.warning("llm.coach_decision_invalid reason=truncated_fitmas_message response_type=%s", response_type)
        return False
    return True


def optional_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_pending_resolution(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    resolution_type = str(raw.get("type") or "").strip()
    allowed_fields = {
        "accept_pending": {"type", "reason", "selected_candidate_id"},
        "reject_pending": {"type", "reason"},
        "modify_pending": {"type", "requested_changes", "reason"},
        "ignore": {"type", "reason"},
        "needs_clarification": {"type", "reason", "question"},
    }
    if resolution_type not in allowed_fields:
        logger.info("llm.coach_decision_action_dropped reason=malformed_pending_resolution")
        return None
    cleaned = {key: value for key, value in raw.items() if key in allowed_fields[resolution_type]}
    cleaned["type"] = resolution_type
    return cleaned


def build_coach_decision_from_payload(payload: dict[str, Any]) -> CoachDecision | None:
    try:
        decision = CoachDecision(**payload)
        remember_invalid_decision(None)
        return decision
    except Exception as exc:
        logger.warning("llm.coach_decision_invalid reason=coach_decision_model_validation_failed error=%s", str(exc)[:240])
        return None


def normalize_memory_actions(raw: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(raw, (list, tuple)):
        return ()
    normalized: list[dict[str, Any]] = []
    allowed_fields = {
        "record_health_signal": {"type", "health_signal", "body_area", "signal_kind", "severity", "status", "confidence", "evidence"},
        "record_availability": {
            "type",
            "window_text",
            "availability",
            "sport_type",
            "scope",
            "starts_on",
            "ends_on",
            "recurrence",
            "confidence",
            "evidence",
        },
        "record_preference": {"type", "preference", "polarity", "scope", "confidence", "evidence"},
    }
    required_fields = {
        "record_health_signal": {"health_signal"},
        "record_availability": {"window_text", "availability"},
        "record_preference": {"preference", "polarity"},
    }
    for item in raw:
        if not isinstance(item, dict):
            continue
        action_type = str(item.get("type") or item.get("action") or item.get("operation_type") or "").strip()
        if action_type not in allowed_fields:
            continue
        cleaned = {key: value for key, value in item.items() if key in allowed_fields[action_type]}
        cleaned["type"] = action_type
        if any(not str(cleaned.get(field) or "").strip() for field in required_fields[action_type]):
            logger.warning("llm.coach_decision_action_dropped action_type=%s reason=missing_required_field", action_type)
            continue
        if "confidence" in cleaned:
            cleaned["confidence"] = normalize_confidence(cleaned.get("confidence"))
        normalized.append(cleaned)
    return tuple(normalized)


def has_unknown_memory_action(raw: Any) -> bool:
    if not isinstance(raw, (list, tuple)):
        return False
    allowed = {"record_health_signal", "record_availability", "record_preference"}
    for item in raw:
        if not isinstance(item, dict):
            continue
        action_type = str(item.get("type") or item.get("action") or item.get("operation_type") or "").strip()
        if action_type and action_type not in allowed:
            return True
    return False


def normalize_execution_actions(raw: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(raw, (list, tuple)):
        return ()
    normalized: list[dict[str, Any]] = []
    allowed_fields = {
        "type",
        "target_ref",
        "target_session_id",
        "status",
        "completed",
        "sport_type",
        "duration_min",
        "confidence",
        "evidence",
    }
    for item in raw:
        if not isinstance(item, dict):
            continue
        action_type = str(item.get("type") or item.get("action") or item.get("operation_type") or "").strip()
        if action_type != "record_execution_update":
            continue
        cleaned = {key: value for key, value in item.items() if key in allowed_fields}
        cleaned["type"] = "record_execution_update"
        completed = normalize_bool(cleaned.get("completed"))
        if completed is not None:
            cleaned["completed"] = completed
        if not str(cleaned.get("target_ref") or "").strip() and cleaned.get("target_session_id") is not None:
            cleaned["target_ref"] = f"session_id:{cleaned['target_session_id']}"
        cleaned["status"] = normalize_execution_status(cleaned.get("status"), completed=completed)
        if "confidence" in cleaned:
            cleaned["confidence"] = normalize_confidence(cleaned.get("confidence"))
        if not str(cleaned.get("target_ref") or "").strip() or cleaned["status"] is None:
            logger.warning("llm.coach_decision_action_dropped action_type=record_execution_update reason=missing_target_or_status")
            continue
        normalized.append(cleaned)
    return tuple(normalized)


def has_unknown_execution_action(raw: Any) -> bool:
    if not isinstance(raw, (list, tuple)):
        return False
    for item in raw:
        if not isinstance(item, dict):
            continue
        action_type = str(item.get("type") or item.get("action") or item.get("operation_type") or "").strip()
        if action_type and action_type != "record_execution_update":
            return True
    return False


def normalize_execution_status(raw: Any, *, completed: Any = None) -> str | None:
    value = str(raw or "").strip().lower()
    if value in {"completed", "done"} or completed is True:
        return "completed"
    if value in {"not_completed", "not done", "not_done", "skipped", "missed", "cancelled", "canceled"} or completed is False:
        return "not_completed"
    if value in {"partially_completed", "partial", "partially done"}:
        return "partially_completed"
    if value == "unknown":
        return "unknown"
    return None


def message_claims_execution_receipt_without_action(message: str, *, rationale: str) -> bool:
    normalized = _normalize_for_guard(" ".join([message, rationale]))
    if not any(marker in normalized for marker in ("hier", "seance d hier", "seance dhier")):
        return False
    receipt_markers = (
        "vu pour",
        "c est note",
        "vu pour hier",
        "note pour hier",
        "bien note",
        "je note",
        "renfo manque",
        "seance manque",
        "session manque",
        "seance saute",
        "session saute",
        "non fait",
        "ne pas avoir fait",
        "pas avoir fait",
        "pas fait",
        "n est pas fait",
        "n a pas tenu",
        "annule hier",
        "manquee hier",
        "manque la seance",
        "avoir manque",
        "imprevu",
        "pas eu le temps",
        "execution manquee",
    )
    return any(marker in normalized for marker in receipt_markers)


def repair_execution_receipt_without_action_decision(
    *,
    data: dict[str, Any] | None,
    coach_context: dict | None,
) -> CoachDecision | None:
    if not isinstance(data, dict):
        return None
    fitmas_message = str(data.get("fitmas_message") or "").strip()
    rationale = str(data.get("rationale") or "").strip()
    if not fitmas_message or not rationale:
        return None
    if not message_claims_execution_receipt_without_action(fitmas_message, rationale=rationale):
        return None
    followup_session_id = optional_int((coach_context or {}).get("unresolved_execution_followup_session_id"))
    evidence_parts = [part for part in (rationale, fitmas_message) if part]
    evidence = " | ".join(evidence_parts)
    if len(evidence) > 240:
        evidence = evidence[:237].rstrip() + "..."
    repaired_payload = {
        "response_type": "no_change",
        "rationale": rationale,
        "fitmas_message": fitmas_message,
        "execution_actions": [
            {
                "type": "record_execution_update",
                "target_ref": "seance d'hier",
                "target_session_id": followup_session_id,
                "status": "not_completed",
                "completed": False,
                "confidence": 0.85,
                "evidence": evidence,
            }
        ],
        "pending_resolution": data.get("pending_resolution"),
    }
    if followup_session_id is None:
        action = repaired_payload["execution_actions"][0]
        action.pop("target_session_id", None)
        action["confidence"] = 0.8
    decision = parse_coach_decision_payload(repaired_payload)
    if decision is not None:
        logger.info(
            "llm.coach_decision_semantic_repair reason=execution_receipt_without_action target_session_id=%s",
            followup_session_id,
        )
    return decision


def normalize_bool(raw: Any) -> bool | None:
    if isinstance(raw, bool):
        return raw
    value = str(raw or "").strip().lower()
    if value in {"true", "yes", "oui", "1"}:
        return True
    if value in {"false", "no", "non", "0"}:
        return False
    return None


def normalize_confidence(raw: Any) -> float:
    if isinstance(raw, (int, float)):
        return max(0.0, min(1.0, float(raw)))
    value = str(raw or "").strip().lower()
    if value in {"high", "elevee", "elevée", "strong"}:
        return 0.85
    if value in {"medium", "moyenne", "moderate"}:
        return 0.65
    if value in {"low", "faible"}:
        return 0.4
    try:
        return max(0.0, min(1.0, float(value)))
    except ValueError:
        return 0.75


def missing_create_session_fields(data: dict[str, Any]) -> bool:
    return (
        not str(data.get("target_date") or "").strip()
        or not str(data.get("new_sport_type") or "").strip()
        or not str(data.get("new_title") or "").strip()
        or data.get("new_duration_min") is None
    )


def _looks_like_targetless_replace_create(data: dict[str, Any], *, mutation_type: str) -> bool:
    return (
        mutation_type == "replace_session"
        and data.get("target_session_id") is None
        and not missing_create_session_fields(data)
    )


def message_claims_plan_action_without_mutation(message: str) -> bool:
    normalized = _normalize_for_guard(message)
    return any(pattern in normalized for pattern in _NO_CHANGE_ACTION_CLAIM_PATTERNS)


def looks_truncated_fitmas_message(message: str) -> bool:
    normalized = _normalize_for_guard(message).rstrip(".!?;:")
    if normalized.endswith(_TRUNCATED_MESSAGE_SUFFIXES):
        return True
    if "confirme" in normalized and message.strip()[-1:] not in {".", "!", "?"}:
        return True
    if message.strip()[-1:] not in {".", "!", "?"} and len(message.strip()) >= 40:
        return True
    return False


def downgrade_free_confirmation_payload(data: dict | None) -> dict | None:
    if not isinstance(data, dict):
        return data
    if str(data.get("response_type") or "").strip() != "requires_confirmation":
        return data
    if isinstance(data.get("plan_patch"), dict) or isinstance(data.get("mutation_decision"), dict):
        return data
    repaired = dict(data)
    repaired["response_type"] = "no_change"
    repaired["confirmation_reason"] = None
    repaired["fitmas_message"] = "Signal pris. Je reste prudent et je ne touche pas au plan sans adaptation valide."
    return repaired
