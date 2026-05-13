from __future__ import annotations

from datetime import date, datetime
from typing import Any

from fitmas.grounding_contract import ReplyGroundingPacket
from fitmas.plan_patch import PlanPatch


def build_backend_candidate_refs_for_turn(
    *,
    grounding: ReplyGroundingPacket | None,
    scheduled_sessions: list[Any],
    turn_plan: Any | None = None,
) -> tuple[tuple[dict[str, Any], ...], dict[str, PlanPatch]]:
    """Build backend-owned candidates from typed turn artifacts only."""
    if grounding is None:
        return (), {}

    payloads: list[dict[str, Any]] = []
    patches: dict[str, PlanPatch] = {}
    sport_window = _availability_sport_window(turn_plan=turn_plan, grounding=grounding)
    if sport_window is not None:
        sport_type, starts_on, ends_on = sport_window
        _append_sport_unavailable_candidates(
            payloads=payloads,
            patches=patches,
            scheduled_sessions=scheduled_sessions,
            sport_type=sport_type,
            starts_on=starts_on,
            ends_on=ends_on,
        )
        return tuple(payloads[:12]), dict(list(patches.items())[:12])

    source_dates = _temporal_ref_dates(grounding, role="source")
    target_dates = _temporal_ref_dates(grounding, role="target")
    session_dates = source_dates | target_dates | _temporal_ref_dates(grounding, role="context")

    if source_dates and target_dates:
        _append_move_and_swap_candidates(
            payloads=payloads,
            patches=patches,
            scheduled_sessions=scheduled_sessions,
            source_dates=source_dates,
            target_dates=target_dates,
        )
    if session_dates:
        _append_lighten_and_replace_candidates(
            payloads=payloads,
            patches=patches,
            scheduled_sessions=scheduled_sessions,
            session_dates=session_dates,
        )
    return tuple(payloads[:12]), dict(list(patches.items())[:12])


def _append_move_and_swap_candidates(
    *,
    payloads: list[dict[str, Any]],
    patches: dict[str, PlanPatch],
    scheduled_sessions: list[Any],
    source_dates: set[date],
    target_dates: set[date],
) -> None:
    source_sessions = _sessions_on_dates(scheduled_sessions, source_dates)
    target_sessions = _sessions_on_dates(scheduled_sessions, target_dates)
    for source in source_sessions:
        source_id = _session_int(source, "id")
        source_date = _session_date(source)
        if source_id is None or source_date is None:
            continue
        for target_date in sorted(target_dates):
            if target_date == source_date:
                continue
            _append_move_candidate(
                payloads=payloads,
                patches=patches,
                session=source,
                target_date=target_date,
            )
        for target in target_sessions:
            target_id = _session_int(target, "id")
            if target_id is None or target_id == source_id:
                continue
            _append_swap_candidate(
                payloads=payloads,
                patches=patches,
                first=source,
                second=target,
            )


def _append_lighten_and_replace_candidates(
    *,
    payloads: list[dict[str, Any]],
    patches: dict[str, PlanPatch],
    scheduled_sessions: list[Any],
    session_dates: set[date],
) -> None:
    for session in _sessions_on_dates(scheduled_sessions, session_dates):
        _append_lighten_candidate(payloads=payloads, patches=patches, session=session)
        _append_recovery_replace_candidate(payloads=payloads, patches=patches, session=session)


def _append_sport_unavailable_candidates(
    *,
    payloads: list[dict[str, Any]],
    patches: dict[str, PlanPatch],
    scheduled_sessions: list[Any],
    sport_type: str,
    starts_on: date,
    ends_on: date,
) -> None:
    for session in scheduled_sessions:
        session_date = _session_date(session)
        if session_date is None or not starts_on <= session_date <= ends_on:
            continue
        if _session_is_completed(session):
            continue
        if _normalized_sport(_value(session, "sport_type")) != sport_type:
            continue
        _append_sport_unavailable_replace_candidate(
            payloads=payloads,
            patches=patches,
            session=session,
            sport_type=sport_type,
            starts_on=starts_on,
            ends_on=ends_on,
        )


def _append_sport_unavailable_replace_candidate(
    *,
    payloads: list[dict[str, Any]],
    patches: dict[str, PlanPatch],
    session: Any,
    sport_type: str,
    starts_on: date,
    ends_on: date,
) -> None:
    session_id = _session_int(session, "id")
    session_date = _session_date(session)
    if session_id is None or session_date is None:
        return
    duration = _light_duration(session)
    replacement = _replacement_for_unavailable_sport(sport_type)
    ref = f"backend:replace_unavailable_sport:{session_id}:{sport_type}"
    patches[ref] = PlanPatch(
        operations=[
            {
                "operation_type": "replace_session",
                "target_session_id": session_id,
                "new_title": replacement["title"],
                "new_goal": replacement["goal"],
                "new_sport_type": replacement["sport_type"],
                "new_session_type": replacement["session_type"],
                "new_duration_min": duration,
                "new_intensity": "easy",
                "new_description": replacement["description"],
                "rationale": "Candidate backend construite depuis une contrainte sport indisponible typee.",
            }
        ],
        coach_message="Candidate backend, pas une reponse finale.",
    )
    payloads.append(
        {
            "candidate_ref": ref,
            "summary": (
                f"Remplacer {_session_title(session)} ({sport_type}) du {session_date.isoformat()} "
                f"pendant l'indisponibilite {starts_on.isoformat()} -> {ends_on.isoformat()}."
            ),
            "operations": ["replace_session"],
            "target_session_id": session_id,
            "target_date": session_date.isoformat(),
            "constraint_sport_type": sport_type,
            "constraint_start_date": starts_on.isoformat(),
            "constraint_end_date": ends_on.isoformat(),
            "new_sport_type": replacement["sport_type"],
            "new_session_type": replacement["session_type"],
            "new_duration_min": duration,
        }
    )


def _append_move_candidate(
    *,
    payloads: list[dict[str, Any]],
    patches: dict[str, PlanPatch],
    session: Any,
    target_date: date,
) -> None:
    session_id = _session_int(session, "id")
    session_date = _session_date(session)
    if session_id is None or session_date is None:
        return
    ref = f"backend:move_session:{session_id}:{target_date.isoformat()}"
    patches[ref] = PlanPatch(
        operations=[
            {
                "operation_type": "move_session",
                "target_session_id": session_id,
                "target_date": target_date.isoformat(),
                "rationale": "Candidate backend construite depuis les dates structurees du tour.",
            }
        ],
        coach_message="Candidate backend, pas une reponse finale.",
    )
    payloads.append(
        {
            "candidate_ref": ref,
            "summary": f"Déplacer {_session_title(session)} du {session_date.isoformat()} au {target_date.isoformat()}.",
            "operations": ["move_session"],
            "target_session_id": session_id,
            "target_date": target_date.isoformat(),
        }
    )


def _append_swap_candidate(
    *,
    payloads: list[dict[str, Any]],
    patches: dict[str, PlanPatch],
    first: Any,
    second: Any,
) -> None:
    first_id = _session_int(first, "id")
    second_id = _session_int(second, "id")
    if first_id is None or second_id is None:
        return
    ref = f"backend:swap_sessions:{first_id}:{second_id}"
    patches[ref] = PlanPatch(
        operations=[
            {
                "operation_type": "swap_sessions",
                "target_session_id": first_id,
                "second_session_id": second_id,
                "rationale": "Candidate backend d'echange entre deux seances datees.",
            }
        ],
        coach_message="Candidate backend, pas une reponse finale.",
    )
    payloads.append(
        {
            "candidate_ref": ref,
            "summary": f"Échanger {_session_title(first)} et {_session_title(second)}.",
            "operations": ["swap_sessions"],
            "target_session_id": first_id,
            "second_session_id": second_id,
        }
    )


def _append_lighten_candidate(
    *,
    payloads: list[dict[str, Any]],
    patches: dict[str, PlanPatch],
    session: Any,
) -> None:
    session_id = _session_int(session, "id")
    if session_id is None:
        return
    duration = _light_duration(session)
    ref = f"backend:lighten_day:{session_id}:easy_{duration}"
    patches[ref] = PlanPatch(
        operations=[
            {
                "operation_type": "lighten_day",
                "target_session_id": session_id,
                "new_title": f"{_session_title(session)} allégée",
                "new_goal": "Garder le geste sans accumuler de fatigue.",
                "new_duration_min": duration,
                "new_intensity": "easy",
                "new_description": "Version facile et raccourcie, sans chercher la performance.",
                "rationale": "Candidate backend d'allegement de charge.",
            }
        ],
        coach_message="Candidate backend, pas une reponse finale.",
    )
    payloads.append(
        {
            "candidate_ref": ref,
            "summary": f"Alléger {_session_title(session)} en {duration} min facile.",
            "operations": ["lighten_day"],
            "target_session_id": session_id,
            "new_duration_min": duration,
            "new_intensity": "easy",
        }
    )


def _append_recovery_replace_candidate(
    *,
    payloads: list[dict[str, Any]],
    patches: dict[str, PlanPatch],
    session: Any,
) -> None:
    session_id = _session_int(session, "id")
    if session_id is None:
        return
    duration = _light_duration(session)
    ref = f"backend:replace_session:{session_id}:recovery_{duration}"
    patches[ref] = PlanPatch(
        operations=[
            {
                "operation_type": "replace_session",
                "target_session_id": session_id,
                "new_title": "Récupération active",
                "new_goal": "Préserver la continuité en retirant la contrainte sportive forte.",
                "new_sport_type": "mobility",
                "new_session_type": "recovery",
                "new_duration_min": duration,
                "new_intensity": "easy",
                "new_description": "Mobilité douce, marche facile ou retour au calme long selon sensations.",
                "rationale": "Candidate backend de remplacement par récupération active.",
            }
        ],
        coach_message="Candidate backend, pas une reponse finale.",
    )
    payloads.append(
        {
            "candidate_ref": ref,
            "summary": f"Remplacer {_session_title(session)} par récupération active {duration} min.",
            "operations": ["replace_session"],
            "target_session_id": session_id,
            "new_sport_type": "mobility",
            "new_session_type": "recovery",
            "new_duration_min": duration,
        }
    )


def _sessions_on_dates(scheduled_sessions: list[Any], dates: set[date]) -> list[Any]:
    return [
        session
        for session in scheduled_sessions
        if _session_date(session) in dates and not _session_is_completed(session)
    ]


def _availability_sport_window(
    *,
    turn_plan: Any | None,
    grounding: ReplyGroundingPacket,
) -> tuple[str, date, date] | None:
    raw = _value(turn_plan, "availability_constraint")
    if not isinstance(raw, dict):
        return None
    availability = str(raw.get("availability") or "").strip().lower()
    if availability not in {"unavailable", "limited"}:
        return None
    sport_type = _normalized_sport(raw.get("sport_type"))
    if sport_type in {None, "unknown", "general", "all", "rest", "off"}:
        return None
    starts_on = _date_value(raw.get("starts_on")) or grounding.local_date
    ends_on = _date_value(raw.get("ends_on")) or starts_on
    if starts_on is None or ends_on is None or ends_on < starts_on:
        return None
    return sport_type, starts_on, ends_on


def _temporal_ref_dates(grounding: ReplyGroundingPacket, *, role: str) -> set[date]:
    return {
        ref.resolved_date
        for ref in grounding.temporal_references.get(role, ())
        if isinstance(getattr(ref, "resolved_date", None), date)
    }


def _session_date(session: Any) -> date | None:
    raw = _value(session, "scheduled_date")
    return _date_value(raw)


def _date_value(raw: Any) -> date | None:
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    if isinstance(raw, str):
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            return None
    return None


def _replacement_for_unavailable_sport(sport_type: str) -> dict[str, str]:
    sport = _normalized_sport(sport_type) or ""
    if sport in {"running", "cycling"}:
        return {
            "sport_type": "mobility",
            "session_type": "recovery",
            "title": "Mobilite facile",
            "goal": "Garder le mouvement sans utiliser le sport indisponible.",
            "description": "Mobilite douce, gainage leger ou marche facile selon sensations.",
        }
    if sport in {"swimming", "climbing"}:
        return {
            "sport_type": "strength",
            "session_type": "support",
            "title": "Renfo support facile",
            "goal": "Remplacer la seance indisponible par du support controlé.",
            "description": "Renforcement general facile, sans chercher la fatigue.",
        }
    return {
        "sport_type": "mobility",
        "session_type": "recovery",
        "title": "Recuperation active",
        "goal": "Retirer la contrainte sportive tout en gardant un signal leger.",
        "description": "Mobilite douce ou marche facile selon sensations.",
    }


def _normalized_sport(value: Any) -> str | None:
    sport = str(value or "").strip().lower()
    return sport or None


def _session_int(session: Any, key: str) -> int | None:
    raw = _value(session, key)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _session_title(session: Any) -> str:
    return str(_value(session, "session_title") or _value(session, "title") or "Séance").strip()


def _light_duration(session: Any) -> int:
    try:
        duration = int(_value(session, "duration_min") or 30)
    except (TypeError, ValueError):
        duration = 30
    return max(15, min(duration, 30))


def _session_is_completed(session: Any) -> bool:
    status = str(_value(session, "completion_status") or "").strip().lower()
    return status in {"done", "completed"}


def _value(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)
