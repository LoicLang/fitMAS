from __future__ import annotations

import re
from dataclasses import dataclass

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
) -> dict:
    normalized_sports = normalize_sports(sports)
    notes_blob = " ".join([weekly_structure_notes, *constraints]).lower()

    blocked_days = _extract_days(notes_blob, ("bloque", "bloqué", "indispo", "pas dispo", "jamais"))
    fragile_days = _extract_days(notes_blob, ("fragile", "leger", "léger", "light", "souple", "doux"))
    long_day = _extract_long_day(notes_blob, blocked_days)
    key_day = _pick_key_day(blocked_days, fragile_days, long_day)

    sessions = _build_sessions(normalized_sports, key_day, long_day)
    days: dict[str, dict] = {
        day: _rest_day(day, flexible=day in fragile_days or day in blocked_days)
        for day in DAY_KEYS
    }

    occupied_days = {day for day in blocked_days}
    for day in blocked_days:
        days[day] = _rest_day(day, flexible=True)

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
        days[target_day] = _session_day(target_day, session)

    ordered_days = [days[day] for day in DAY_KEYS]
    intention_seed = _build_intention_seed(normalized_sports, long_day, key_day, coach_name)
    return {"intention_seed": intention_seed, "days": ordered_days}


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


def _build_sessions(sports: list[str], key_day: str, long_day: str) -> list[PlannedSession]:
    main_sport = sports[0]
    support_sports = [sport for sport in sports[1:] if sport != "rest"]
    sessions = [
        PlannedSession(
            sport_type=main_sport,
            session_type="quality" if main_sport != "climbing" else "project",
            duration_min=60 if main_sport in {"running", "cycling"} else 50,
            intensity="hard",
            load_score=3,
            priority="Seance cle",
            preferred_day=key_day,
        ),
        PlannedSession(
            sport_type=main_sport,
            session_type="long",
            duration_min=90 if main_sport == "cycling" else 75 if main_sport == "running" else 60,
            intensity="moderate",
            load_score=3,
            priority="Repere fort",
            preferred_day=long_day,
        ),
    ]

    for sport in support_sports:
        sessions.append(_support_session(sport))

    if main_sport != "swimming":
        sessions.append(
            PlannedSession(
                sport_type="swimming" if "swimming" in sports else main_sport,
                session_type="easy" if "swimming" not in sports else "technique",
                duration_min=40,
                intensity="easy",
                load_score=1,
                priority="Recuperation active",
            )
        )
    else:
        sessions.append(
            PlannedSession(
                sport_type=main_sport,
                session_type="easy",
                duration_min=35,
                intensity="easy",
                load_score=1,
                priority="Clarte",
            )
        )

    return sessions[:6]


def _support_session(sport: str) -> PlannedSession:
    defaults = {
        "cycling": PlannedSession("cycling", "endurance", 75, "moderate", 2, "Endurance"),
        "swimming": PlannedSession("swimming", "technique", 45, "easy", 1, "Technique"),
        "climbing": PlannedSession("climbing", "volume", 90, "moderate", 2, "Charge utile"),
        "strength": PlannedSession("strength", "support", 35, "easy", 1, "Support"),
        "running": PlannedSession("running", "easy", 45, "easy", 1, "Clarte"),
    }
    return defaults.get(sport, PlannedSession(sport, "easy", 45, "easy", 1, "Clarte"))


def _pick_day_for_session(
    *,
    session: PlannedSession,
    occupied_days: set[str],
    blocked_days: set[str],
    fragile_days: set[str],
    long_day: str,
    key_day: str,
) -> str:
    if session.preferred_day and session.preferred_day not in occupied_days:
        return session.preferred_day

    if session.intensity == "easy":
        preferred_order = list(fragile_days) + ["monday", "wednesday", "friday", "saturday", "sunday"]
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


def _build_intention_seed(sports: list[str], long_day: str, key_day: str, coach_name: str) -> str:
    sports_text = ", ".join(_sport_label(sport) for sport in sports[:3])
    return (
        f"{coach_name} doit poser une semaine multisport lisible: bloc cle vers "
        f"{DAY_LABELS[key_day].lower()}, repere long vers {DAY_LABELS[long_day].lower()}, "
        f"et assez d'air pour tenir {sports_text} sans rigidifier la semaine."
    )


def _rest_day(day: str, *, flexible: bool) -> dict:
    return {
        "day": day,
        "label": DAY_LABELS[day],
        "sport_type": "rest",
        "session_type": "rest",
        "session_title": "Journee flexible",
        "session_goal": "Laisser de l'air a la semaine et garder de la marge.",
        "session_note": "On ne force rien ici. La semaine doit rester respirable.",
        "duration_min": None,
        "intensity": "easy",
        "load_score": 0,
        "priority": "Souplesse",
        "nutrition_focus": "Rester simple et regulier. Pas besoin d'en faire trop.",
        "flexibility": "flexible" if flexible else "stable",
        "completion_status": "planned",
        "change_notes": [],
        "watch_items": [("Charge globale", "FitMAS garde surtout de la marge pour la suite.")],
    }


def _session_day(day: str, session: PlannedSession) -> dict:
    title, goal = _session_copy(session)
    return {
        "day": day,
        "label": DAY_LABELS[day],
        "sport_type": session.sport_type,
        "session_type": session.session_type,
        "session_title": title,
        "session_goal": goal,
        "session_note": "",
        "duration_min": session.duration_min,
        "intensity": session.intensity,
        "load_score": session.load_score,
        "priority": session.priority,
        "nutrition_focus": _nutrition_copy(session),
        "flexibility": "flexible" if session.intensity == "easy" else "stable",
        "completion_status": "planned",
        "change_notes": [],
        "watch_items": [_watch_copy(session)],
    }


def _session_copy(session: PlannedSession) -> tuple[str, str]:
    sport = _sport_label(session.sport_type)
    templates = {
        ("running", "quality"): ("Course qualite", "Poser un vrai stimulus sans casser le reste de la semaine."),
        ("running", "long"): ("Sortie longue course", "Construire un repere durable et propre."),
        ("running", "easy"): ("Footing facile", "Faire du volume simple sans bruit."),
        ("cycling", "quality"): ("Velo avec bloc soutenu", "Travailler la puissance utile sans eparpiller la semaine."),
        ("cycling", "long"): ("Sortie longue velo", "Mettre une vraie base d'endurance dans la semaine."),
        ("cycling", "endurance"): ("Sortie velo endurance", "Ajouter du volume propre et lisible."),
        ("swimming", "technique"): ("Natation technique", "Garder de la precision sans ajouter trop de charge."),
        ("swimming", "easy"): ("Natation fluide", "Bouger et recuperer sans alourdir la semaine."),
        ("climbing", "project"): ("Escalade bloc fort", "Mettre un vrai effort de grimpe sans tout durcir autour."),
        ("climbing", "volume"): ("Escalade volume", "Prendre de la grimpe utile et lire la fatigue ensuite."),
        ("strength", "support"): ("Renfo support", "Stabiliser sans prendre toute la place."),
    }
    return templates.get((session.sport_type, session.session_type), (f"Seance {sport}", f"Poser une seance {sport} propre et tenable."))


def _nutrition_copy(session: PlannedSession) -> str:
    if session.intensity == "hard":
        return "Prevois quelque chose avant la seance, puis une recup simple derriere."
    if session.sport_type in {"cycling", "running"} and session.duration_min and session.duration_min >= 70:
        return "Ne pars pas a vide. Anticipe un peu avant puis remets quelque chose apres."
    return "Rester simple. Le but est surtout de soutenir la regularite."


def _watch_copy(session: PlannedSession) -> tuple[str, str]:
    if session.sport_type == "climbing":
        return ("Avant-bras et fraicheur", "La grimpe peut charger plus que ce qu'elle raconte au planning.")
    if session.intensity == "hard":
        return ("Recuperation", "Le lendemain dira si la dose etait juste.")
    return ("Regulier", "FitMAS lit surtout si la semaine reste tenable.")


def _sport_label(sport: str) -> str:
    labels = {
        "running": "course",
        "cycling": "velo",
        "swimming": "natation",
        "climbing": "escalade",
        "strength": "renfo",
        "rest": "repos",
    }
    return labels.get(sport, sport)
