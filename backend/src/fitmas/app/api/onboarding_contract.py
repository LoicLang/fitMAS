from __future__ import annotations

from dataclasses import dataclass

from fitmas.domain.coaching.calibration_status import build_onboarding_unknowns


@dataclass(frozen=True, slots=True)
class CoachPresetDefinition:
    style: str
    relationship: str
    do: str
    dont: str
    soul: str
    label: str


COACH_PRESETS: dict[str, CoachPresetDefinition] = {
    "direct": CoachPresetDefinition(
        style="direct",
        relationship="exigeant, lucide, sans detour",
        do="dire les choses clairement, recadrer vite, proteger l'essentiel",
        dont="phrases creuses, compliments automatiques, theatre",
        soul="calme, net, concret, sans faux enthousiasme",
        label="Direct",
    ),
    "calm": CoachPresetDefinition(
        style="calm",
        relationship="calme, solide, rassurant sans mollesse",
        do="poser les choses proprement, calmer sans endormir, garder du discernement",
        dont="pression inutile, drama, surcharge verbale",
        soul="stable, sobre, respirable, precis",
        label="Calme",
    ),
    "analytical": CoachPresetDefinition(
        style="data_driven",
        relationship="factuel, structure, oriente progression",
        do="expliquer la logique, montrer les arbitrages, rester compréhensible",
        dont="noyer en jargon, devenir froid, multiplier les chiffres gratuits",
        soul="clair, methodique, orienté performance utile",
        label="Analytique",
    ),
    "demanding": CoachPresetDefinition(
        style="tough_friend",
        relationship="exigeant mais juste, sans culpabiliser",
        do="tenir le cap, recadrer franchement, proteger la discipline",
        dont="humilier, surjouer, pousser au mauvais moment",
        soul="dense, tendu juste ce qu'il faut, jamais brutal",
        label="Exigeant",
    ),
    "protective": CoachPresetDefinition(
        style="protective",
        relationship="protecteur, intelligent, garde-fou avant tout",
        do="sentir quand alleger, prioriser la durabilite, proteger la cohérence",
        dont="forcer une surcharge artificielle, ignorer les signaux faibles, culpabiliser",
        soul="humain, prudent, pertinent, jamais mou",
        label="Protecteur",
    ),
}

_LEGACY_PRESET_ALIASES = {
    "direct": "direct",
    "calme": "calm",
    "calm": "calm",
    "data": "analytical",
    "data_driven": "analytical",
    "analytique": "analytical",
    "analytical": "analytical",
    "tough": "demanding",
    "tough_friend": "demanding",
    "exigeant": "demanding",
    "demanding": "demanding",
    "protecteur": "protective",
    "protective": "protective",
}


def normalize_coach_preset(raw_value: str | None) -> str:
    key = (raw_value or "").strip().lower()
    if not key:
        return "direct"
    return _LEGACY_PRESET_ALIASES.get(key, "direct")


def build_coach_profile(payload: dict) -> dict[str, str]:
    preset_key = normalize_coach_preset(payload.get("coach_preset") or payload.get("coach_style"))
    preset = COACH_PRESETS[preset_key]
    adjustment = str(payload.get("coach_adjustment_notes") or "").strip()
    explicit_soul = str(payload.get("coach_soul") or "").strip()
    soul_parts = [preset.soul]
    if explicit_soul:
        soul_parts.append(explicit_soul)
    if adjustment:
        soul_parts.append(f"Ajustement voix: {adjustment}")
    return {
        "coach_preset": preset_key,
        "coach_name": str(payload.get("coach_name") or "FitMAS").strip() or "FitMAS",
        "coach_style": str(payload.get("coach_style") or preset.style).strip() or preset.style,
        "coach_relationship": str(payload.get("coach_relationship") or preset.relationship).strip() or preset.relationship,
        "coach_do": str(payload.get("coach_do") or preset.do).strip() or preset.do,
        "coach_dont": str(payload.get("coach_dont") or preset.dont).strip() or preset.dont,
        "coach_soul": " | ".join(part for part in soul_parts if part),
        "coach_preset_label": preset.label,
    }


def build_goal_summary(payload: dict) -> str:
    base = str(payload.get("primary_objective") or "").strip()
    goal_context = str(payload.get("goal_context") or "").strip()
    if not goal_context:
        return base
    if not base:
        return goal_context
    return f"{base} — {goal_context}"


def build_onboarding_setup_preview(payload: dict) -> list[str]:
    coach = build_coach_profile(payload)
    lines = [
        f"Cap: {build_goal_summary(payload) or 'cap à préciser'}",
        f"Semaine réelle: {str(payload.get('weekly_structure_notes') or '').strip() or 'matière encore légère'}",
        f"État actuel: {str(payload.get('current_state_notes') or '').strip() or 'à affiner sur les prochaines séances'}",
        f"Ce que je protégerai: {build_protected_focus(payload)}",
        f"Coach: {coach['coach_name']} · preset {coach['coach_preset_label'].lower()}",
    ]
    unknowns = build_onboarding_unknowns(payload)
    if unknowns:
        lines.append(f"À clarifier ensuite: {unknowns[0]}")
    return lines


def build_protected_focus(payload: dict) -> str:
    week = str(payload.get("weekly_structure_notes") or "").lower()
    constraints = [str(value).lower() for value in payload.get("constraints", [])]
    joined_constraints = " ".join(constraints)
    joined = f"{week} {joined_constraints}"
    if "sortie longue" in joined or "long" in joined:
        return "le créneau long et les jours fiables"
    if "matin" in joined or "soir" in joined:
        return "les créneaux les plus tenables dans ta vraie semaine"
    if constraints:
        return constraints[0]
    return "la régularité et une semaine tenable"
