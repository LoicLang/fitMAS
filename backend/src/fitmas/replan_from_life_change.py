from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Sequence

from fitmas.adaptation_decision import (
    AdaptationDecision,
    AdaptationLevel,
    DecisionReasonCode,
    LifeChangeEvent,
    ProposedMutation,
    ReplanScenario,
    TrajectoryImpact,
    WeekMissionStatus,
)
from fitmas.athlete_profile import AthleteProfileSnapshot
from fitmas.planning_contract import (
    AvailabilityState,
    AvailabilityConfidence,
    ChangeBudgetStatus,
    PlanConfidence,
    SessionPolicy,
    SessionRole,
    WeekMission,
    build_availability_state,
    build_planning_contract,
    build_session_policies,
    build_week_mission,
)
from fitmas.time_context import DAY_KEYS, DAY_LABELS_FR
from fitmas.user_indications import (
    UserIndication,
    UserIndicationKind,
    UserIndicationPolarity,
)
from fitmas.planning_window_resolution import PlanningWindowResolution

_UNAVAILABLE_PATTERNS = (
    "je peux pas",
    "je ne peux pas",
    "pas possible",
    "pas dispo",
    "indispo",
    "c est mort",
    "c'est mort",
    "imprevu",
    "imprevu",
)
_TONIGHT_PATTERNS = ("ce soir", "tonight", "ce soir la")
_TODAY_PATTERNS = ("aujourd hui", "aujourd'hui", "aujourdhui", "today", "cet aprem", "cet apres midi")
_TOMORROW_PATTERNS = ("demain", "tomorrow")
_FATIGUE_PATTERNS = (
    "crame",
    "cramé",
    "rince",
    "rincé",
    "fatigue",
    "fatiguee",
    "fatigué",
    "fatiguée",
    "jambes lourdes",
    "lessive",
    "lessivé",
)
_TRAVEL_PATTERNS = ("deplacement", "déplacement", "voyage", "travel", "train", "avion")
_WINDOW_PATTERNS = {
    "morning": ("matin", "morning"),
    "midday": ("midi", "midday", "aprem", "apres midi", "après midi"),
    "evening": ("soir", "evening"),
}
_DAY_ALIASES = {
    "monday": ("lundi", "monday"),
    "tuesday": ("mardi", "tuesday"),
    "wednesday": ("mercredi", "wednesday"),
    "thursday": ("jeudi", "thursday"),
    "friday": ("vendredi", "friday"),
    "saturday": ("samedi", "saturday"),
    "sunday": ("dimanche", "sunday"),
}


@dataclass(frozen=True, slots=True)
class ReplanContext:
    availability_state: AvailabilityState
    session_policies: tuple[SessionPolicy, ...]
    week_mission: WeekMission
    planning_contract: Any


def maybe_replan_from_life_change(
    *,
    user_text: str,
    today: date,
    time_context: dict[str, str] | None,
    profile: AthleteProfileSnapshot,
    week_plan: Any,
    planning_decision: Any | None,
    today_session: Any | None,
    scheduled_sessions: Sequence[Any],
) -> AdaptationDecision | None:
    context = build_replan_context(
        today=today,
        profile=profile,
        week_plan=week_plan,
        planning_decision=planning_decision,
        scheduled_sessions=scheduled_sessions,
    )
    event = extract_life_change_event(
        user_text=user_text,
        today=today,
        time_context=time_context,
        today_session=today_session,
    )
    if event is None or event.affected_session_id is None:
        return None

    impacted_policy = next((policy for policy in context.session_policies if policy.session_id == event.affected_session_id), None)
    impacted_session = next((session for session in scheduled_sessions if int(_value(session, "id") or 0) == event.affected_session_id), None)
    if impacted_policy is None or impacted_session is None:
        return None

    scenarios = _build_scenarios(
        event=event,
        today=today,
        impacted_policy=impacted_policy,
        impacted_session=impacted_session,
        scheduled_sessions=scheduled_sessions,
        context=context,
    )
    if not scenarios:
        return None

    selected = max(scenarios, key=lambda scenario: scenario.score)
    message = _build_user_message(
        scenario=selected,
        impacted_session=impacted_session,
        week_mission=context.week_mission,
    )
    alternatives = tuple(scenario for scenario in scenarios if scenario is not selected)
    return AdaptationDecision(
        event=event,
        selected_scenario=selected,
        alternative_scenarios=alternatives,
        user_message=message,
    )


def maybe_replan_from_user_indication(
    *,
    indication: UserIndication,
    resolution: PlanningWindowResolution | None,
    today: date,
    profile: AthleteProfileSnapshot,
    week_plan: Any,
    planning_decision: Any | None,
    today_session: Any | None,
    scheduled_sessions: Sequence[Any],
) -> AdaptationDecision | None:
    if indication.kind is not UserIndicationKind.AVAILABILITY_CONSTRAINT:
        return None
    if indication.polarity not in {UserIndicationPolarity.UNAVAILABLE, UserIndicationPolarity.LIMITED}:
        return None
    if resolution is None or resolution.matched_session_id is None:
        return None

    context = build_replan_context(
        today=today,
        profile=profile,
        week_plan=week_plan,
        planning_decision=planning_decision,
        scheduled_sessions=scheduled_sessions,
    )
    event = _event_from_indication(
        indication=indication,
        resolution=resolution,
        today=today,
        today_session=today_session,
    )
    if event is None or event.affected_session_id is None:
        return None

    impacted_policy = next((policy for policy in context.session_policies if policy.session_id == event.affected_session_id), None)
    impacted_session = next((session for session in scheduled_sessions if int(_value(session, "id") or 0) == event.affected_session_id), None)
    if impacted_policy is None or impacted_session is None:
        return None

    scenarios = _build_scenarios(
        event=event,
        today=today,
        impacted_policy=impacted_policy,
        impacted_session=impacted_session,
        scheduled_sessions=scheduled_sessions,
        context=context,
    )
    if not scenarios:
        return None

    selected = max(scenarios, key=lambda scenario: scenario.score)
    message = _build_user_message(
        scenario=selected,
        impacted_session=impacted_session,
        week_mission=context.week_mission,
    )
    alternatives = tuple(scenario for scenario in scenarios if scenario is not selected)
    return AdaptationDecision(
        event=event,
        selected_scenario=selected,
        alternative_scenarios=alternatives,
        user_message=message,
    )


def build_replan_context(
    *,
    today: date,
    profile: AthleteProfileSnapshot,
    week_plan: Any,
    planning_decision: Any | None,
    scheduled_sessions: Sequence[Any],
) -> ReplanContext:
    availability_state = build_availability_state(profile)
    session_policies = build_session_policies(today=today, scheduled_sessions=scheduled_sessions)
    week_mission = build_week_mission(
        today=today,
        planning_decision=planning_decision,
        scheduled_sessions=scheduled_sessions,
        session_policies=session_policies,
    )
    planning_contract = build_planning_contract(
        today=today,
        profile=profile,
        week_plan=week_plan,
        planning_decision=planning_decision,
        scheduled_sessions=scheduled_sessions,
    )
    return ReplanContext(
        availability_state=availability_state,
        session_policies=session_policies,
        week_mission=week_mission,
        planning_contract=planning_contract,
    )


def extract_life_change_event(
    *,
    user_text: str,
    today: date,
    time_context: dict[str, str] | None,
    today_session: Any | None,
) -> LifeChangeEvent | None:
    normalized = _normalize(user_text)
    reason_code = _event_reason_code(normalized)
    if reason_code is None:
        return None
    if today_session is None:
        return None

    explicit_today_reference = any(pattern in normalized for pattern in _TONIGHT_PATTERNS + _TODAY_PATTERNS)
    requested_day = _requested_day(normalized, today=today)
    requested_days = _requested_days(normalized)
    if not explicit_today_reference:
        if any(pattern in normalized for pattern in _TOMORROW_PATTERNS):
            return None
        if requested_day is not None and requested_day != DAY_KEYS[today.weekday()]:
            return None

    temporal_label = "ce soir" if any(pattern in normalized for pattern in _TONIGHT_PATTERNS) else "aujourd'hui"
    if not any(pattern in normalized for pattern in _TONIGHT_PATTERNS + _TODAY_PATTERNS):
        part_of_day = (time_context or {}).get("part_of_day")
        temporal_label = "ce soir" if part_of_day == "soir" else "aujourd'hui"

    return LifeChangeEvent(
        reason_code=reason_code,
        adaptation_level=AdaptationLevel.MICRO,
        confidence=_event_confidence(reason_code),
        affected_session_id=int(_value(today_session, "id") or 0),
        affected_date=today,
        temporal_label=temporal_label,
        details=_event_details(reason_code),
        source_text=user_text,
        requested_day=requested_day,
        requested_days=requested_days,
        requested_window=_requested_window(normalized),
        earliest_date=_requested_earliest_date(normalized, source_date=today),
    )


def _build_scenarios(
    *,
    event: LifeChangeEvent,
    today: date,
    impacted_policy: SessionPolicy,
    impacted_session: Any,
    scheduled_sessions: Sequence[Any],
    context: ReplanContext,
) -> list[ReplanScenario]:
    scenarios: list[ReplanScenario] = []
    if event.reason_code is DecisionReasonCode.FATIGUE_SIGNAL:
        return _build_fatigue_scenarios(
            impacted_policy=impacted_policy,
            context=context,
        )
    move_candidate = _find_move_candidate(
        event=event,
        impacted_session=impacted_session,
        impacted_policy=impacted_policy,
        scheduled_sessions=scheduled_sessions,
        availability_state=context.availability_state,
    )
    budget = context.planning_contract.change_budget
    protected_ids = tuple(session.session_id for session in context.week_mission.key_sessions if session.session_id != impacted_policy.session_id)

    if move_candidate is not None:
        gap_days = max(1, (move_candidate - today).days)
        move_change_cost = 1
        move_stability_penalty = _stability_penalty(
            budget_status=budget.status,
            budget_used=budget.used,
            change_cost=move_change_cost,
            adaptation_level=AdaptationLevel.MICRO,
        )
        move_score = 100.0 - (gap_days * 9) - move_stability_penalty
        if impacted_policy.role is SessionRole.KEY:
            move_score += 6
        mutation = ProposedMutation(
            mutation_type="move_session",
            target_session_id=impacted_policy.session_id,
            target_date=move_candidate.isoformat(),
            rationale="Imprevu logistique ponctuel. On deplace le creneau sans casser le fil de la semaine.",
        )
        scenarios.append(
            ReplanScenario(
                scenario_type="move",
                mutation=mutation,
                score=move_score,
                change_cost=move_change_cost,
                stability_penalty=move_stability_penalty,
                adaptation_level=AdaptationLevel.MICRO,
                week_mission_status=WeekMissionStatus.UNCHANGED,
                trajectory_impact=TrajectoryImpact.LOW,
                protected_session_ids=protected_ids,
                summary=f"Reporter la seance au {DAY_LABELS_FR[DAY_KEYS[move_candidate.weekday()]]}.",
            )
        )

    lighten_level = _lighten_adaptation_level(impacted_policy=impacted_policy, budget_status=budget.status)
    lighten_change_cost = _lighten_change_cost(role=impacted_policy.role, adaptation_level=lighten_level)
    lighten_stability_penalty = _stability_penalty(
        budget_status=budget.status,
        budget_used=budget.used,
        change_cost=lighten_change_cost,
        adaptation_level=lighten_level,
    )
    lighten_score = _lighten_base_score(role=impacted_policy.role, move_candidate=move_candidate) - lighten_stability_penalty
    mission_status = _lighten_mission_status(role=impacted_policy.role, adaptation_level=lighten_level)
    impact = _lighten_trajectory_impact(role=impacted_policy.role, adaptation_level=lighten_level)
    lighten_reason = (
        "Imprevu logistique ponctuel. On libere ce creneau et on protege la suite de la semaine."
        if move_candidate is None
        else "Imprevu logistique ponctuel. On prefere relacher ce creneau plutot que de multiplier les changements."
    )
    scenarios.append(
        ReplanScenario(
            scenario_type="lighten",
            mutation=ProposedMutation(
                mutation_type="lighten_day",
                target_session_id=impacted_policy.session_id,
                rationale=lighten_reason,
            ),
            score=lighten_score,
            change_cost=lighten_change_cost,
            stability_penalty=lighten_stability_penalty,
            adaptation_level=lighten_level,
            week_mission_status=mission_status,
            trajectory_impact=impact,
            protected_session_ids=protected_ids,
            summary=_lighten_summary(adaptation_level=lighten_level),
        )
    )
    return scenarios


def _event_from_indication(
    *,
    indication: UserIndication,
    resolution: PlanningWindowResolution,
    today: date,
    today_session: Any | None,
) -> LifeChangeEvent | None:
    if indication.kind is not UserIndicationKind.AVAILABILITY_CONSTRAINT:
        return None
    affected_session_id = resolution.matched_session_id
    affected_date = resolution.resolved_date
    if affected_session_id is None and today_session is not None and indication.time_reference and indication.time_reference.resolved_date == today:
        affected_session_id = int(_value(today_session, "id") or 0)
        affected_date = today
    if affected_session_id is None:
        return None
    temporal_label = indication.time_reference.label if indication.time_reference else "ce creneau"
    details = "Contrainte de disponibilite utilisateur."
    if indication.polarity is UserIndicationPolarity.LIMITED:
        details = "Contrainte de disponibilite partielle utilisateur."
    return LifeChangeEvent(
        reason_code=DecisionReasonCode.LOGISTICS_CONFLICT,
        adaptation_level=AdaptationLevel.MICRO,
        confidence=indication.confidence,
        affected_session_id=affected_session_id,
        affected_date=affected_date,
        temporal_label=temporal_label,
        details=details,
        source_text=indication.source_text,
        requested_day=indication.requested_days[0] if indication.requested_days else None,
        requested_days=indication.requested_days,
        requested_window=None,
        earliest_date=_day_to_candidate_date(indication.earliest_day, source_date=affected_date or today),
    )


def _find_move_candidate(
    *,
    event: LifeChangeEvent,
    impacted_session: Any,
    impacted_policy: SessionPolicy,
    scheduled_sessions: Sequence[Any],
    availability_state: AvailabilityState,
) -> date | None:
    source_date = _as_date(_value(impacted_session, "scheduled_date"))
    if source_date is None:
        return None

    max_days = max(1, impacted_policy.move_window_hours // 24)
    explicit_availability_days = {window.day for window in availability_state.preferred_windows}
    sessions_by_date = {
        _as_date(_value(session, "scheduled_date")): session
        for session in scheduled_sessions
        if _as_date(_value(session, "scheduled_date")) is not None
    }
    constrained_days = set(availability_state.constrained_days)
    requested_candidates = _requested_candidate_dates(event=event, source_date=source_date, max_days=max_days)
    candidate_pool = requested_candidates or [
        source_date + timedelta(days=offset)
        for offset in range(1, max_days + 1)
    ]
    if event.earliest_date is not None:
        candidate_pool = [candidate for candidate in candidate_pool if candidate >= event.earliest_date]
    open_candidates = [
        candidate
        for candidate in candidate_pool
        if _candidate_is_open(
            candidate=candidate,
            sessions_by_date=sessions_by_date,
            constrained_days=constrained_days,
            availability_state=availability_state,
            explicit_availability_days=explicit_availability_days,
        )
    ]
    if not open_candidates:
        return None
    return max(
        open_candidates,
        key=lambda candidate: _move_candidate_score(
            candidate=candidate,
            source_date=source_date,
            event=event,
            impacted_session=impacted_session,
            scheduled_sessions=scheduled_sessions,
        ),
    )


def _build_user_message(
    *,
    scenario: ReplanScenario,
    impacted_session: Any,
    week_mission: WeekMission,
) -> str:
    title = str(_value(impacted_session, "session_title") or "la seance")
    if scenario.scenario_type == "move" and scenario.mutation.target_date:
        target_date = date.fromisoformat(scenario.mutation.target_date)
        target_label = DAY_LABELS_FR[DAY_KEYS[target_date.weekday()]]
        lines = [
            f"OK. Je deplace {title.lower()} a {target_label}.",
            "Je protege l'objectif principal de la semaine.",
            f"Mission hebdo : {mission_status_label(scenario.week_mission_status)}.",
            f"Impact trajectoire : {trajectory_impact_label(scenario.trajectory_impact)}.",
        ]
        return "\n".join(lines)

    if scenario.scenario_type == "minimum_dose":
        lines = [
            "OK. Je garde une version courte au lieu de forcer la seance normale.",
            f"Mission hebdo : {mission_status_label(scenario.week_mission_status)}.",
            f"Impact trajectoire : {trajectory_impact_label(scenario.trajectory_impact)}.",
        ]
        if week_mission.key_sessions:
            lines.insert(1, f"Je protege encore {week_mission.key_sessions[0].title.lower()}.")
        return "\n".join(lines)

    lines = [
        "OK. Je libere ce creneau et je garde la suite propre.",
        f"Mission hebdo : {mission_status_label(scenario.week_mission_status)}.",
        f"Impact trajectoire : {trajectory_impact_label(scenario.trajectory_impact)}.",
    ]
    if scenario.adaptation_level is AdaptationLevel.MESO:
        lines.insert(1, "Je touche un peu a la forme de la semaine pour eviter une surcharge artificielle.")
    if week_mission.key_sessions:
        lines.insert(1, f"Je protege encore {week_mission.key_sessions[0].title.lower()}.")
    return "\n".join(lines)


def mission_status_label(status: WeekMissionStatus) -> str:
    mapping = {
        WeekMissionStatus.UNCHANGED: "inchangée",
        WeekMissionStatus.SOFTENED: "adoucie",
        WeekMissionStatus.REVISED: "révisée",
    }
    return mapping[status]


def trajectory_impact_label(impact: TrajectoryImpact) -> str:
    mapping = {
        TrajectoryImpact.NONE: "nul",
        TrajectoryImpact.LOW: "faible",
        TrajectoryImpact.MODERATE: "modéré",
        TrajectoryImpact.SIGNIFICANT: "marqué",
    }
    return mapping[impact]


def _normalize(value: str) -> str:
    lowered = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii").lower()
    return " ".join(lowered.split())


def _value(obj: Any, key: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    try:
        return value.date()
    except AttributeError:
        return None


def _lighten_adaptation_level(*, impacted_policy: SessionPolicy, budget_status: ChangeBudgetStatus) -> AdaptationLevel:
    if impacted_policy.role is SessionRole.KEY:
        return AdaptationLevel.MESO
    if budget_status is ChangeBudgetStatus.EXHAUSTED and impacted_policy.role is SessionRole.SUPPORT:
        return AdaptationLevel.MESO
    return AdaptationLevel.MICRO


def _lighten_change_cost(*, role: SessionRole, adaptation_level: AdaptationLevel) -> int:
    base = {
        SessionRole.OPTIONAL: 1,
        SessionRole.RECOVERY: 1,
        SessionRole.SUPPORT: 2,
        SessionRole.KEY: 4,
    }[role]
    if adaptation_level is AdaptationLevel.MESO:
        return base + 1
    return base


def _stability_penalty(
    *,
    budget_status: ChangeBudgetStatus,
    budget_used: int,
    change_cost: int,
    adaptation_level: AdaptationLevel,
) -> float:
    penalty = float(max(0, budget_used) * 5)
    penalty += max(0, change_cost - 1) * 4.0
    if budget_status is ChangeBudgetStatus.WATCH:
        penalty += 6.0
    elif budget_status is ChangeBudgetStatus.EXHAUSTED:
        penalty += 14.0
    if adaptation_level is AdaptationLevel.MESO:
        penalty += 8.0
    return penalty


def _lighten_base_score(*, role: SessionRole, move_candidate: date | None) -> float:
    if role in {SessionRole.OPTIONAL, SessionRole.RECOVERY}:
        return 62.0
    if role is SessionRole.SUPPORT:
        return 50.0 if move_candidate is None else 42.0
    return 34.0


def _lighten_mission_status(*, role: SessionRole, adaptation_level: AdaptationLevel) -> WeekMissionStatus:
    if adaptation_level is AdaptationLevel.MICRO:
        return WeekMissionStatus.UNCHANGED
    if role is SessionRole.KEY:
        return WeekMissionStatus.SOFTENED
    return WeekMissionStatus.SOFTENED


def _lighten_trajectory_impact(*, role: SessionRole, adaptation_level: AdaptationLevel) -> TrajectoryImpact:
    if adaptation_level is AdaptationLevel.MICRO:
        if role in {SessionRole.OPTIONAL, SessionRole.RECOVERY}:
            return TrajectoryImpact.NONE
        return TrajectoryImpact.LOW
    if role is SessionRole.KEY:
        return TrajectoryImpact.MODERATE
    return TrajectoryImpact.LOW


def _lighten_summary(*, adaptation_level: AdaptationLevel) -> str:
    if adaptation_level is AdaptationLevel.MESO:
        return "Alleger ce creneau et adoucir la semaine pour garder une charge credible."
    return "Liberer le creneau et garder le reste lisible."


def _build_fatigue_scenarios(
    *,
    impacted_policy: SessionPolicy,
    context: ReplanContext,
) -> list[ReplanScenario]:
    protected_ids = tuple(session.session_id for session in context.week_mission.key_sessions if session.session_id != impacted_policy.session_id)
    budget = context.planning_contract.change_budget
    scenarios: list[ReplanScenario] = []

    minimum_level = AdaptationLevel.MICRO if impacted_policy.role in {SessionRole.SUPPORT, SessionRole.RECOVERY, SessionRole.OPTIONAL} else AdaptationLevel.MESO
    minimum_duration = impacted_policy.minimum_duration_min or 25
    minimum_change_cost = 2 if minimum_level is AdaptationLevel.MICRO else 4
    minimum_penalty = _stability_penalty(
        budget_status=budget.status,
        budget_used=budget.used,
        change_cost=minimum_change_cost,
        adaptation_level=minimum_level,
    )
    scenarios.append(
        ReplanScenario(
            scenario_type="minimum_dose",
            mutation=ProposedMutation(
                mutation_type="replace_session",
                target_session_id=impacted_policy.session_id,
                rationale="Signal de fatigue du jour. On garde le minimum efficace sans ajouter de dette de recuperation.",
                new_title=f"{impacted_policy.title} · version courte",
                new_goal="Garder le fil sans forcer. Priorite a la fraicheur.",
                new_session_type="recovery" if impacted_policy.role is SessionRole.KEY else "easy",
                new_duration_min=minimum_duration,
                new_intensity="easy",
                new_description=f"Version courte {minimum_duration} min pour absorber la fatigue du jour.",
            ),
            score=72.0 - minimum_penalty,
            change_cost=minimum_change_cost,
            stability_penalty=minimum_penalty,
            adaptation_level=minimum_level,
            week_mission_status=WeekMissionStatus.SOFTENED if minimum_level is AdaptationLevel.MESO else WeekMissionStatus.UNCHANGED,
            trajectory_impact=TrajectoryImpact.LOW if minimum_level is AdaptationLevel.MICRO else TrajectoryImpact.MODERATE,
            protected_session_ids=protected_ids,
            summary="Garder le minimum efficace et sauver la recuperation.",
        )
    )

    lighten_level = AdaptationLevel.MESO if impacted_policy.role is SessionRole.KEY else AdaptationLevel.MICRO
    lighten_change_cost = _lighten_change_cost(role=impacted_policy.role, adaptation_level=lighten_level)
    lighten_penalty = _stability_penalty(
        budget_status=budget.status,
        budget_used=budget.used,
        change_cost=lighten_change_cost,
        adaptation_level=lighten_level,
    )
    scenarios.append(
        ReplanScenario(
            scenario_type="lighten",
            mutation=ProposedMutation(
                mutation_type="lighten_day",
                target_session_id=impacted_policy.session_id,
                rationale="Signal de fatigue du jour. On coupe franchement pour proteger la suite du bloc.",
            ),
            score=58.0 - lighten_penalty,
            change_cost=lighten_change_cost,
            stability_penalty=lighten_penalty,
            adaptation_level=lighten_level,
            week_mission_status=WeekMissionStatus.SOFTENED,
            trajectory_impact=TrajectoryImpact.MODERATE if impacted_policy.role is SessionRole.KEY else TrajectoryImpact.LOW,
            protected_session_ids=protected_ids,
            summary="Alleger franchement aujourd'hui pour proteger la suite.",
        )
    )
    return scenarios


def _event_reason_code(normalized: str) -> DecisionReasonCode | None:
    if any(pattern in normalized for pattern in _FATIGUE_PATTERNS):
        return DecisionReasonCode.FATIGUE_SIGNAL
    if any(pattern in normalized for pattern in _UNAVAILABLE_PATTERNS):
        if any(pattern in normalized for pattern in _TRAVEL_PATTERNS):
            return DecisionReasonCode.TRAVEL_CONSTRAINT
        return DecisionReasonCode.LOGISTICS_CONFLICT
    return None


def _event_confidence(reason_code: DecisionReasonCode) -> float:
    if reason_code is DecisionReasonCode.FATIGUE_SIGNAL:
        return 0.9
    if reason_code is DecisionReasonCode.TRAVEL_CONSTRAINT:
        return 0.93
    return 0.92


def _event_details(reason_code: DecisionReasonCode) -> str:
    if reason_code is DecisionReasonCode.FATIGUE_SIGNAL:
        return "Signal de fatigue sur le creneau du jour."
    if reason_code is DecisionReasonCode.TRAVEL_CONSTRAINT:
        return "Contrainte de deplacement ou trajet sur le creneau du jour."
    return "Indisponibilite ponctuelle sur le creneau du jour."


def _requested_day(normalized: str, *, today: date) -> str | None:
    for day_key in _requested_days(normalized):
        if day_key != DAY_KEYS[today.weekday()]:
            return day_key
    return None


def _requested_days(normalized: str) -> tuple[str, ...]:
    positions: list[tuple[int, str]] = []
    weekend_index = normalized.find("weekend")
    if weekend_index == -1:
        weekend_index = normalized.find("week end")
    if weekend_index >= 0:
        positions.extend(((weekend_index, "saturday"), (weekend_index + 1, "sunday")))
    for day_key, aliases in _DAY_ALIASES.items():
        for alias in aliases:
            index = normalized.find(alias)
            if index != -1:
                positions.append((index, day_key))
                break
    ordered: list[str] = []
    for _, day_key in sorted(positions, key=lambda item: item[0]):
        if day_key not in ordered:
            ordered.append(day_key)
    return tuple(ordered)


def _requested_window(normalized: str) -> str | None:
    for window, patterns in _WINDOW_PATTERNS.items():
        if any(pattern in normalized for pattern in patterns):
            return window
    return None


def _requested_candidate_dates(*, event: LifeChangeEvent, source_date: date, max_days: int) -> list[date]:
    requested_days = event.requested_days or ((event.requested_day,) if event.requested_day else ())
    candidates: list[date] = []
    for requested_day in requested_days:
        candidate = _day_to_candidate_date(requested_day, source_date=source_date)
        if candidate is None:
            continue
        delta = (candidate - source_date).days
        if delta <= 0 or delta > max_days:
            continue
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates


def _requested_earliest_date(normalized: str, *, source_date: date) -> date | None:
    for pattern in (
        r"pas avant (?P<day>lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)",
        r"a partir de (?P<day>lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)",
        r"apres (?P<day>lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)",
    ):
        match = re.search(pattern, normalized)
        if not match:
            continue
        token = match.group("day")
        for day_key, aliases in _DAY_ALIASES.items():
            if token in aliases:
                return _day_to_candidate_date(day_key, source_date=source_date)
    return None


def _day_to_candidate_date(day_key: str | None, *, source_date: date) -> date | None:
    if not day_key:
        return None
    requested_idx = DAY_KEYS.index(day_key)
    delta = (requested_idx - source_date.weekday()) % 7
    if delta == 0:
        delta = 7
    return source_date + timedelta(days=delta)


def _move_candidate_score(
    *,
    candidate: date,
    source_date: date,
    event: LifeChangeEvent,
    impacted_session: Any,
    scheduled_sessions: Sequence[Any],
) -> float:
    gap_days = max(1, (candidate - source_date).days)
    score = 100.0 - (gap_days * 9)
    candidate_day = DAY_KEYS[candidate.weekday()]
    for idx, requested_day in enumerate(event.requested_days):
        if candidate_day == requested_day:
            score += max(0.0, 18.0 - (idx * 6.0))
            break
    if event.earliest_date is not None and candidate == event.earliest_date:
        score += 4.0
    score -= _candidate_coherence_penalty(
        candidate=candidate,
        impacted_session=impacted_session,
        scheduled_sessions=scheduled_sessions,
    )
    return score


def _candidate_coherence_penalty(
    *,
    candidate: date,
    impacted_session: Any,
    scheduled_sessions: Sequence[Any],
) -> float:
    impacted_id = int(_value(impacted_session, "id") or 0)
    impacted_sport = str(_value(impacted_session, "sport_type") or "").lower()
    penalty = 0.0
    for session in scheduled_sessions:
        if int(_value(session, "id") or 0) == impacted_id:
            continue
        session_date = _as_date(_value(session, "scheduled_date"))
        if session_date is None:
            continue
        sport_type = str(_value(session, "sport_type") or "").lower()
        if sport_type in {"rest", "off"}:
            continue
        delta_days = abs((session_date - candidate).days)
        if delta_days == 0 and sport_type == impacted_sport:
            penalty += 28.0
        elif delta_days == 1 and sport_type == impacted_sport:
            penalty += 24.0
        elif delta_days == 1 and str(_value(session, "priority") or "").lower() in {"high", "cle", "seance cle", "key"}:
            penalty += 8.0
    return penalty


def _candidate_is_open(
    *,
    candidate: date,
    sessions_by_date: dict[date, Any],
    constrained_days: set[str],
    availability_state: AvailabilityState,
    explicit_availability_days: set[str],
) -> bool:
    day_key = DAY_KEYS[candidate.weekday()]
    if day_key in constrained_days:
        return False
    if availability_state.confidence is not AvailabilityConfidence.CONFIRMED and day_key not in explicit_availability_days:
        return False
    existing = sessions_by_date.get(candidate)
    if existing is None:
        return True
    existing_sport = str(_value(existing, "sport_type") or "").lower()
    existing_flexibility = str(_value(existing, "flexibility") or "").lower()
    return existing_sport in {"rest", "off"} or existing_flexibility == "flexible"
