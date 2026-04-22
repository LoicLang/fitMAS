from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Sequence

from fitmas.plan_validator import validate_week_plan
from fitmas.user_indications import parse_availability_fact_key

DAY_ORDER = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
REST_DAY = {
    "sport_type": "rest",
    "session_type": "rest",
    "session_title": "Repos",
    "duration_min": 0,
    "intensity": "easy",
    "priority": "Recovery",
    "load_score": 0,
}


@dataclass(frozen=True, slots=True)
class ConstraintWindow:
    start_date: date
    end_date: date
    sport_type: str | None


def build_replan_proposal(
    *,
    scheduled_sessions: Sequence[Any],
    active_facts: Sequence[dict[str, Any]],
    timezone_name: str | None,
    now: datetime | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    sport_type: str | None = None,
    preferred_replacement_sport: str | None = None,
) -> dict[str, Any] | None:
    local_today = _local_today(timezone_name, now=now)
    constraint = _resolve_constraint_window(
        active_facts=active_facts,
        local_today=local_today,
        start_date=start_date,
        end_date=end_date,
        sport_type=sport_type,
    )
    if constraint is None:
        return None

    impacted_sessions = _find_impacted_sessions(
        scheduled_sessions=scheduled_sessions,
        constraint=constraint,
        timezone_name=timezone_name,
        local_today=local_today,
    )
    payload: dict[str, Any] = {
        "constraint": {
            "start_date": constraint.start_date.isoformat(),
            "end_date": constraint.end_date.isoformat(),
            "sport_type": constraint.sport_type,
        },
        "impacted_sessions": [
            {
                "session_id": int(_value(session, "id") or 0),
                "scheduled_date": _local_date(_value(session, "scheduled_date"), timezone_name=timezone_name).isoformat(),
                "sport_type": _normalized_sport(_value(session, "sport_type")),
                "session_title": str(_value(session, "session_title") or ""),
                "duration_min": int(_value(session, "duration_min") or 0),
            }
            for session in impacted_sessions
        ],
    }
    payload["scope"] = {
        "covers_all_impacted_sessions": False,
        "covered_session_ids": [],
        "remaining_session_ids": [int(_value(session, "id") or 0) for session in impacted_sessions],
        "note": "La recommandation vise la prochaine seance touchee seulement. Les autres seances impactees restent a arbitrer ensuite.",
    }
    if not impacted_sessions:
        payload["recommended_mutation"] = None
        payload["validation"] = {
            "is_valid": False,
            "issues": [
                {
                    "code": "no_impacted_session",
                    "detail": "Aucune seance future ne tombe dans la fenetre de contrainte.",
                    "severity": "info",
                }
            ],
        }
        return payload

    target_session = impacted_sessions[0]
    candidate_mutations = _candidate_mutations(
        target_session=target_session,
        scheduled_sessions=scheduled_sessions,
        timezone_name=timezone_name,
        preferred_replacement_sport=preferred_replacement_sport,
    )
    if not candidate_mutations:
        payload["recommended_mutation"] = None
        payload["validation"] = {
            "is_valid": False,
            "issues": [
                {
                    "code": "no_candidate_mutation",
                    "detail": "Aucune mutation candidate propre n'a ete trouvee.",
                    "severity": "error",
                }
            ],
        }
        return payload

    primary_sport = _infer_primary_sport(scheduled_sessions, fallback=_normalized_sport(_value(target_session, "sport_type")) or "running")
    ranked: list[tuple[int, int, dict[str, Any], Any]] = []
    for mutation in candidate_mutations:
        validation = _validate_candidate_week(
            scheduled_sessions=scheduled_sessions,
            target_session=target_session,
            mutation=mutation,
            timezone_name=timezone_name,
            primary_sport=primary_sport,
        )
        same_sport_penalty = _same_sport_proximity_penalty(
            scheduled_sessions=scheduled_sessions,
            target_session=target_session,
            mutation=mutation,
            timezone_name=timezone_name,
        )
        validity_rank = 0 if validation.is_valid else 1
        ranked.append((validity_rank, same_sport_penalty, mutation, validation))

    ranked.sort(key=lambda item: (item[0], item[1]))
    _, _, selected_mutation, validation = ranked[0]
    payload["recommended_mutation"] = selected_mutation
    target_session_id = int(selected_mutation.get("target_session_id") or 0)
    payload["scope"] = {
        "covers_all_impacted_sessions": len(impacted_sessions) <= 1,
        "covered_session_ids": [target_session_id] if target_session_id else [],
        "remaining_session_ids": [
            int(_value(session, "id") or 0)
            for session in impacted_sessions
            if int(_value(session, "id") or 0) != target_session_id
        ],
        "note": (
            "La recommandation couvre uniquement la seance cible."
            if len(impacted_sessions) > 1
            else "La recommandation couvre toute la fenetre touchee."
        ),
    }
    payload["validation"] = {
        "is_valid": validation.is_valid,
        "issues": [
            {
                "code": issue.code,
                "detail": issue.detail,
                "severity": issue.severity,
            }
            for issue in validation.issues
        ],
    }
    return payload


def _resolve_constraint_window(
    *,
    active_facts: Sequence[dict[str, Any]],
    local_today: date,
    start_date: date | None,
    end_date: date | None,
    sport_type: str | None,
) -> ConstraintWindow | None:
    if start_date is not None:
        return ConstraintWindow(
            start_date=start_date,
            end_date=end_date or start_date,
            sport_type=_normalized_sport(sport_type),
        )

    for fact in active_facts:
        if str(fact.get("category") or "").lower() != "availability":
            continue
        parsed = parse_availability_fact_key(fact.get("key"))
        if parsed is None or parsed.end_date < local_today:
            continue
        return ConstraintWindow(
            start_date=max(parsed.start_date, local_today),
            end_date=parsed.end_date,
            sport_type=_normalized_sport(parsed.sport_type),
        )
    return None


def _find_impacted_sessions(
    *,
    scheduled_sessions: Sequence[Any],
    constraint: ConstraintWindow,
    timezone_name: str | None,
    local_today: date,
) -> list[Any]:
    impacted: list[Any] = []
    for session in scheduled_sessions:
        scheduled_date = _local_date(_value(session, "scheduled_date"), timezone_name=timezone_name)
        if scheduled_date is None or scheduled_date < local_today:
            continue
        if not (constraint.start_date <= scheduled_date <= constraint.end_date):
            continue
        sport = _normalized_sport(_value(session, "sport_type"))
        if sport in {None, "rest"}:
            continue
        if constraint.sport_type is not None and sport != constraint.sport_type:
            continue
        impacted.append(session)
    impacted.sort(key=lambda session: (_local_date(_value(session, "scheduled_date"), timezone_name=timezone_name), int(_value(session, "id") or 0)))
    return impacted


def _candidate_mutations(
    *,
    target_session: Any,
    scheduled_sessions: Sequence[Any],
    timezone_name: str | None,
    preferred_replacement_sport: str | None,
) -> list[dict[str, Any]]:
    target_sport = _normalized_sport(_value(target_session, "sport_type")) or "general"
    duration_min = int(_value(target_session, "duration_min") or 0)
    ordered_sports: list[str] = []
    preferred = _normalized_sport(preferred_replacement_sport)
    if preferred:
        ordered_sports.append(preferred)
    if target_sport == "swimming":
        ordered_sports.extend(["strength", "running"])
    elif target_sport == "running":
        ordered_sports.extend(["strength"])
    else:
        ordered_sports.extend(["strength", "running"])

    deduped: list[str] = []
    for sport in ordered_sports:
        if sport not in deduped:
            deduped.append(sport)

    target_date = _local_date(_value(target_session, "scheduled_date"), timezone_name=timezone_name)
    previous_sport, next_sport = _neighbor_sports(
        scheduled_sessions=scheduled_sessions,
        target_session=target_session,
        timezone_name=timezone_name,
    )
    mutations: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    for sport in deduped:
        if sport == "running":
            title = "Running relais"
            session_type = "easy"
            goal = "Remplacer la seance bloquee sans casser la semaine"
            intensity = "easy"
            new_duration = min(max(duration_min, 35), 45)
            description = f"{new_duration} min footing facile en remplacement."
        elif sport == "strength":
            title = "Renfo relais"
            session_type = "strength"
            goal = "Compenser sans charger le meme sport deux jours de suite"
            intensity = "easy"
            new_duration = 35 if duration_min >= 40 else 30
            description = f"{new_duration} min renfo support fluide."
        else:
            continue
        mutation = {
            "mutation_type": "replace_session",
            "target_session_id": int(_value(target_session, "id") or 0),
            "target_date": target_date.isoformat() if target_date else None,
            "new_sport_type": sport,
            "new_session_type": session_type,
            "new_title": title,
            "new_goal": goal,
            "new_duration_min": new_duration,
            "new_intensity": intensity,
            "new_description": description,
            "rationale": "Replan propose sur contrainte active avec validation semaine.",
        }
        if (sport == "running" and previous_sport == "running") or (
            sport == "strength" and next_sport == "strength"
        ):
            deferred.append(mutation)
        else:
            mutations.append(mutation)
    return mutations or deferred


def _validate_candidate_week(
    *,
    scheduled_sessions: Sequence[Any],
    target_session: Any,
    mutation: dict[str, Any],
    timezone_name: str | None,
    primary_sport: str,
):
    target_date = _local_date(_value(target_session, "scheduled_date"), timezone_name=timezone_name)
    assert target_date is not None
    week_start = target_date - timedelta(days=target_date.weekday())
    day_map: dict[str, dict[str, Any]] = {
        day_key: {"day": day_key, **REST_DAY}
        for day_key in DAY_ORDER
    }
    target_id = int(_value(target_session, "id") or 0)
    for session in scheduled_sessions:
        scheduled_date = _local_date(_value(session, "scheduled_date"), timezone_name=timezone_name)
        if scheduled_date is None:
            continue
        if not (week_start <= scheduled_date <= week_start + timedelta(days=6)):
            continue
        day_key = DAY_ORDER[scheduled_date.weekday()]
        if int(_value(session, "id") or 0) == target_id:
            day_map[day_key] = _day_from_mutation(day_key, mutation)
            continue
        day_map[day_key] = _day_from_session(day_key, session)
    return validate_week_plan([day_map[day_key] for day_key in DAY_ORDER], primary_sport=primary_sport)


def _day_from_session(day_key: str, session: Any) -> dict[str, Any]:
    return {
        "day": day_key,
        "sport_type": _normalized_sport(_value(session, "sport_type")) or "rest",
        "session_type": str(_value(session, "session_type") or "easy"),
        "session_title": str(_value(session, "session_title") or ""),
        "duration_min": int(_value(session, "duration_min") or 0),
        "intensity": str(_value(session, "intensity") or "easy"),
        "priority": str(_value(session, "priority") or "Normal"),
        "load_score": int(_value(session, "load_score") or 0),
    }


def _day_from_mutation(day_key: str, mutation: dict[str, Any]) -> dict[str, Any]:
    sport = _normalized_sport(mutation.get("new_sport_type")) or "rest"
    duration_min = int(mutation.get("new_duration_min") or 0)
    return {
        "day": day_key,
        "sport_type": sport,
        "session_type": str(mutation.get("new_session_type") or "easy"),
        "session_title": str(mutation.get("new_title") or ""),
        "duration_min": duration_min,
        "intensity": str(mutation.get("new_intensity") or "easy"),
        "priority": "Normal",
        "load_score": 2 if sport != "rest" and duration_min > 0 else 0,
    }


def _infer_primary_sport(scheduled_sessions: Sequence[Any], fallback: str) -> str:
    counts: dict[str, int] = {}
    for session in scheduled_sessions:
        sport = _normalized_sport(_value(session, "sport_type"))
        if sport in {None, "rest"}:
            continue
        counts[sport] = counts.get(sport, 0) + 1
    if not counts:
        return fallback
    return max(counts.items(), key=lambda item: item[1])[0]


def _same_sport_proximity_penalty(
    *,
    scheduled_sessions: Sequence[Any],
    target_session: Any,
    mutation: dict[str, Any],
    timezone_name: str | None,
) -> int:
    target_id = int(_value(target_session, "id") or 0)
    target_date = _local_date(_value(target_session, "scheduled_date"), timezone_name=timezone_name)
    replacement_sport = _normalized_sport(mutation.get("new_sport_type"))
    if target_date is None or replacement_sport is None:
        return 0
    penalty = 0
    for session in scheduled_sessions:
        if int(_value(session, "id") or 0) == target_id:
            continue
        scheduled_date = _local_date(_value(session, "scheduled_date"), timezone_name=timezone_name)
        if scheduled_date is None:
            continue
        sport = _normalized_sport(_value(session, "sport_type"))
        if sport != replacement_sport:
            continue
        if abs((scheduled_date - target_date).days) <= 1:
            penalty += 1
    return penalty


def _neighbor_sports(
    *,
    scheduled_sessions: Sequence[Any],
    target_session: Any,
    timezone_name: str | None,
) -> tuple[str | None, str | None]:
    target_id = int(_value(target_session, "id") or 0)
    target_date = _local_date(_value(target_session, "scheduled_date"), timezone_name=timezone_name)
    if target_date is None:
        return None, None
    previous_sport = None
    next_sport = None
    for session in scheduled_sessions:
        if int(_value(session, "id") or 0) == target_id:
            continue
        scheduled_date = _local_date(_value(session, "scheduled_date"), timezone_name=timezone_name)
        if scheduled_date is None:
            continue
        delta = (scheduled_date - target_date).days
        if delta == -1:
            previous_sport = _normalized_sport(_value(session, "sport_type"))
        elif delta == 1:
            next_sport = _normalized_sport(_value(session, "sport_type"))
    return previous_sport, next_sport


def _value(item: Any, field: str) -> Any:
    if isinstance(item, dict):
        return item.get(field)
    return getattr(item, field, None)


def _local_today(timezone_name: str | None, *, now: datetime | None) -> date:
    if now is None:
        return datetime.utcnow().date()
    if now.tzinfo is not None:
        return now.astimezone().date()
    return now.date()


def _local_date(value: Any, *, timezone_name: str | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            if "T" in value:
                value = datetime.fromisoformat(value)
            else:
                return date.fromisoformat(value)
        except ValueError:
            return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone().date()
        return value.date()
    return None


def _normalized_sport(value: Any) -> str | None:
    if value is None:
        return None
    sport = str(value).strip().lower()
    return sport or None
