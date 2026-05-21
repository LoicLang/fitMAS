from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import import_module
from typing import Any, Callable, Literal

from sqlalchemy.orm import Session

from fitmas import repository as repo
from fitmas import schema as s
from fitmas.conversation_contract import ConversationTurnOutcome
from fitmas.decision import CoachUnderstanding, DecisionReplyComposer
from fitmas.decision import pending_reply
from fitmas.decision.planning_outcomes import (
    legacy_decision_contract_disabled_outcome,
    plan_patch_service_result_to_outcome,
)
from fitmas.models import Extraction
from fitmas.mutation_permissions import (
    deserialize_plan_patch_choice_confirmation,
    deserialize_plan_patch_confirmation,
)
from fitmas.plan_patch_candidates import PlanPatchCandidate


logger = logging.getLogger(__name__)

PendingResolutionSource = Literal["coach_decision", "coach_understanding"]
PendingRecheckFn = Callable[..., str]


@dataclass(frozen=True, slots=True)
class PendingResolutionArtifact:
    type: str
    reason: str | None = None
    selected_candidate_id: str | None = None
    requested_changes: str | None = None
    question: str | None = None
    source: PendingResolutionSource = "coach_decision"


def pending_from_understanding_enabled() -> bool:
    return _env_flag_enabled("FITMAS_PENDING_FROM_UNDERSTANDING", default=True)


def should_prepare_canonical_pending_understanding(*, pending_confirmation) -> bool:
    return pending_from_understanding_enabled() and _has_active_pending_confirmation(pending_confirmation)


def _env_flag_enabled(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _has_active_pending_confirmation(pending_confirmation) -> bool:
    return pending_confirmation is not None and str(getattr(pending_confirmation, "status", "") or "") == "pending"


def pending_resolution_from_sources(
    *,
    decision_artifact: Any,
    canonical_understanding: CoachUnderstanding | None,
) -> PendingResolutionArtifact | None:
    if pending_from_understanding_enabled() and isinstance(canonical_understanding, CoachUnderstanding):
        artifact = _artifact_from_resolution(
            canonical_understanding.pending_resolution,
            source="coach_understanding",
        )
        if artifact is not None:
            return artifact
    return _artifact_from_resolution(getattr(decision_artifact, "pending_resolution", None), source="coach_decision")


def apply_pending_resolution(
    *,
    db: Session,
    user: s.User,
    decision_artifact: Any,
    canonical_understanding: CoachUnderstanding | None,
    pending_confirmation,
    user_text: str | None = None,
    turn_plan=None,
    verify_pending_accept_resolution_fn: PendingRecheckFn | None = None,
    decision_reply_composer: Any | None = None,
) -> ConversationTurnOutcome | None:
    resolution = pending_resolution_from_sources(
        decision_artifact=decision_artifact,
        canonical_understanding=canonical_understanding,
    )
    if resolution is None or pending_confirmation is None:
        return None

    unavailable_outcome = pending_confirmation_unavailable_outcome(
        db=db,
        pending_confirmation=pending_confirmation,
        user_text=user_text,
        decision_reply_composer=decision_reply_composer,
    )
    if unavailable_outcome is not None:
        return unavailable_outcome

    resolution_type = str(resolution.type or "")
    if (
        resolution_type in {"ignore", "modify_pending", "needs_clarification"}
        and str(getattr(decision_artifact, "response_type", "") or "") in {"plan_patch", "requires_confirmation"}
        and getattr(decision_artifact, "plan_patch", None) is not None
    ):
        return None
    if resolution_type in {"ignore", "modify_pending", "needs_clarification"} and turn_plan_requests_plan_adaptation(
        turn_plan
    ):
        return None

    recheck_fn = verify_pending_accept_resolution_fn or verify_pending_accept_resolution
    if resolution_type == "accept_pending":
        verified_resolution_type = recheck_fn(
            user_text=user_text,
            pending_resolution=resolution,
            pending_confirmation=pending_confirmation,
        )
        if verified_resolution_type != "accept_pending":
            if turn_plan_requests_plan_adaptation(turn_plan):
                return None
            return pending_accept_recheck_blocked_outcome(
                db=db,
                pending_confirmation=pending_confirmation,
                verified_resolution_type=verified_resolution_type,
                pending_resolution=resolution,
                user_text=user_text,
                decision_reply_composer=decision_reply_composer,
            )
        return accept_pending_confirmation(
            db=db,
            user=user,
            decision_artifact=decision_artifact,
            pending_resolution=resolution,
            pending_confirmation=pending_confirmation,
            user_text=user_text,
            decision_reply_composer=decision_reply_composer,
        )

    if resolution_type == "reject_pending":
        verified_resolution_type = recheck_fn(
            user_text=user_text,
            pending_resolution=resolution,
            pending_confirmation=pending_confirmation,
        )
        if verified_resolution_type != "reject_pending":
            if turn_plan_requests_plan_adaptation(turn_plan):
                return None
            return pending_accept_recheck_blocked_outcome(
                db=db,
                pending_confirmation=pending_confirmation,
                verified_resolution_type=verified_resolution_type,
                pending_resolution=resolution,
                user_text=user_text,
                decision_reply_composer=decision_reply_composer,
            )
        repo.resolve_pending_mutation_confirmation(db, pending_confirmation.id, status="rejected")
        return ConversationTurnOutcome(
            extraction=Extraction(confidence=0.85),
            reply_text=_pending_reply(
                mode="rejected",
                pending_confirmation=pending_confirmation,
                pending_resolution=resolution,
                user_text=user_text,
                decision_reply_composer=decision_reply_composer,
            ),
            response_mode="pending_rejected",
            mutation_applied=False,
        )

    if resolution_type in {"modify_pending", "needs_clarification"}:
        mode = "modify_pending" if resolution_type == "modify_pending" else "needs_clarification"
        return ConversationTurnOutcome(
            extraction=Extraction(confidence=0.85),
            reply_text=_pending_reply(
                mode=mode,
                pending_confirmation=pending_confirmation,
                pending_resolution=resolution,
                user_text=user_text,
                decision_reply_composer=decision_reply_composer,
            ),
            response_mode=f"pending_{resolution_type}",
            mutation_applied=False,
            pending_confirmation=True,
            pending_confirmation_id=getattr(pending_confirmation, "id", None),
        )

    if resolution_type == "ignore":
        return ConversationTurnOutcome(
            extraction=Extraction(confidence=0.85),
            reply_text=_pending_reply(
                mode="kept",
                pending_confirmation=pending_confirmation,
                pending_resolution=resolution,
                user_text=user_text,
                decision_reply_composer=decision_reply_composer,
            ),
            response_mode="pending_ignore",
            mutation_applied=False,
            pending_confirmation=True,
            pending_confirmation_id=getattr(pending_confirmation, "id", None),
        )

    return None


_PENDING_ACCEPT_RECHECK_TYPES = frozenset(
    {
        "accept_pending",
        "reject_pending",
        "modify_pending",
        "ignore",
        "needs_clarification",
    }
)


def verify_pending_accept_resolution(
    *,
    user_text: str | None,
    pending_resolution: Any,
    pending_confirmation,
    request_json_fn=None,
) -> str:
    """Recheck a high-impact pending accept with a narrow JSON-only contract."""
    if user_text is None:
        return "accept_pending"
    system = (
        "Tu es un validateur de pending planning FitMAS.\n"
        "Ta seule mission: verifier si le dernier message utilisateur accepte, refuse, "
        "modifie ou ignore vraiment la proposition planning en attente.\n"
        "Retourne uniquement un JSON valide.\n"
        "N'applique jamais la proposition toi-meme.\n"
        "Classes possibles:\n"
        "- accept_pending: le user valide clairement l'application du pending actif, "
        "ou choisit clairement une option candidate.\n"
        "- reject_pending: le user refuse clairement la proposition active.\n"
        "- modify_pending: le user change la demande ou propose une variante.\n"
        "- needs_clarification: le message est ambigu et demande une clarification.\n"
        "- ignore: le user demande un statut, dit qu'il attend, parle d'autre chose, "
        "ou donne une nouvelle information sans accepter explicitement.\n"
        "N'utilise pas accept_pending pour une demande de refaire, readapter, revoir, expliquer, attendre, "
        "ou pour une question. Ces cas sont modify_pending, needs_clarification ou ignore.\n"
        "N'utilise pas accept_pending juste parce que la nouvelle information rend la proposition possible "
        "ou compatible. `demain je suis dispo`, `je peux jeudi`, `finalement ce creneau marche` "
        "sont des informations de disponibilite, pas des validations, sauf si le user dit aussi clairement "
        "`je confirme`, `vas-y`, `fais ca`, `applique`.\n"
        "Un message qui commence par `non` et corrige un fait est generalement modify_pending ou ignore, "
        "pas accept_pending.\n"
        "Une objection ou question qui defend une option (`pourquoi pas vendredi ?`, "
        "`ou est le souci ?`, `si on le met vendredi ?`) n'est PAS une acceptation: "
        "retourne needs_clarification ou modify_pending.\n"
        "Accept_pending exige une validation imperative et non interrogative du pending actif.\n"
        "Une validation conditionnelle sur ton jugement de coach (`oui je confirme si tu penses que c'est propre`, "
        "`vas-y si c'est coherent`) reste une acceptation: le backend revalide ensuite la securite sportive.\n"
        "Exemples: `oui je confirme` -> accept_pending; `ok fais ca` -> accept_pending; "
        "`ok readapte la semaine` -> modify_pending; `j'attends` -> ignore; "
        "`donc je force ?` -> needs_clarification; "
        "`non j'etais indispo aujourd'hui mais demain je suis dispo` -> modify_pending; "
        "`demain je suis dispo` -> ignore; "
        "`si tu le mets vendredi il y a un jour de repos, ou est le souci ?` -> needs_clarification.\n"
        "Sois conservateur: en doute, retourne ignore ou needs_clarification, jamais accept_pending."
    )
    prompt = json.dumps(
        {
            "user_text": user_text,
            "pending_confirmation": pending_confirmation_recheck_payload(pending_confirmation),
            "main_model_resolution": pending_resolution_payload(pending_resolution),
            "expected_json": {
                "resolution_type": "accept_pending|reject_pending|modify_pending|ignore|needs_clarification",
                "confidence": 0.0,
                "reason": "court",
            },
        },
        ensure_ascii=False,
        default=str,
    )
    request_json_fn = request_json_fn or _default_request_json_fn()
    try:
        data = request_json_fn(
            system=system,
            prompt=prompt,
            model=_default_strong_model(),
            max_tokens=700,
            schema_hint=(
                "JSON object only: resolution_type string enum "
                "accept_pending|reject_pending|modify_pending|ignore|needs_clarification, "
                "confidence number, reason string."
            ),
        )
    except Exception:
        logger.exception(
            "pending_accept_recheck_failed user_text_len=%s pending=%s",
            len(user_text or ""),
            getattr(pending_confirmation, "id", None),
        )
        return "ignore"
    resolution_type = str(
        (data or {}).get("resolution_type")
        or (data or {}).get("type")
        or (data or {}).get("pending_resolution")
        or ""
    ).strip()
    if resolution_type in _PENDING_ACCEPT_RECHECK_TYPES:
        logger.info(
            "pending_accept_recheck result=%s confidence=%s pending=%s",
            resolution_type,
            (data or {}).get("confidence"),
            getattr(pending_confirmation, "id", None),
        )
        return resolution_type
    logger.warning(
        "pending_accept_recheck_invalid result=%s pending=%s",
        resolution_type,
        getattr(pending_confirmation, "id", None),
    )
    return "ignore"


def accept_pending_confirmation(
    *,
    db: Session,
    user: s.User,
    decision_artifact: Any,
    pending_confirmation,
    pending_resolution: PendingResolutionArtifact | Any | None = None,
    user_text: str | None = None,
    decision_reply_composer: Any | None = None,
) -> ConversationTurnOutcome:
    try:
        unavailable_outcome = pending_confirmation_unavailable_outcome(
            db=db,
            pending_confirmation=pending_confirmation,
            user_text=user_text,
            decision_reply_composer=decision_reply_composer,
        )
        if unavailable_outcome is not None:
            return unavailable_outcome

        if str(getattr(pending_confirmation, "mutation_type", "") or "") == "plan_patch_choice":
            return accept_pending_plan_patch_choice(
                db=db,
                user=user,
                decision_artifact=decision_artifact,
                pending_resolution=pending_resolution,
                pending_confirmation=pending_confirmation,
                user_text=user_text,
                decision_reply_composer=decision_reply_composer,
            )

        if str(getattr(pending_confirmation, "mutation_type", "") or "") == "plan_patch":
            patch = deserialize_plan_patch_confirmation(pending_confirmation.decision_json)
            service_result = _apply_patch_for_user()(
                db,
                user=user,
                patch=patch,
                source="conversation",
                trigger_type="pending_confirmation",
                explained_to_user=True,
                allow_requires_confirmation=True,
            )
            applied = patch_was_applied(service_result)
            if applied:
                repo.resolve_pending_mutation_confirmation(db, pending_confirmation.id, status="accepted")
                return ConversationTurnOutcome(
                    extraction=Extraction(confidence=0.85),
                    reply_text=applied_plan_patch_reply(service_result, fallback=patch.coach_message),
                    response_mode="pending_accepted",
                    mutation_applied=True,
                )
            return ConversationTurnOutcome(
                extraction=Extraction(confidence=0.85),
                reply_text=blocked_plan_patch_reply(service_result),
                response_mode="pending_accept_blocked",
                mutation_applied=False,
            )

        repo.resolve_pending_mutation_confirmation(db, pending_confirmation.id, status="blocked")
        outcome = legacy_decision_contract_disabled_outcome(
            decision_reply_composer_fn=_decision_reply_composer,
        )
        outcome.response_mode = "pending_legacy_mutation_disabled"
        return outcome
    except Exception:
        logger.exception(
            "pending_resolution_accept_failed user=%s pending=%s",
            getattr(user, "id", None),
            getattr(pending_confirmation, "id", None),
        )
        return ConversationTurnOutcome(
            extraction=Extraction(confidence=0.5),
            reply_text=_pending_reply(
                mode="accept_error",
                pending_confirmation=pending_confirmation,
                pending_resolution=pending_resolution,
                user_text=user_text,
                decision_reply_composer=decision_reply_composer,
            ),
            response_mode="pending_accept_error",
            mutation_applied=False,
        )


def accept_pending_plan_patch_choice(
    *,
    db: Session,
    user: s.User,
    decision_artifact: Any,
    pending_resolution: PendingResolutionArtifact | Any | None,
    pending_confirmation,
    user_text: str | None = None,
    decision_reply_composer: Any | None = None,
) -> ConversationTurnOutcome:
    selected_candidate_id = str(getattr(pending_resolution, "selected_candidate_id", "") or "").strip()
    if not selected_candidate_id:
        return ConversationTurnOutcome(
            extraction=Extraction(confidence=0.85),
            reply_text=_pending_reply(
                mode="choice_needs_selection",
                pending_confirmation=pending_confirmation,
                pending_resolution=pending_resolution,
                user_text=user_text,
                decision_reply_composer=decision_reply_composer,
            ),
            response_mode="pending_choice_needs_selection",
            mutation_applied=False,
            pending_confirmation=True,
            pending_confirmation_id=getattr(pending_confirmation, "id", None),
        )

    candidates = deserialize_plan_patch_choice_confirmation(pending_confirmation.decision_json)
    selected = next((candidate for candidate in candidates if candidate.id == selected_candidate_id), None)
    if selected is None:
        return ConversationTurnOutcome(
            extraction=Extraction(confidence=0.85),
            reply_text=_pending_reply(
                mode="choice_invalid_selection",
                pending_confirmation=pending_confirmation,
                pending_resolution=pending_resolution,
                user_text=user_text,
                decision_reply_composer=decision_reply_composer,
            ),
            response_mode="pending_choice_invalid_selection",
            mutation_applied=False,
            pending_confirmation=True,
            pending_confirmation_id=getattr(pending_confirmation, "id", None),
        )

    patch = patch_from_choice_candidate(selected)
    service_result = _apply_patch_for_user()(
        db,
        user=user,
        patch=patch,
        source="conversation",
        trigger_type="pending_choice_confirmation",
        explained_to_user=True,
        allow_requires_confirmation=True,
    )
    applied = patch_was_applied(service_result)
    if applied:
        repo.resolve_pending_mutation_confirmation(db, pending_confirmation.id, status="accepted")
        return ConversationTurnOutcome(
            extraction=Extraction(confidence=0.85),
            reply_text=applied_plan_patch_reply(service_result, fallback=patch.coach_message),
            response_mode="pending_choice_accepted",
            mutation_applied=True,
        )
    return ConversationTurnOutcome(
        extraction=Extraction(confidence=0.85),
        reply_text=blocked_plan_patch_reply(service_result),
        response_mode="pending_choice_accept_blocked",
        mutation_applied=False,
    )


def patch_from_choice_candidate(candidate: PlanPatchCandidate) -> Any:
    operations = []
    for patch in candidate.patches:
        operations.extend(patch.operations)
    patch_model = candidate.patches[0].__class__
    return patch_model(
        operations=operations,
        coach_message=candidate.rationale or candidate.patches[0].coach_message,
        confirmation_reason=candidate.expected_tradeoff or None,
    )


def patch_was_applied(service_result: Any | None) -> bool:
    if service_result is None or service_result.mutation_result is None:
        return False
    mutation_result = service_result.mutation_result
    return int(getattr(mutation_result, "applied_count", 0) or 0) > 0 and int(
        getattr(mutation_result, "event_count", 0) or 0
    ) > 0


def applied_plan_patch_reply(service_result: Any | None, *, fallback: str) -> str:
    outcome = plan_patch_service_result_to_outcome(service_result, mode="applied")
    reply_result = _decision_reply_composer().compose(outcome, context=None)
    if reply_result.text:
        return reply_result.text
    committed = " ".join(str(result.payload.get("summary") or "") for result in outcome.applied_commands).strip()
    return committed or fallback


def blocked_plan_patch_reply(service_result: Any | None) -> str:
    outcome = plan_patch_service_result_to_outcome(service_result, mode="blocked")
    reply_result = _decision_reply_composer().compose(outcome, context=None)
    return reply_result.text or outcome.explanation.reason_summary


def pending_accept_recheck_blocked_outcome(
    *,
    db: Session,
    pending_confirmation,
    verified_resolution_type: str,
    pending_resolution: PendingResolutionArtifact | Any | None = None,
    user_text: str | None = None,
    decision_reply_composer: Any | None = None,
) -> ConversationTurnOutcome:
    if verified_resolution_type == "reject_pending":
        repo.resolve_pending_mutation_confirmation(db, pending_confirmation.id, status="rejected")
        return ConversationTurnOutcome(
            extraction=Extraction(confidence=0.85),
            reply_text=_pending_reply(
                mode="rejected",
                pending_confirmation=pending_confirmation,
                pending_resolution=pending_resolution,
                user_text=user_text,
                decision_reply_composer=decision_reply_composer,
            ),
            response_mode="pending_rejected",
            mutation_applied=False,
        )
    response_mode = "pending_ignore"
    mode = "kept"
    if verified_resolution_type == "modify_pending":
        response_mode = "pending_modify_pending"
        mode = "modify_pending"
    elif verified_resolution_type == "needs_clarification":
        response_mode = "pending_needs_clarification"
        mode = "needs_clarification"
    return ConversationTurnOutcome(
        extraction=Extraction(confidence=0.85),
        reply_text=_pending_reply(
            mode=mode,
            pending_confirmation=pending_confirmation,
            pending_resolution=pending_resolution,
            user_text=user_text,
            decision_reply_composer=decision_reply_composer,
        ),
        response_mode=response_mode,
        mutation_applied=False,
        pending_confirmation=True,
        pending_confirmation_id=getattr(pending_confirmation, "id", None),
    )


def pending_confirmation_unavailable_outcome(
    *,
    db: Session,
    pending_confirmation,
    user_text: str | None = None,
    decision_reply_composer: Any | None = None,
) -> ConversationTurnOutcome | None:
    status = str(getattr(pending_confirmation, "status", "") or "")
    if status == "pending" and pending_confirmation_is_expired(pending_confirmation):
        repo.resolve_pending_mutation_confirmation(db, pending_confirmation.id, status="expired")
        return ConversationTurnOutcome(
            extraction=Extraction(confidence=0.85),
            reply_text=_pending_reply(
                mode="expired",
                pending_confirmation=pending_confirmation,
                user_text=user_text,
                decision_reply_composer=decision_reply_composer,
            ),
            response_mode="pending_expired",
            mutation_applied=False,
        )
    if status != "pending":
        return ConversationTurnOutcome(
            extraction=Extraction(confidence=0.85),
            reply_text=_pending_reply(
                mode="not_active",
                pending_confirmation=pending_confirmation,
                user_text=user_text,
                decision_reply_composer=decision_reply_composer,
            ),
            response_mode="pending_not_active",
            mutation_applied=False,
        )
    return None


def turn_plan_requests_plan_adaptation(turn_plan) -> bool:
    if turn_plan is None:
        return False
    if not bool(getattr(turn_plan, "has_plan_mutation", False)):
        return False
    primary_intent = str(getattr(turn_plan, "primary_intent", "") or "")
    secondary_intents = {str(item) for item in tuple(getattr(turn_plan, "secondary_intents", ()) or ())}
    return primary_intent == "plan_mutation" or "plan_mutation" in secondary_intents


def pending_confirmation_is_expired(pending_confirmation) -> bool:
    expires_at = getattr(pending_confirmation, "expires_at", None)
    if expires_at is None:
        return False
    if getattr(expires_at, "tzinfo", None) is not None:
        expires_at = expires_at.astimezone(UTC).replace(tzinfo=None)
    return expires_at <= datetime.now(UTC).replace(tzinfo=None)


def outcome_keeps_pending_confirmation(outcome: ConversationTurnOutcome, pending_confirmation) -> bool:
    if (
        outcome.response_mode
        in {
            "plan_patch_clarification",
            "planning_snapshot_clarification",
        }
        and getattr(pending_confirmation, "id", None) is not None
    ):
        return True
    return bool(
        outcome.pending_confirmation
        and outcome.pending_confirmation_id is not None
        and outcome.pending_confirmation_id == getattr(pending_confirmation, "id", None)
    )


def keep_pending_for_non_mutating_turn(
    *,
    outcome: ConversationTurnOutcome,
    turn_plan,
    pending_confirmation,
) -> None:
    if pending_confirmation is None or str(getattr(pending_confirmation, "status", "") or "") != "pending":
        return
    if outcome.pending_confirmation or outcome.mutation_applied:
        return
    if outcome.response_mode in {"llm_unavailable", "pending_rejected", "pending_accepted"}:
        return
    primary_intent = str(getattr(turn_plan, "primary_intent", "") or "")
    if primary_intent not in {"casual_chat", "close_turn", "generic_question", "needs_clarification", "trivial_ack"}:
        return
    outcome.pending_confirmation = True
    outcome.pending_confirmation_id = getattr(pending_confirmation, "id", None)


def supersede_pending_if_replaced(
    *,
    db: Session,
    outcome: ConversationTurnOutcome,
    pending_confirmation,
) -> None:
    if pending_confirmation is None:
        return
    if str(getattr(pending_confirmation, "status", "") or "") != "pending":
        return
    if outcome.response_mode == "llm_unavailable":
        return
    if outcome_keeps_pending_confirmation(outcome, pending_confirmation):
        return
    repo.resolve_pending_mutation_confirmation(db, pending_confirmation.id, status="superseded")


def pending_pre_adaptation_allows(resolution_type: str | None) -> bool:
    return str(resolution_type or "").strip() == "modify_pending"


def pending_confirmation_recheck_payload(pending_confirmation) -> dict[str, Any]:
    return {
        "id": getattr(pending_confirmation, "id", None),
        "mutation_type": str(getattr(pending_confirmation, "mutation_type", "") or ""),
        "reason": str(getattr(pending_confirmation, "reason", "") or ""),
        "summary": str(getattr(pending_confirmation, "summary", "") or ""),
        "source_text": str(getattr(pending_confirmation, "source_text", "") or ""),
        "decision_json": truncate_for_recheck(str(getattr(pending_confirmation, "decision_json", "") or "")),
    }


def pending_resolution_payload(resolution: Any) -> dict[str, Any] | None:
    if resolution is None:
        return None
    if isinstance(resolution, PendingResolutionArtifact):
        return {
            "type": resolution.type,
            "reason": resolution.reason,
            "selected_candidate_id": resolution.selected_candidate_id,
            "requested_changes": resolution.requested_changes,
            "question": resolution.question,
            "source": resolution.source,
        }
    if hasattr(resolution, "model_dump"):
        return dict(resolution.model_dump(mode="json", exclude_none=True))
    return {
        "type": getattr(resolution, "type", None),
        "reason": getattr(resolution, "reason", None),
        "selected_candidate_id": getattr(resolution, "selected_candidate_id", None),
        "requested_changes": getattr(resolution, "requested_changes", None),
        "question": getattr(resolution, "question", None),
    }


def truncate_for_recheck(value: str, *, limit: int = 6000) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "\n[truncated]"


def _artifact_from_resolution(
    resolution: Any,
    *,
    source: PendingResolutionSource,
) -> PendingResolutionArtifact | None:
    if resolution is None:
        return None
    resolution_type = str(getattr(resolution, "type", "") or "").strip()
    if not resolution_type:
        return None
    return PendingResolutionArtifact(
        type=resolution_type,
        reason=_optional_text(getattr(resolution, "reason", None)),
        selected_candidate_id=_optional_text(getattr(resolution, "selected_candidate_id", None)),
        requested_changes=_optional_text(getattr(resolution, "requested_changes", None)),
        question=_optional_text(getattr(resolution, "question", None)),
        source=source,
    )


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _pending_reply(
    *,
    mode: pending_reply.PendingReplyMode,
    pending_confirmation,
    pending_resolution: Any | None = None,
    user_text: str | None = None,
    decision_reply_composer: Any | None = None,
) -> str:
    return pending_reply.compose_pending_reply(
        mode=mode,
        pending_confirmation=pending_confirmation,
        pending_resolution=pending_resolution,
        user_text=user_text,
        decision_reply_composer=decision_reply_composer,
    )


def _decision_reply_composer() -> DecisionReplyComposer:
    backend_cls = getattr(import_module("fitmas.llm.reply_decision_backend"), "LLMReplyBackend")
    return DecisionReplyComposer(reply_backend=backend_cls())


def _apply_patch_for_user():
    return getattr(import_module("fitmas.plan_mutation_service"), "apply_patch_for_user")


def _default_request_json_fn():
    return getattr(import_module("fitmas.llm.gateway"), "request_json")


def _default_strong_model() -> str:
    return str(getattr(import_module("fitmas.llm.gateway"), "DEFAULT_STRONG_MODEL"))
