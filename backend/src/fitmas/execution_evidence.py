from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Sequence

from fitmas.activity_claims import ActivityClaim


@dataclass(frozen=True, slots=True)
class ExecutionEvidence:
    evidence_state: Literal["observed", "claimed", "candidate", "none"]
    plan_relation: Literal["linked", "same_sport", "offplan", "unknown"]
    display_status: Literal["confirmed_done", "claimed_done", "planned_pending", "offplan_done", "uncertain"]
    reason: str
    activity_id: int | None = None


def classify_execution_evidence(
    *,
    planned_session: Any | None,
    activities: Sequence[Any] = (),
    claims: Sequence[ActivityClaim] = (),
) -> ExecutionEvidence:
    planned_sport = str(_value(planned_session, "sport_type") or "").strip().lower()
    planned_status = str(_value(planned_session, "completion_status") or "").strip().lower()
    planned_session_id = _int(_value(planned_session, "id"))

    linked_activity = next(
        (
            activity
            for activity in activities
            if planned_session_id is not None
            and _int(_value(activity, "scheduled_session_id")) == planned_session_id
            and _activity_sport(activity) == planned_sport
        ),
        None,
    )
    same_sport_activity = next(
        (activity for activity in activities if planned_sport and _activity_sport(activity) == planned_sport),
        None,
    )
    same_sport_claim = next(
        (claim for claim in claims if planned_sport and str(claim.sport_type or "").strip().lower() == planned_sport),
        None,
    )

    if planned_session is None:
        if activities:
            first = activities[0]
            return ExecutionEvidence(
                evidence_state="observed",
                plan_relation="offplan",
                display_status="offplan_done",
                reason="Activite reelle detectee sans seance planifiee explicite.",
                activity_id=_int(_value(first, "id")),
            )
        if claims:
            return ExecutionEvidence(
                evidence_state="claimed",
                plan_relation="offplan",
                display_status="claimed_done",
                reason="Activite declaree par l'utilisateur sans seance planifiee explicite.",
            )
        return ExecutionEvidence(
            evidence_state="none",
            plan_relation="unknown",
            display_status="planned_pending",
            reason="Aucune seance planifiee et aucune activite confirmee.",
        )

    if linked_activity is not None:
        return ExecutionEvidence(
            evidence_state="observed",
            plan_relation="linked",
            display_status="confirmed_done",
            reason="Activite reelle liee explicitement a la seance planifiee.",
            activity_id=_int(_value(linked_activity, "id")),
        )

    if same_sport_activity is not None:
        return ExecutionEvidence(
            evidence_state="candidate",
            plan_relation="same_sport",
            display_status="uncertain",
            reason="Activite du meme sport detectee, mais sans lien explicite avec la seance planifiee.",
            activity_id=_int(_value(same_sport_activity, "id")),
        )

    if same_sport_claim is not None:
        return ExecutionEvidence(
            evidence_state="claimed",
            plan_relation="same_sport",
            display_status="claimed_done",
            reason="Activite du meme sport declaree par l'utilisateur, mais non confirmee par une activite persistée.",
        )

    if activities:
        first = activities[0]
        return ExecutionEvidence(
            evidence_state="observed",
            plan_relation="offplan",
            display_status="offplan_done",
            reason="Activite reelle detectee, mais sur un autre sport que la seance planifiee.",
            activity_id=_int(_value(first, "id")),
        )

    if claims:
        return ExecutionEvidence(
            evidence_state="claimed",
            plan_relation="offplan",
            display_status="claimed_done",
            reason="Activite declaree par l'utilisateur, mais sur un autre sport que la seance planifiee.",
        )

    if planned_status in {"done", "adapted"}:
        return ExecutionEvidence(
            evidence_state="none",
            plan_relation="unknown",
            display_status="uncertain",
            reason="Seance marquee faite dans le plan, mais sans activite ni claim pour la confirmer.",
        )

    return ExecutionEvidence(
        evidence_state="none",
        plan_relation="unknown",
        display_status="planned_pending",
        reason="Seance planifiee sans activite ni claim confirmes.",
    )


def _activity_sport(activity: Any) -> str:
    return str(_value(activity, "sport_type") or "").strip().lower()


def _value(obj: Any, key: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
