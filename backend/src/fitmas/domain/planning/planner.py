from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from fitmas.domain.athlete.profile import AthleteProfileSnapshot
from fitmas.domain.athlete.zones import AthleteZones
from fitmas.plan_validator import validate_week_plan
from fitmas.domain.planning.planning_config import get_sport_planning_config
from fitmas.domain.planning.planning_decision import PlanningDecision
from fitmas.domain.planning.session_templates import render_session_description, select_session_template

logger = logging.getLogger(__name__)

DAY_KEYS = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]

DAY_LABELS = {
    "monday": "Lundi",
    "tuesday": "Mardi",
    "wednesday": "Mercredi",
    "thursday": "Jeudi",
    "friday": "Vendredi",
    "saturday": "Samedi",
    "sunday": "Dimanche",
}

SPORT_SYNONYMS = {
    "running": ("running", "run", "course", "jogging", "trail"),
    "cycling": ("cycling", "velo", "vélo", "bike", "ride", "cyclisme"),
    "swimming": ("swimming", "swim", "natation", "piscine"),
    "climbing": ("climbing", "climb", "escalade", "bloc", "bouldering", "voie"),
    "strength": ("strength", "renfo", "renforcement", "muscu", "gym", "gainage"),
}

DAY_SYNONYMS = {
    "monday": ("lundi", "monday"),
    "tuesday": ("mardi", "tuesday"),
    "wednesday": ("mercredi", "wednesday"),
    "thursday": ("jeudi", "thursday"),
    "friday": ("vendredi", "friday"),
    "saturday": ("samedi", "saturday"),
    "sunday": ("dimanche", "sunday"),
}


@dataclass(slots=True)
class PlannedSession:
    sport_type: str
    session_type: str
    duration_min: int
    intensity: str
    load_score: int
    priority: str
    preferred_day: str | None = None


def normalize_sports(raw_values: list[str] | str) -> list[str]:
    if isinstance(raw_values, str):
        candidates = re.split(r"[,\n;/]+", raw_values)
    else:
        candidates = []
        for value in raw_values:
            candidates.extend(re.split(r"[,\n;/]+", value))

    normalized: list[str] = []
    for candidate in candidates:
        text = candidate.strip().lower()
        if not text:
            continue
        for sport, synonyms in SPORT_SYNONYMS.items():
            if any(token in text for token in synonyms):
                if sport not in normalized:
                    normalized.append(sport)
                break
    return normalized or ["running"]


def build_week_plan(
    *,
    sports: list[str],
    weekly_structure_notes: str,
    constraints: list[str],
    coach_name: str,
    planning_decision: PlanningDecision | None = None,
    athlete_profile: AthleteProfileSnapshot | None = None,
    zones: AthleteZones | None = None,
    cycle_week: int = 1,
) -> dict:
    normalized_sports = normalize_sports(list(athlete_profile.primary_sports) if athlete_profile is not None else sports)
    notes_blob = " ".join(
        [
            weekly_structure_notes,
            *constraints,
            *(athlete_profile.constraints if athlete_profile is not None else ()),
            *(athlete_profile.preferences if athlete_profile is not None else ()),
        ]
    ).lower()

    blocked_days = _extract_days(notes_blob, ("bloque", "bloqué", "indispo", "pas dispo", "jamais"))
    fragile_days = _extract_days(notes_blob, ("fragile", "leger", "léger", "light", "souple", "doux"))
    long_day = _extract_long_day(notes_blob, blocked_days)
    key_day = _pick_key_day(blocked_days, fragile_days, long_day)

    sessions = _build_sessions(
        normalized_sports=normalized_sports,
        key_day=key_day,
        long_day=long_day,
        planning_decision=planning_decision,
        athlete_profile=athlete_profile,
    )
    athlete_level = _resolve_athlete_level(athlete_profile, normalized_sports[0])
    days = _schedule_sessions(
        sessions=sessions,
        blocked_days=blocked_days,
        fragile_days=fragile_days,
        long_day=long_day,
        key_day=key_day,
        planning_decision=planning_decision,
        zones=zones,
        athlete_level=athlete_level,
        cycle_week=cycle_week,
    )

    validation = validate_week_plan(
        days,
        primary_sport=normalized_sports[0],
        planning_decision=planning_decision,
    )
    if not validation.is_valid:
        logger.warning("Planner validation fallback triggered: %s", ", ".join(issue.code for issue in validation.issues))
        safe_sessions = _build_safe_sessions(normalized_sports=normalized_sports, long_day=long_day, athlete_profile=athlete_profile)
        days = _schedule_sessions(
            sessions=safe_sessions,
            blocked_days=blocked_days,
            fragile_days=fragile_days,
            long_day=long_day,
            key_day=key_day,
            planning_decision=None,
            zones=zones,
            athlete_level=athlete_level,
            cycle_week=cycle_week,
        )

    return {
        "intention_seed": _build_intention_seed(
            sports=normalized_sports,
            long_day=long_day,
            key_day=key_day,
            coach_name=coach_name,
            planning_decision=planning_decision,
        ),
        "planning_context": _planning_context_payload(planning_decision),
        "days": days,
    }


def _build_sessions(
    *,
    normalized_sports: list[str],
    key_day: str,
    long_day: str,
    planning_decision: PlanningDecision | None,
    athlete_profile: AthleteProfileSnapshot | None,
) -> list[PlannedSession]:
    primary_sport = normalized_sports[0]
    support_sports = [sport for sport in normalized_sports[1:] if sport != "rest"]
    mode = planning_decision.planning_mode if planning_decision is not None else "maintain_load"
    key_budget = planning_decision.key_session_count if planning_decision is not None else 2
    long_enabled = planning_decision.long_session if planning_decision is not None else True
    strength_budget = planning_decision.strength_session_count if planning_decision is not None else (1 if "strength" in normalized_sports else 0)
    sessions: list[PlannedSession] = []

    if mode == "injury_protection":
        sessions.append(_session_from_type(primary_sport, _recovery_type(primary_sport), preferred_day=key_day, mode=mode))
        low_impact_supports = [sport for sport in support_sports if sport != "strength"]
        for sport in low_impact_supports[:2]:
            sessions.append(_session_from_type(sport, _support_type(sport, mode), preferred_day=None, mode=mode))
        if strength_budget > 0 and len(sessions) < 3:
            sessions.append(_session_from_type("strength", "mobility", preferred_day=None, mode=mode))
        elif "strength" in normalized_sports and not low_impact_supports and len(sessions) < 3:
            sessions.append(_session_from_type("strength", "mobility", preferred_day=None, mode=mode))
        return sessions[:3]

    key_types = _key_types_for_mode(primary_sport, mode)
    quality_budget = min(key_budget, len(key_types))
    if long_enabled and get_sport_planning_config(primary_sport).supports_long_session:
        quality_budget = max(1, quality_budget - 1)
    secondary_key_day = _secondary_key_day(key_day=key_day, long_day=long_day)
    for index in range(quality_budget):
        preferred_day = key_day if index == 0 else secondary_key_day
        sessions.append(_session_from_type(primary_sport, key_types[index], preferred_day=preferred_day, mode=mode))

    if long_enabled and get_sport_planning_config(primary_sport).supports_long_session:
        sessions.append(_session_from_type(primary_sport, "long", preferred_day=long_day, mode=mode))

    sessions.append(_session_from_type(primary_sport, _easy_type(primary_sport), preferred_day=None, mode=mode))

    support_limit = 2 if mode in {"increase_load", "maintain_load"} else 1
    for sport in support_sports[:support_limit]:
        sessions.append(_session_from_type(sport, _support_type(sport, mode), preferred_day=None, mode=mode))

    if "strength" not in normalized_sports and strength_budget > 0:
        for index in range(strength_budget):
            sessions.append(
                _session_from_type(
                    "strength",
                    "general" if index == 0 and mode not in {"deload", "restart_consistency"} else "core",
                    preferred_day=None,
                    mode=mode,
                )
            )
    elif "strength" in normalized_sports:
        for index in range(max(0, strength_budget - 1)):
            sessions.append(_session_from_type("strength", "core" if index == 0 else "mobility", preferred_day=None, mode=mode))

    if athlete_profile is not None and "pool_access" in athlete_profile.equipment and "swimming" not in normalized_sports and mode in {"increase_load", "maintain_load"}:
        sessions.append(_session_from_type("swimming", "technique", preferred_day=None, mode="tactical_adjustment"))

    return sessions[:6]


def _build_safe_sessions(
    *,
    normalized_sports: list[str],
    long_day: str,
    athlete_profile: AthleteProfileSnapshot | None,
) -> list[PlannedSession]:
    primary_sport = normalized_sports[0]
    sessions = [
        _session_from_type(primary_sport, _easy_type(primary_sport), preferred_day="wednesday", mode="maintain_load"),
        _session_from_type(primary_sport, "long" if get_sport_planning_config(primary_sport).supports_long_session else _easy_type(primary_sport), preferred_day=long_day, mode="reduce_load"),
    ]
    if athlete_profile is not None and "strength" in athlete_profile.primary_sports:
        sessions.append(_session_from_type("strength", "core", preferred_day="monday", mode="maintain_load"))
    return sessions


def _schedule_sessions(
    *,
    sessions: list[PlannedSession],
    blocked_days: set[str],
    fragile_days: set[str],
    long_day: str,
    key_day: str,
    planning_decision: PlanningDecision | None,
    zones: AthleteZones | None = None,
    athlete_level: str = "intermediate",
    cycle_week: int = 1,
) -> list[dict]:
    days: dict[str, dict] = {
        day: _rest_day(day, flexible=day in fragile_days or day in blocked_days)
        for day in DAY_KEYS
    }
    occupied_days = set(blocked_days)

    for session in sessions:
        target_day = _pick_day_for_session(
            session=session,
            occupied_days=occupied_days,
            blocked_days=blocked_days,
            fragile_days=fragile_days,
            long_day=long_day,
            key_day=key_day,
        )
        occupied_days.add(target_day)
        days[target_day] = _session_day(
            target_day, session,
            planning_decision=planning_decision,
            zones=zones,
            athlete_level=athlete_level,
            cycle_week=cycle_week,
        )

    # Check for multisport interference and swap if needed
    day_list = [days[day] for day in DAY_KEYS]
    _resolve_interference(day_list)

    return day_list


def _resolve_interference(day_list: list[dict]) -> None:
    """Swap sessions to resolve adjacent-day interference conflicts."""
    from fitmas.domain.planning.interference import check_adjacent_conflicts

    conflicts = check_adjacent_conflicts(day_list)
    if not conflicts:
        return

    for session_a, session_b, rule in conflicts:
        if rule.level != "avoid":
            continue
        # Try to find a rest/easy day to swap session_b with
        for i, day in enumerate(day_list):
            if day.get("sport_type") == "rest" or day.get("intensity") == "easy":
                # Don't swap if it creates a new conflict
                idx_b = day_list.index(session_b)
                if idx_b == i:
                    continue
                # Swap content
                for field in ("sport_type", "session_type", "session_title", "session_goal",
                              "session_description", "duration_min", "intensity", "load_score",
                              "priority", "nutrition_focus", "flexibility"):
                    val_b = session_b.get(field)
                    val_rest = day.get(field)
                    day[field] = val_b
                    session_b[field] = val_rest
                break  # one swap per conflict


def _extract_days(text: str, keywords: tuple[str, ...]) -> set[str]:
    matches: set[str] = set()
    for day, aliases in DAY_SYNONYMS.items():
        for alias in aliases:
            if alias not in text:
                continue
            window_start = max(0, text.index(alias) - 24)
            window_end = min(len(text), text.index(alias) + 24)
            window = text[window_start:window_end]
            if any(keyword in window for keyword in keywords):
                matches.add(day)
                break
    return matches


def _extract_long_day(text: str, blocked_days: set[str]) -> str:
    for segment in re.split(r"[.!?\n]+", text):
        segment = segment.strip()
        if not segment or ("long" not in segment and "sortie longue" not in segment):
            continue
        for day, aliases in DAY_SYNONYMS.items():
            if day in blocked_days:
                continue
            if any(alias in segment for alias in aliases):
                return day
    for fallback in ("sunday", "saturday", "friday"):
        if fallback not in blocked_days:
            return fallback
    return "sunday"


def _pick_key_day(blocked_days: set[str], fragile_days: set[str], long_day: str) -> str:
    for candidate in ("thursday", "wednesday", "tuesday", "friday"):
        if candidate in blocked_days or candidate in fragile_days or candidate == long_day:
            continue
        if abs(DAY_KEYS.index(candidate) - DAY_KEYS.index(long_day)) == 1:
            continue
        return candidate
    return "wednesday"


def _secondary_key_day(*, key_day: str, long_day: str) -> str | None:
    for candidate in ("tuesday", "thursday", "wednesday", "friday", "monday"):
        if candidate in {key_day, long_day}:
            continue
        if abs(DAY_KEYS.index(candidate) - DAY_KEYS.index(key_day)) <= 1:
            continue
        if abs(DAY_KEYS.index(candidate) - DAY_KEYS.index(long_day)) <= 1:
            continue
        return candidate
    return None


def _pick_day_for_session(
    *,
    session: PlannedSession,
    occupied_days: set[str],
    blocked_days: set[str],
    fragile_days: set[str],
    long_day: str,
    key_day: str,
) -> str:
    if session.preferred_day and session.preferred_day not in occupied_days and session.preferred_day not in blocked_days:
        return session.preferred_day

    if session.intensity == "easy":
        preferred_order = list(fragile_days) + ["monday", "wednesday", "friday", "saturday", "sunday", "tuesday", "thursday"]
    else:
        preferred_order = ["tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "monday"]

    for day in preferred_order:
        if day in blocked_days or day in occupied_days:
            continue
        if session.intensity == "hard" and _is_adjacent(day, long_day, key_day, occupied_days):
            continue
        return day

    for day in DAY_KEYS:
        if day not in occupied_days and day not in blocked_days:
            return day
    return "monday"


def _is_adjacent(day: str, long_day: str, key_day: str, occupied_days: set[str]) -> bool:
    index = DAY_KEYS.index(day)
    for other in (long_day, key_day):
        other_index = DAY_KEYS.index(other)
        if abs(index - other_index) == 1 and other in occupied_days:
            return True
    return False


def _session_from_type(
    sport_type: str,
    session_type: str,
    *,
    preferred_day: str | None,
    mode: str,
) -> PlannedSession:
    template = select_session_template(sport_type=sport_type, session_type=session_type)
    sport_config = get_sport_planning_config(sport_type)
    duration = int(round(template.default_duration_min * _duration_multiplier(mode, session_type=session_type)))
    duration = max(sport_config.min_session_duration_min, min(sport_config.max_session_duration_min, duration))
    intensity = template.intensity
    load_score = template.load_score
    priority = _priority_for_template(template.session_type, template.load_score)

    if mode in {"reduce_load", "deload", "restart_consistency"} and intensity == "hard":
        intensity = "moderate"
        load_score = max(2, load_score - 1)
    if mode == "injury_protection":
        intensity = "easy"
        load_score = 1
        priority = "Protection"
    if mode == "tactical_adjustment" and intensity == "hard":
        priority = "Ajustable"
    if mode == "restart_consistency":
        priority = "Reprise cadrée" if intensity != "easy" else "Support"

    return PlannedSession(
        sport_type=sport_type,
        session_type=session_type,
        duration_min=duration,
        intensity=intensity,
        load_score=load_score,
        priority=priority,
        preferred_day=preferred_day,
    )


def _duration_multiplier(mode: str, *, session_type: str) -> float:
    if mode == "increase_load":
        return 1.1 if session_type != "recovery" else 1.0
    if mode == "maintain_load":
        return 1.0
    if mode == "reduce_load":
        return 0.85
    if mode == "deload":
        return 0.75
    if mode == "restart_consistency":
        return 0.8
    if mode == "tactical_adjustment":
        return 0.9
    if mode == "injury_protection":
        return 0.65
    return 1.0


def _key_types_for_mode(primary_sport: str, mode: str) -> list[str]:
    progressive = {
        "running": ["intervals", "tempo", "fartlek"],
        "cycling": ["intervals", "sweet_spot"],
        "swimming": ["css", "endurance_sets"],
        "climbing": ["bouldering", "technique"],
        "strength": ["general", "core"],
    }
    conservative = {
        "running": ["fartlek", "tempo"],
        "cycling": ["sweet_spot", "endurance"],
        "swimming": ["endurance_sets", "technique"],
        "climbing": ["technique"],
        "strength": ["general"],
    }
    protected = {
        "running": ["easy"],
        "cycling": ["endurance"],
        "swimming": ["technique"],
        "climbing": ["technique"],
        "strength": ["mobility"],
    }
    if mode in {"injury_protection", "tactical_adjustment"}:
        return protected.get(primary_sport, ["easy"])
    if mode == "restart_consistency":
        return conservative.get(primary_sport, ["easy"])
    if mode in {"reduce_load", "deload"}:
        return conservative.get(primary_sport, ["easy"])
    return progressive.get(primary_sport, ["easy"])


def _easy_type(sport_type: str) -> str:
    mapping = {
        "running": "easy",
        "cycling": "recovery",
        "swimming": "technique",
        "climbing": "technique",
        "strength": "core",
    }
    return mapping.get(sport_type, "easy")


def _recovery_type(sport_type: str) -> str:
    mapping = {
        "running": "recovery",
        "cycling": "recovery",
        "swimming": "recovery",
        "climbing": "technique",
        "strength": "mobility",
    }
    return mapping.get(sport_type, "recovery")


def _support_type(sport_type: str, mode: str) -> str:
    if sport_type == "cycling":
        return "recovery" if mode in {"deload", "reduce_load", "restart_consistency"} else "endurance"
    if sport_type == "swimming":
        return "technique"
    if sport_type == "strength":
        return "core"
    if sport_type == "climbing":
        return "technique"
    return _easy_type(sport_type)


def _priority_for_template(session_type: str, load_score: int) -> str:
    if session_type == "long":
        return "Repère fort"
    if load_score >= 3:
        return "Séance clé"
    if session_type in {"recovery", "mobility"}:
        return "Récupération active"
    return "Support"


def _planning_context_payload(planning_decision: PlanningDecision | None) -> dict | None:
    if planning_decision is None:
        return None
    return {
        "planning_mode": planning_decision.planning_mode,
        "weekly_target_tss": planning_decision.weekly_target_tss,
        "key_session_count": planning_decision.key_session_count,
        "strength_session_count": planning_decision.strength_session_count,
        "long_session": planning_decision.long_session,
        "rationale": list(planning_decision.rationale),
        "adaptations": list(planning_decision.adaptations),
    }


def _build_intention_seed(
    *,
    sports: list[str],
    long_day: str,
    key_day: str,
    coach_name: str,
    planning_decision: PlanningDecision | None,
) -> str:
    sports_text = ", ".join(_sport_label(sport) for sport in sports[:3])
    if planning_decision is None:
        return (
            f"{coach_name} doit poser une semaine multisport lisible : bloc clé vers "
            f"{DAY_LABELS[key_day].lower()}, repère long vers {DAY_LABELS[long_day].lower()}, "
            f"et assez d'air pour tenir {sports_text} sans rigidifier la semaine."
        )
    return (
        f"{coach_name} pose une semaine {planning_decision.planning_mode} avec cible {int(planning_decision.weekly_target_tss)} TSS. "
        f"Bloc clé vers {DAY_LABELS[key_day].lower()}, repère long vers {DAY_LABELS[long_day].lower()} si pertinent, "
        f"et assez d'air pour tenir {sports_text}. Raisons: {'; '.join(planning_decision.rationale[:2])}."
    )


def _rest_day(day: str, *, flexible: bool) -> dict:
    return {
        "day": day,
        "label": DAY_LABELS[day],
        "sport_type": "rest",
        "session_type": "rest",
        "session_title": "Journée flexible",
        "session_goal": "Laisser de l'air à la semaine et garder de la marge.",
        "session_note": "On ne force rien ici. La semaine doit rester respirable.",
        "session_description": "",
        "duration_min": None,
        "intensity": "easy",
        "load_score": 0,
        "priority": "Souplesse",
        "nutrition_focus": "Rester simple et régulier. Pas besoin d'en faire trop.",
        "flexibility": "flexible" if flexible else "stable",
        "completion_status": "planned",
        "change_notes": [],
        "watch_items": [("Charge globale", "FitMAS garde surtout de la marge pour la suite.")],
    }


def _session_day(
    day: str,
    session: PlannedSession,
    *,
    planning_decision: PlanningDecision | None,
    zones: AthleteZones | None = None,
    athlete_level: str = "intermediate",
    cycle_week: int = 1,
) -> dict:
    template = select_session_template(sport_type=session.sport_type, session_type=session.session_type)
    return {
        "day": day,
        "label": DAY_LABELS[day],
        "sport_type": session.sport_type,
        "session_type": session.session_type,
        "session_title": f"{template.title} {session.duration_min}min",
        "session_goal": template.goal,
        "session_note": _session_note(session, planning_decision=planning_decision),
        "session_description": render_session_description(
            template,
            duration_min=session.duration_min,
            zones=zones,
            athlete_level=athlete_level,
            cycle_week=cycle_week,
        ),
        "duration_min": session.duration_min,
        "intensity": session.intensity,
        "load_score": session.load_score,
        "priority": session.priority,
        "nutrition_focus": _nutrition_copy(session),
        "flexibility": "flexible" if session.intensity == "easy" else "stable",
        "completion_status": "planned",
        "change_notes": [],
        "watch_items": [(template.watch_title, template.watch_detail)],
    }


def _session_note(session: PlannedSession, *, planning_decision: PlanningDecision | None) -> str:
    if planning_decision is None:
        if session.priority == "Séance clé":
            return "Bloc principal de la semaine. Il doit compter sans casser le reste."
        if session.priority == "Repère fort":
            return "Repère utile pour lire l'endurance et la régularité."
        return "Séance utile mais déplaçable si la vraie vie bouge."
    if planning_decision.planning_mode == "deload":
        return "Semaine allégée. On garde le geste sans chercher la performance."
    if planning_decision.planning_mode == "injury_protection":
        return "Protection prioritaire. Tout doit rester propre et tenable."
    if planning_decision.planning_mode == "restart_consistency":
        return "Relance cadrée. On repart plus simple pour reconstruire de la régularité."
    from fitmas.domain.athlete.load_projection import planning_mode_label_fr
    mode_label = planning_mode_label_fr(planning_decision.planning_mode)
    if session.priority == "Séance clé":
        return f"Semaine {mode_label.lower()}. Ce bloc porte le stimulus principal."
    return f"Semaine {mode_label.lower()}. On garde de la marge autour."


def _nutrition_copy(session: PlannedSession) -> str:
    if session.intensity == "hard":
        return "Prévois quelque chose avant la séance, puis une récup simple derrière."
    if session.sport_type in {"cycling", "running"} and session.duration_min >= 70:
        return "Ne pars pas à vide. Anticipe un peu avant puis remets quelque chose après."
    return "Rester simple. Le but est surtout de soutenir la régularité."


def _resolve_athlete_level(profile: AthleteProfileSnapshot | None, primary_sport: str) -> str:
    if profile is None:
        return "intermediate"
    return profile.level_by_sport.get(primary_sport, "intermediate")


def _sport_label(sport: str) -> str:
    labels = {
        "running": "course",
        "cycling": "vélo",
        "swimming": "natation",
        "climbing": "escalade",
        "strength": "renfo",
        "rest": "repos",
    }
    return labels.get(sport, sport)
