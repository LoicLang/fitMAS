from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from fitmas.core import orm as s

DAY_ALIASES = {
    "monday": ("lundi", "monday"),
    "tuesday": ("mardi", "tuesday"),
    "wednesday": ("mercredi", "wednesday"),
    "thursday": ("jeudi", "thursday"),
    "friday": ("vendredi", "friday"),
    "saturday": ("samedi", "saturday"),
    "sunday": ("dimanche", "sunday"),
}

TIME_PREFERENCE_KEYWORDS = {
    "morning": ("matin", "morning", "7h", "8h", "am"),
    "midday": ("midi", "midday", "noon"),
    "evening": ("soir", "evening", "18h", "19h", "20h", "pm"),
}

EQUIPMENT_KEYWORDS = {
    "home_trainer": ("home trainer", "hometrainer"),
    "hr_monitor": ("cardio", "ceinture cardio", "capteur cardio", "heart rate"),
    "gps_watch": ("montre gps", "garmin", "coros", "suunto", "polar"),
    "pool_access": ("piscine", "bassin", "ligne d'eau", "nage"),
    "gym_access": ("salle", "gym", "musculation"),
    "weights": ("halteres", "haltères", "kettlebell", "barre", "poids"),
    "climbing_gym": ("bloc", "voie", "mur", "salle d'escalade"),
}

LEVEL_KEYWORDS = {
    "advanced": ("avance", "avancé", "advanced", "expert", "confirme", "confirmé"),
    "intermediate": ("intermediaire", "intermédiaire", "intermediate", "regulier", "régulier"),
    "beginner": ("debutant", "débutant", "beginner", "novice", "reprise"),
}


@dataclass(frozen=True, slots=True)
class AthleteProfileSnapshot:
    user_id: int
    primary_sports: tuple[str, ...]
    primary_sport: str
    level_by_sport: dict[str, str]
    goals: tuple[str, ...]
    weekly_availability: dict[str, tuple[str, ...]]
    equipment: tuple[str, ...]
    constraints: tuple[str, ...]
    preferences: tuple[str, ...]
    preferred_training_times: tuple[str, ...]
    coach_tone: str
    coach_style_notes: str
    athlete_identity_summary: str
    onboarding_completed: bool


def build_athlete_profile(
    user: s.User,
    *,
    facts: Sequence[object] | None = None,
) -> AthleteProfileSnapshot:
    active_facts = [fact for fact in (facts or []) if _is_active(fact)]
    primary_sports = tuple(
        sport.sport_type
        for sport in sorted(
            [sport for sport in user.sports if _is_active(sport)],
            key=lambda sport: (sport.priority_rank, sport.id or 0),
        )
    ) or ("running",)
    level_by_sport = {
        sport.sport_type: normalize_sport_level(sport.level_note)
        for sport in user.sports
        if _is_active(sport)
    } or {"running": "unknown"}
    constraints = tuple(_dedupe(_collect_texts(user.constraints, active_facts, categories={"constraint", "health"})))
    preferences = tuple(_dedupe(_collect_texts(user.preferences, active_facts, categories={"preference"})))
    goals = tuple(_dedupe(_collect_goals(user, active_facts)))
    weekly_availability = extract_weekly_availability(user.weekly_structure_notes, active_facts)
    preferred_training_times = tuple(_detect_training_times([user.weekly_structure_notes, *constraints, *preferences]))
    equipment = tuple(
        _detect_equipment(
            [
                user.weekly_structure_notes,
                *constraints,
                *preferences,
                *(fact.value for fact in active_facts),
            ]
        )
    )
    coach_tone = (user.coach_style or user.coaching_style or "direct").strip() or "direct"
    coach_style_notes = build_coach_style_notes(user)
    athlete_identity_summary = summarize_athlete_identity(
        name=user.name,
        sports=primary_sports,
        goals=goals,
        constraints=constraints,
        coach_tone=coach_tone,
    )
    return AthleteProfileSnapshot(
        user_id=user.id,
        primary_sports=primary_sports,
        primary_sport=primary_sports[0],
        level_by_sport=level_by_sport,
        goals=goals,
        weekly_availability=weekly_availability,
        equipment=equipment,
        constraints=constraints,
        preferences=preferences,
        preferred_training_times=preferred_training_times,
        coach_tone=coach_tone,
        coach_style_notes=coach_style_notes,
        athlete_identity_summary=athlete_identity_summary,
        onboarding_completed=user.onboarding_status == "completed",
    )


def normalize_sport_level(raw_level: str | None) -> str:
    text = (raw_level or "").strip().lower()
    if not text:
        return "unknown"
    for level, keywords in LEVEL_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return level
    return "unknown"


def extract_weekly_availability(
    weekly_structure_notes: str,
    facts: Sequence[object],
) -> dict[str, tuple[str, ...]]:
    snippets: dict[str, list[str]] = {}
    sources = [weekly_structure_notes, *(fact.value for fact in facts if fact.category in {"availability", "schedule"})]
    for raw_source in sources:
        for chunk in _split_note_chunks(raw_source):
            normalized = chunk.lower()
            for day_key, aliases in DAY_ALIASES.items():
                if not any(alias in normalized for alias in aliases):
                    continue
                snippets.setdefault(day_key, []).append(chunk)
                break
    return {day_key: tuple(_dedupe(values)) for day_key, values in snippets.items()}


def build_coach_style_notes(user: s.User) -> str:
    parts = [
        user.coach_relationship.strip(),
        user.coach_do.strip(),
        user.coach_dont.strip(),
        user.coach_soul.strip(),
    ]
    return " | ".join(part for part in parts if part)


def summarize_athlete_identity(
    *,
    name: str,
    sports: Sequence[str],
    goals: Sequence[str],
    constraints: Sequence[str],
    coach_tone: str,
) -> str:
    goal = goals[0] if goals else "continuer a progresser"
    sports_label = ", ".join(sports[:3])
    summary = f"{name} s'entraine surtout en {sports_label} et vise {goal}."
    if constraints:
        summary += f" Vigilance: {constraints[0]}."
    summary += f" Coach attendu: ton {coach_tone}."
    return summary


def _collect_goals(user: s.User, facts: Sequence[object]) -> list[str]:
    values = []
    for candidate in (user.primary_objective, user.objective):
        cleaned = candidate.strip()
        if cleaned:
            values.append(cleaned)
    for fact in facts:
        if fact.category in {"goal", "objective"}:
            cleaned = fact.value.strip()
            if cleaned:
                values.append(cleaned)
    return values or ["continuer a progresser"]


def _collect_texts(
    rows: Iterable[object],
    facts: Sequence[object],
    *,
    categories: set[str],
) -> list[str]:
    values = []
    for row in rows:
        text = getattr(row, "text", "").strip()
        if text:
            values.append(text)
    for fact in facts:
        if fact.category not in categories:
            continue
        cleaned = fact.value.strip()
        if cleaned:
            values.append(cleaned)
    return values


def _detect_training_times(chunks: Iterable[str]) -> list[str]:
    detected: list[str] = []
    for chunk in chunks:
        normalized = chunk.lower()
        for label, keywords in TIME_PREFERENCE_KEYWORDS.items():
            if label in detected:
                continue
            if any(keyword in normalized for keyword in keywords):
                detected.append(label)
    return detected


def _detect_equipment(chunks: Iterable[str]) -> list[str]:
    detected: list[str] = []
    for chunk in chunks:
        normalized = chunk.lower()
        for label, keywords in EQUIPMENT_KEYWORDS.items():
            if label in detected:
                continue
            if any(keyword in normalized for keyword in keywords):
                detected.append(label)
    return detected


def _split_note_chunks(raw_text: str) -> list[str]:
    return [
        chunk.strip(" -•\t")
        for chunk in raw_text.replace(";", "\n").replace(".", "\n").splitlines()
        if chunk.strip(" -•\t")
    ]


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(normalized)
    return unique


def _is_active(row: object) -> bool:
    return getattr(row, "active", True) is not False
