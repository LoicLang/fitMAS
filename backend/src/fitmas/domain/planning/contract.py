from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Any, Sequence

from fitmas.domain.athlete.profile import AthleteProfileSnapshot
from fitmas.domain.athlete.load_projection import planning_mode_label_fr

REST_SPORTS = {"rest", "off"}
DAY_LABELS_FR = {
    "monday": "Lun",
    "tuesday": "Mar",
    "wednesday": "Mer",
    "thursday": "Jeu",
    "friday": "Ven",
    "saturday": "Sam",
    "sunday": "Dim",
}
SPORT_LABELS_FR = {
    "running": "course",
    "cycling": "velo",
    "swimming": "natation",
    "climbing": "escalade",
    "strength": "renfo",
}
DAY_PART_KEYWORDS = {
    "morning": ("matin", "morning", "7h", "8h"),
    "midday": ("midi", "midday", "noon"),
    "evening": ("soir", "evening", "18h", "19h", "20h"),
}
NEGATIVE_AVAILABILITY_KEYWORDS = (
    "indispo",
    "impossible",
    "pas possible",
    "pas dispo",
    "boulot",
    "travail",
    "voyage",
    "deplacement",
    "déplacement",
)
KEY_SESSION_TYPES = {"tempo", "threshold", "vo2", "interval", "long", "race"}
RECOVERY_SESSION_TYPES = {"rest", "recovery", "mobility", "easy"}
OPTIONAL_PRIORITY_KEYWORDS = ("bonus", "option", "facult", "low")
KEY_PRIORITY_KEYWORDS = ("cle", "clé", "high", "prior")


class PlanConfidence(StrEnum):
    COMMITTED = "committed"
    TENTATIVE = "tentative"
    PROJECTED = "projected"


class SessionRole(StrEnum):
    KEY = "key"
    SUPPORT = "support"
    RECOVERY = "recovery"
    OPTIONAL = "optional"


class AvailabilityConfidence(StrEnum):
    CONFIRMED = "confirmed"
    INFERRED = "inferred"
    SPARSE = "sparse"


class ChangeBudgetStatus(StrEnum):
    STABLE = "stable"
    WATCH = "watch"
    EXHAUSTED = "exhausted"


@dataclass(frozen=True, slots=True)
class PlanningHorizon:
    key: str
    label: str
    confidence: PlanConfidence
    summary: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "confidence": self.confidence.value,
            "summary": self.summary,
        }


@dataclass(frozen=True, slots=True)
class ChangeBudget:
    total: int
    used: int
    remaining: int
    status: ChangeBudgetStatus

    def as_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "used": self.used,
            "remaining": self.remaining,
            "status": self.status.value,
        }


@dataclass(frozen=True, slots=True)
class DayAvailability:
    day: str
    label: str
    windows: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "day": self.day,
            "label": self.label,
            "windows": list(self.windows),
        }


@dataclass(frozen=True, slots=True)
class AvailabilityState:
    confidence: AvailabilityConfidence
    preferred_windows: tuple[DayAvailability, ...]
    constrained_days: tuple[str, ...]
    equipment: tuple[str, ...]
    preferred_training_times: tuple[str, ...]
    summary: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "confidence": self.confidence.value,
            "preferred_windows": [window.as_dict() for window in self.preferred_windows],
            "constrained_days": list(self.constrained_days),
            "equipment": list(self.equipment),
            "preferred_training_times": list(self.preferred_training_times),
            "summary": self.summary,
        }


@dataclass(frozen=True, slots=True)
class SessionPolicy:
    session_id: int
    title: str
    day: str
    label: str
    scheduled_date: str
    sport_type: str
    role: SessionRole
    confidence: PlanConfidence
    move_window_hours: int
    minimum_duration_min: int | None
    drop_cost: int
    substitutions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MissionSessionRef:
    session_id: int
    title: str
    label: str
    role: SessionRole
    confidence: PlanConfidence

    def as_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "title": self.title,
            "label": self.label,
            "role": self.role.value,
            "confidence": self.confidence.value,
        }


@dataclass(frozen=True, slots=True)
class WeekMission:
    objective: str
    objective_reason: str
    success_criteria: str
    minimum_success: str
    primary_risk: str
    mission_status: str
    key_sessions: tuple[MissionSessionRef, ...]
    support_sessions: tuple[MissionSessionRef, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "objective": self.objective,
            "objective_reason": self.objective_reason,
            "success_criteria": self.success_criteria,
            "minimum_success": self.minimum_success,
            "primary_risk": self.primary_risk,
            "mission_status": self.mission_status,
            "key_sessions": [session.as_dict() for session in self.key_sessions],
            "support_sessions": [session.as_dict() for session in self.support_sessions],
        }


@dataclass(frozen=True, slots=True)
class PlanningContract:
    phase_label: str
    block_focus: str
    cycle_position: str
    horizon_summary: str
    next_inflexion: str
    adaptation_mode: str
    horizons: tuple[PlanningHorizon, ...]
    change_budget: ChangeBudget

    def as_dict(self) -> dict[str, Any]:
        return {
            "phase_label": self.phase_label,
            "block_focus": self.block_focus,
            "cycle_position": self.cycle_position,
            "horizon_summary": self.horizon_summary,
            "next_inflexion": self.next_inflexion,
            "adaptation_mode": self.adaptation_mode,
            "horizons": [horizon.as_dict() for horizon in self.horizons],
            "change_budget": self.change_budget.as_dict(),
        }


def build_availability_state(profile: AthleteProfileSnapshot) -> AvailabilityState:
    windows: list[DayAvailability] = []
    constrained_days: list[str] = []

    for day, snippets in sorted(profile.weekly_availability.items()):
        day_windows = _detect_day_windows(snippets, fallback=profile.preferred_training_times)
        if any(any(keyword in snippet.lower() for keyword in NEGATIVE_AVAILABILITY_KEYWORDS) for snippet in snippets):
            constrained_days.append(day)
        windows.append(DayAvailability(day=day, label=DAY_LABELS_FR.get(day, day[:3].capitalize()), windows=day_windows))

    if len(windows) >= 3:
        confidence = AvailabilityConfidence.CONFIRMED
    elif windows:
        confidence = AvailabilityConfidence.INFERRED
    else:
        confidence = AvailabilityConfidence.SPARSE

    if confidence is AvailabilityConfidence.CONFIRMED:
        summary = "Disponibilites connues sur plusieurs jours, le moteur peut replanifier sans clarifier a chaque fois."
    elif confidence is AvailabilityConfidence.INFERRED:
        summary = "Structure partielle seulement, le moteur peut s'adapter mais devra parfois confirmer un creneau."
    else:
        summary = "Disponibilites encore floues, les gros replans doivent rester prudents."

    return AvailabilityState(
        confidence=confidence,
        preferred_windows=tuple(windows),
        constrained_days=tuple(dict.fromkeys(constrained_days)),
        equipment=tuple(profile.equipment),
        preferred_training_times=tuple(profile.preferred_training_times),
        summary=summary,
    )


def build_session_policies(*, today: date, scheduled_sessions: Sequence[Any]) -> tuple[SessionPolicy, ...]:
    policies: list[tuple[date, SessionPolicy]] = []
    for session in scheduled_sessions:
        sport = str(_value(session, "sport_type") or "").lower()
        if sport in REST_SPORTS:
            continue
        session_date = _as_date(_value(session, "scheduled_date")) or today
        role = _session_role(session)
        confidence = _session_confidence(today=today, session_date=session_date)
        duration_min = _int_or_none(_value(session, "duration_min"))
        policies.append(
            (
                session_date,
                SessionPolicy(
                session_id=int(_value(session, "id") or 0),
                title=str(_value(session, "session_title") or ""),
                day=str(_value(session, "day") or ""),
                label=str(_value(session, "label") or DAY_LABELS_FR.get(str(_value(session, "day") or ""), "")),
                scheduled_date=session_date.isoformat(),
                sport_type=sport,
                role=role,
                confidence=confidence,
                move_window_hours=_move_window_hours(role=role, confidence=confidence),
                minimum_duration_min=_minimum_effective_dose(duration_min=duration_min, role=role),
                drop_cost=_drop_cost(role=role),
                substitutions=_substitutions_for_session(role=role, sport_type=sport),
                ),
            )
        )
    return tuple(policy for _, policy in sorted(policies, key=lambda item: (item[0], item[1].session_id)))


def build_week_mission(
    *,
    today: date,
    planning_decision: Any | None,
    scheduled_sessions: Sequence[Any],
    session_policies: Sequence[SessionPolicy],
) -> WeekMission:
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    week_sessions = [
        session
        for session in scheduled_sessions
        if (session_date := _as_date(_value(session, "scheduled_date"))) is not None
        and week_start <= session_date <= week_end
        and str(_value(session, "sport_type") or "").lower() not in REST_SPORTS
    ]
    week_session_ids = {int(_value(session, "id") or 0) for session in week_sessions}
    week_policy_by_id = {policy.session_id: policy for policy in session_policies if policy.session_id in week_session_ids}
    key_sessions = tuple(
        _mission_session_ref(policy)
        for policy in week_policy_by_id.values()
        if policy.role is SessionRole.KEY
    )
    support_sessions = tuple(
        _mission_session_ref(policy)
        for policy in week_policy_by_id.values()
        if policy.role in {SessionRole.SUPPORT, SessionRole.RECOVERY}
    )

    mode_key = str(_value(planning_decision, "planning_mode") or "maintain_load")
    target_tss = round(float(_value(planning_decision, "weekly_target_tss") or 0.0), 1)
    objective = _week_objective(mode_key)
    objective_reason = str(next(iter(_value(planning_decision, "rationale") or []), "Le plan cherche la meilleure progression compatible avec ta vraie vie."))
    primary_risk = _primary_risk(mode_key)

    if key_sessions:
        success_criteria = f"Valider {len(key_sessions)} seance(s) cle(s) et garder la semaine coherente autour de {int(target_tss) if target_tss else 'la'} TSS cible."
        minimum_success = f"Sauver au moins {key_sessions[0].title.lower()} ou sa version courte sans empiler une seconde contrainte derriere."
    elif week_sessions:
        success_criteria = "Garder de la regularite utile sans transformer la semaine en puzzle."
        minimum_success = "Conserver une charge lisible et eviter les changements de derniere minute en cascade."
    else:
        success_criteria = "Rester disponible pour repartir proprement."
        minimum_success = "Ne pas rajouter de fatigue artificielle."

    return WeekMission(
        objective=objective,
        objective_reason=objective_reason,
        success_criteria=success_criteria,
        minimum_success=minimum_success,
        primary_risk=primary_risk,
        mission_status="committed",
        key_sessions=key_sessions[:3],
        support_sessions=support_sessions[:3],
    )


def build_planning_contract(
    *,
    today: date,
    profile: AthleteProfileSnapshot,
    week_plan: Any,
    planning_decision: Any | None,
    scheduled_sessions: Sequence[Any],
) -> PlanningContract:
    mesocycle_week = int(_value(week_plan, "mesocycle_week") or 1)
    is_deload = bool(_value(week_plan, "is_deload"))
    mode_key = str(_value(planning_decision, "planning_mode") or "maintain_load")
    phase_label = f"{planning_mode_label_fr(mode_key)} · semaine {mesocycle_week}/4"
    cycle_position = f"{mesocycle_week}/4"
    block_focus = _block_focus_label(mode_key=mode_key, primary_sport=profile.primary_sport)
    next_inflexion = _next_inflexion(mesocycle_week=mesocycle_week, is_deload=is_deload)
    horizons = (
        PlanningHorizon("today", "Aujourd'hui", PlanConfidence.COMMITTED, "Exact et actionnable."),
        PlanningHorizon("week", "7 jours", PlanConfidence.COMMITTED, "Engage, mais reconfigurable sous contrainte."),
        PlanningHorizon("next", "J+8 a J+14", PlanConfidence.TENTATIVE, "Probable, encore ajustable."),
        PlanningHorizon("block", "Bloc", PlanConfidence.PROJECTED, "Intention strategique, pas promesse detaillee."),
    )
    change_budget = _change_budget(today=today, scheduled_sessions=scheduled_sessions, planning_mode=mode_key)
    return PlanningContract(
        phase_label=phase_label,
        block_focus=block_focus,
        cycle_position=cycle_position,
        horizon_summary="Aujourd'hui exact, semaine engagee, J+8 a J+14 probables, bloc en intention.",
        next_inflexion=next_inflexion,
        adaptation_mode=planning_mode_label_fr(mode_key),
        horizons=horizons,
        change_budget=change_budget,
    )


def _detect_day_windows(snippets: Sequence[str], *, fallback: Sequence[str]) -> tuple[str, ...]:
    detected: list[str] = []
    for snippet in snippets:
        normalized = snippet.lower()
        for label, keywords in DAY_PART_KEYWORDS.items():
            if label in detected:
                continue
            if any(keyword in normalized for keyword in keywords):
                detected.append(label)
    if not detected:
        detected.extend(item for item in fallback if item in DAY_PART_KEYWORDS)
    return tuple(detected)


def _session_role(session: Any) -> SessionRole:
    session_type = str(_value(session, "session_type") or "").lower()
    intensity = str(_value(session, "intensity") or "").lower()
    priority = str(_value(session, "priority") or "").lower()
    load_score = int(_value(session, "load_score") or 0)

    if session_type in RECOVERY_SESSION_TYPES or intensity in {"recovery"}:
        return SessionRole.RECOVERY
    if any(keyword in priority for keyword in OPTIONAL_PRIORITY_KEYWORDS):
        return SessionRole.OPTIONAL
    if session_type in KEY_SESSION_TYPES or intensity in {"hard", "threshold"} or load_score >= 4 or any(keyword in priority for keyword in KEY_PRIORITY_KEYWORDS):
        return SessionRole.KEY
    if intensity in {"easy", "moderate"} and load_score <= 2:
        return SessionRole.SUPPORT
    return SessionRole.SUPPORT


def _session_confidence(*, today: date, session_date: date) -> PlanConfidence:
    delta_days = (session_date - today).days
    if delta_days <= 6:
        return PlanConfidence.COMMITTED
    if delta_days <= 13:
        return PlanConfidence.TENTATIVE
    return PlanConfidence.PROJECTED


def _move_window_hours(*, role: SessionRole, confidence: PlanConfidence) -> int:
    if confidence is PlanConfidence.PROJECTED:
        return 168
    mapping = {
        SessionRole.KEY: 48,
        SessionRole.SUPPORT: 72,
        SessionRole.RECOVERY: 24,
        SessionRole.OPTIONAL: 96,
    }
    return mapping[role]


def _minimum_effective_dose(*, duration_min: int | None, role: SessionRole) -> int | None:
    if duration_min is None or duration_min <= 0:
        return None
    multiplier = {
        SessionRole.KEY: 0.6,
        SessionRole.SUPPORT: 0.5,
        SessionRole.RECOVERY: 0.5,
        SessionRole.OPTIONAL: 0.4,
    }[role]
    return max(20, int(round((duration_min * multiplier) / 5.0) * 5))


def _drop_cost(*, role: SessionRole) -> int:
    return {
        SessionRole.KEY: 5,
        SessionRole.SUPPORT: 3,
        SessionRole.RECOVERY: 1,
        SessionRole.OPTIONAL: 1,
    }[role]


def _substitutions_for_session(*, role: SessionRole, sport_type: str) -> tuple[str, ...]:
    if role is SessionRole.RECOVERY:
        return ("mobility", "walk", "easy_spin")
    if role is SessionRole.OPTIONAL:
        return ("drop", "short_easy", "mobility")
    if sport_type == "cycling":
        return ("indoor_trainer", "shorter_quality", "easy_spin")
    if sport_type == "running":
        return ("shorter_quality_run", "easy_run", "indoor_bike")
    if sport_type == "swimming":
        return ("short_technique", "easy_swim", "mobility")
    if sport_type == "strength":
        return ("compressed_strength", "mobility", "bodyweight")
    return ("shorter_version", "easy_version", "mobility")


def _week_objective(mode_key: str) -> str:
    mapping = {
        "increase_load": "Pousser la charge utile sans casser la regularite.",
        "maintain_load": "Consolider la regularite utile de la semaine.",
        "reduce_load": "Alleger sans perdre le fil du bloc.",
        "deload": "Assimiler et refaire du jus.",
        "restart_consistency": "Relancer simple et remettre de la regularite avant de recharger.",
        "tactical_adjustment": "Sauver la semaine avec le moins de friction possible.",
        "injury_protection": "Proteger le corps et garder le minimum efficace.",
    }
    return mapping.get(mode_key, "Garder une semaine lisible et utile.")


def _primary_risk(mode_key: str) -> str:
    mapping = {
        "increase_load": "Empiler deux contraintes dures ou depasser la recup disponible.",
        "maintain_load": "Diluer la seance cle dans trop de flexibilite.",
        "reduce_load": "Garder trop de volume par culpabilite.",
        "deload": "Transformer l'assimilation en semaine cachee de charge.",
        "restart_consistency": "Vouloir reprendre au rythme d'une semaine deja bien encaissee.",
        "tactical_adjustment": "Multiplier les petits changements et perdre la lisibilite.",
        "injury_protection": "Forcer une intensite qui rallume la douleur.",
    }
    return mapping.get(mode_key, "Changer trop de choses a la fois.")


def _block_focus_label(*, mode_key: str, primary_sport: str) -> str:
    sport_label = SPORT_LABELS_FR.get(primary_sport, primary_sport)
    mapping = {
        "increase_load": f"Charge progressive en {sport_label}",
        "maintain_load": f"Consolidation utile en {sport_label}",
        "reduce_load": "Alleger pour repartir propre",
        "deload": "Assimilation du bloc",
        "restart_consistency": "Relance de la regularite",
        "tactical_adjustment": "Semaine tactique adaptable",
        "injury_protection": "Protection active avant tout",
    }
    return mapping.get(mode_key, "Bloc actif")


def _next_inflexion(*, mesocycle_week: int, is_deload: bool) -> str:
    if is_deload:
        return "Relance la semaine prochaine si les signaux restent stables."
    weeks_until_deload = max(0, 4 - mesocycle_week)
    if weeks_until_deload <= 1:
        return "Semaine d'assimilation a venir tres bientot."
    return f"Assimilation prevue dans {weeks_until_deload} semaine(s)."


def _change_budget(*, today: date, scheduled_sessions: Sequence[Any], planning_mode: str) -> ChangeBudget:
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    week_sessions = [
        session
        for session in scheduled_sessions
        if (session_date := _as_date(_value(session, "scheduled_date"))) is not None
        and week_start <= session_date <= week_end
        and str(_value(session, "sport_type") or "").lower() not in REST_SPORTS
    ]
    base_total = 3 if planning_mode in {"tactical_adjustment", "injury_protection", "restart_consistency"} else 2
    total = min(4, max(base_total, len(week_sessions) // 3 + 1))
    used = sum(1 for session in week_sessions if str(_value(session, "completion_status") or "").lower() in {"adapted", "skipped"})
    remaining = max(0, total - used)
    if used == 0:
        status = ChangeBudgetStatus.STABLE
    elif remaining > 0:
        status = ChangeBudgetStatus.WATCH
    else:
        status = ChangeBudgetStatus.EXHAUSTED
    return ChangeBudget(total=total, used=used, remaining=remaining, status=status)


def _mission_session_ref(policy: SessionPolicy) -> MissionSessionRef:
    return MissionSessionRef(
        session_id=policy.session_id,
        title=policy.title,
        label=policy.label,
        role=policy.role,
        confidence=policy.confidence,
    )


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            return None
    return None
