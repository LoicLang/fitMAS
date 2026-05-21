from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from fitmas.domain.planning.mutation_decision import MutationDecision
from fitmas.plan_patch import PlanPatch
from fitmas.plan_patch_candidates import PlanPatchCandidate

_YES_TEXTS = {
    "oui",
    "oui.",
    "oui!",
    "vas y",
    "vas-y",
    "go",
    "je confirme",
    "confirme",
}
_NO_TEXTS = {
    "non",
    "non.",
    "non!",
    "annule",
    "stop",
    "laisse",
    "laisse comme ca",
    "laisse comme ca.",
}
_DAY_INDEX = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


@dataclass(frozen=True)
class MutationImpactAssessment:
    level: str
    requires_confirmation: bool
    reason: str
    summary: str


def assess_mutation_impact(
    decision: MutationDecision,
    *,
    target_session=None,
    second_session=None,
) -> MutationImpactAssessment:
    summary = summarize_mutation(decision, target_session=target_session, second_session=second_session)

    if decision.mutation_type == "swap_sessions":
        return MutationImpactAssessment(
            level="high",
            requires_confirmation=True,
            reason="swap_sessions_reorganizes_week",
            summary=summary,
        )

    if decision.mutation_type == "move_session":
        span_days = _move_span_days(decision, target_session=target_session)
        if span_days >= 3:
            return MutationImpactAssessment(
                level="high",
                requires_confirmation=True,
                reason="move_session_far_shift",
                summary=summary,
            )
        return MutationImpactAssessment(
            level="low",
            requires_confirmation=False,
            reason="move_session_local_shift",
            summary=summary,
        )

    if decision.mutation_type == "replace_session":
        current_sport = str(getattr(target_session, "sport_type", "") or "").strip().lower()
        next_sport = str(decision.new_sport_type or "").strip().lower()
        session_priority = str(getattr(target_session, "priority", "") or "").strip().lower()
        session_title = str(getattr(target_session, "session_title", "") or "").strip().lower()
        is_key_session = any(token in f"{session_priority} {session_title}" for token in ("cle", "qualite", "bloc", "long"))
        if next_sport and next_sport != current_sport and is_key_session:
            return MutationImpactAssessment(
                level="high",
                requires_confirmation=True,
                reason="replace_key_session_changes_sport",
                summary=summary,
            )
        return MutationImpactAssessment(
            level="low",
            requires_confirmation=False,
            reason="replace_session_same_sport",
            summary=summary,
        )

    if decision.mutation_type == "create_session":
        duration = int(decision.new_duration_min or 0)
        intensity = str(decision.new_intensity or "").strip().lower()
        if duration > 60 or intensity == "hard":
            return MutationImpactAssessment(
                level="high",
                requires_confirmation=True,
                reason="create_session_high_load",
                summary=summary,
            )
        return MutationImpactAssessment(
            level="low",
            requires_confirmation=False,
            reason="create_session_low_load",
            summary=summary,
        )

    return MutationImpactAssessment(
        level="low",
        requires_confirmation=False,
        reason="default_low_impact",
        summary=summary,
    )


def parse_confirmation_reply(text: str) -> bool | None:
    normalized = _normalize_text(text)
    if normalized in _YES_TEXTS:
        return True
    if normalized in _NO_TEXTS:
        return False
    return None


def build_confirmation_prompt(
    decision: MutationDecision,
    *,
    assessment: MutationImpactAssessment,
) -> str:
    return (
        f"Je peux le faire, mais ca change vraiment la semaine: {assessment.summary}. "
        "Tu confirmes ?"
    )


def build_confirmation_followup() -> str:
    return "J'ai une proposition en attente. Tu confirmes ou tu veux la modifier ?"


def build_rejection_reply() -> str:
    return "Compris. Je garde la semaine comme elle est."


def default_confirmation_expiry(*, now: datetime | None = None) -> datetime:
    base = now or datetime.now(UTC).replace(tzinfo=None)
    return base + timedelta(hours=24)


def serialize_mutation_decision(decision: MutationDecision) -> str:
    return json.dumps(decision.model_dump(mode="json"), ensure_ascii=True, sort_keys=True)


def deserialize_mutation_decision(raw_value: str) -> MutationDecision:
    return MutationDecision(**json.loads(raw_value))


def serialize_plan_patch_confirmation(patch: PlanPatch) -> str:
    return json.dumps(
        {
            "kind": "plan_patch",
            "plan_patch": patch.model_dump(mode="json"),
        },
        ensure_ascii=True,
        sort_keys=True,
    )


def deserialize_plan_patch_confirmation(raw_value: str) -> PlanPatch:
    payload = json.loads(raw_value)
    if isinstance(payload, dict) and payload.get("kind") == "plan_patch":
        return PlanPatch(**payload.get("plan_patch", {}))
    return PlanPatch(**payload)


def serialize_plan_patch_choice_confirmation(candidates: Sequence[PlanPatchCandidate]) -> str:
    return json.dumps(
        {
            "kind": "plan_patch_choice",
            "candidates": [_plan_patch_candidate_payload(candidate) for candidate in candidates],
        },
        ensure_ascii=True,
        sort_keys=True,
    )


def deserialize_plan_patch_choice_confirmation(raw_value: str) -> tuple[PlanPatchCandidate, ...]:
    payload = json.loads(raw_value)
    if not isinstance(payload, dict) or payload.get("kind") != "plan_patch_choice":
        return ()
    raw_candidates = payload.get("candidates")
    if not isinstance(raw_candidates, list):
        return ()
    candidates: list[PlanPatchCandidate] = []
    for raw_candidate in raw_candidates:
        if not isinstance(raw_candidate, dict):
            continue
        patches = raw_candidate.get("patches")
        if not isinstance(patches, list):
            continue
        candidates.append(
            PlanPatchCandidate(
                id=str(raw_candidate.get("id") or "").strip(),
                patches=tuple(
                    PlanPatch(**patch)
                    for patch in patches
                    if isinstance(patch, dict)
                ),
                rationale=str(raw_candidate.get("rationale") or "").strip(),
                expected_tradeoff=str(raw_candidate.get("expected_tradeoff") or "").strip(),
                confidence=float(raw_candidate.get("confidence") or 0.0),
                assumptions=tuple(
                    str(item).strip()
                    for item in raw_candidate.get("assumptions", ())
                    if str(item).strip()
                ),
                risk_notes=tuple(
                    str(item).strip()
                    for item in raw_candidate.get("risk_notes", ())
                    if str(item).strip()
                ),
                created_from_plan_id=str(raw_candidate.get("created_from_plan_id") or "").strip(),
                created_from_plan_version=int(raw_candidate.get("created_from_plan_version") or 0),
            )
        )
    return tuple(candidate for candidate in candidates if candidate.id and candidate.patches)


def _plan_patch_candidate_payload(candidate: PlanPatchCandidate) -> dict:
    return {
        "id": candidate.id,
        "patches": [patch.model_dump(mode="json") for patch in candidate.patches],
        "rationale": candidate.rationale,
        "expected_tradeoff": candidate.expected_tradeoff,
        "confidence": candidate.confidence,
        "assumptions": list(candidate.assumptions),
        "risk_notes": list(candidate.risk_notes),
        "created_from_plan_id": candidate.created_from_plan_id,
        "created_from_plan_version": candidate.created_from_plan_version,
    }


def summarize_mutation(
    decision: MutationDecision,
    *,
    target_session=None,
    second_session=None,
) -> str:
    if decision.mutation_type == "move_session":
        title = _session_title(target_session, fallback="la seance")
        source_date = _session_date(target_session)
        target_date = _decision_target_date(decision)
        if source_date and target_date:
            return f"deplacer {title} du {source_date} au {target_date}"
        if target_date:
            return f"deplacer {title} au {target_date}"
        return f"deplacer {title}"

    if decision.mutation_type == "swap_sessions":
        first_title = _session_title(target_session, fallback="la premiere seance")
        second_title = _session_title(second_session, fallback="la seconde seance")
        return f"echanger {first_title} et {second_title}"

    if decision.mutation_type == "replace_session":
        title = _session_title(target_session, fallback="la seance")
        if decision.new_sport_type:
            return f"remplacer {title} par une seance {decision.new_sport_type}"
        return f"remplacer {title}"

    if decision.mutation_type == "lighten_day":
        return f"alleger {_session_title(target_session, fallback='la journee')}"

    if decision.mutation_type == "create_session":
        sport = str(decision.new_sport_type or "sport").strip()
        target_date = _decision_target_date(decision)
        if target_date:
            return f"ajouter une seance {sport} le {target_date}"
        return f"ajouter une seance {sport}"

    return decision.fitmas_message or decision.rationale or "modifier le plan"


def _normalize_text(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    return " ".join(folded.lower().strip().split())


def _session_title(session, *, fallback: str) -> str:
    title = str(getattr(session, "session_title", "") or "").strip()
    return title.lower() if title else fallback


def _session_date(session) -> str | None:
    value = getattr(session, "scheduled_date", None)
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        return value[:10]
    return None


def _decision_target_date(decision: MutationDecision) -> str | None:
    if decision.target_date:
        return decision.target_date[:10]
    if decision.to_day and decision.to_day in _DAY_INDEX:
        return decision.to_day
    return None


def _move_span_days(decision: MutationDecision, *, target_session=None) -> int:
    source_date = getattr(target_session, "scheduled_date", None)
    if isinstance(source_date, datetime) and decision.target_date:
        try:
            target_date = date.fromisoformat(decision.target_date[:10])
        except ValueError:
            return 0
        return abs((target_date - source_date.date()).days)
    if decision.from_day in _DAY_INDEX and decision.to_day in _DAY_INDEX:
        delta = abs(_DAY_INDEX[decision.to_day] - _DAY_INDEX[decision.from_day])
        return min(delta, 7 - delta)
    return 0
