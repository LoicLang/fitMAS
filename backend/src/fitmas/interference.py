"""Multisport interference matrix.

Checks adjacent-day session pairs for cross-sport fatigue conflicts.
Used at plan generation time and as a post-mutation validation.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class InterferenceRule:
    sport_a: str
    intensity_a: str    # "hard", "any"
    sport_b: str
    intensity_b: str    # "hard", "any"
    level: str          # "none", "mild", "avoid"
    reason: str


# Interference rules: (day N, day N+1) — order matters
RULES: tuple[InterferenceRule, ...] = (
    # Running + Running
    InterferenceRule("running", "hard", "running", "hard", "avoid",
                     "Deux seances running dures consecutives = risque blessure"),
    InterferenceRule("running", "hard", "running", "moderate", "mild",
                     "Enchainer running dur + tempo demande de la fraicheur"),

    # Strength + Running
    InterferenceRule("strength", "hard", "running", "hard", "avoid",
                     "Renfo lourd jambes + fractionne = fatigue musculaire cumulee"),
    InterferenceRule("strength", "moderate", "running", "hard", "mild",
                     "Renfo modere peut impacter le fractionne du lendemain"),

    # Climbing + Strength
    InterferenceRule("climbing", "hard", "strength", "hard", "avoid",
                     "Grimpe dure + renfo haut du corps = surcharge tendons doigts/epaules"),
    InterferenceRule("climbing", "hard", "strength", "moderate", "mild",
                     "Grimpe dure suivie de renfo modere — attention aux doigts"),

    # Cycling + Running
    InterferenceRule("cycling", "hard", "running", "hard", "avoid",
                     "Velo dur + running dur = double charge quadriceps"),

    # Running + Cycling (reverse)
    InterferenceRule("running", "hard", "cycling", "hard", "mild",
                     "Fractionne + velo dur — charge cumule mais groupes musculaires differents"),

    # Swimming is generally low interference
    # No rules needed — swimming doesn't create muscular fatigue for other sports
)


def check_adjacent_conflicts(
    sessions: list[dict],
) -> list[tuple[dict, dict, InterferenceRule]]:
    """Check consecutive session pairs for interference.

    sessions: list of dicts with at least 'sport_type' and 'intensity' keys,
              ordered chronologically.

    Returns list of (session_a, session_b, rule) tuples for conflicts.
    """
    conflicts = []
    for i in range(len(sessions) - 1):
        a = sessions[i]
        b = sessions[i + 1]

        sport_a = (a.get("sport_type") or "").lower()
        sport_b = (b.get("sport_type") or "").lower()
        intensity_a = (a.get("intensity") or "moderate").lower()
        intensity_b = (b.get("intensity") or "moderate").lower()

        if sport_a == "rest" or sport_b == "rest":
            continue

        for rule in RULES:
            if not _matches(sport_a, intensity_a, rule.sport_a, rule.intensity_a):
                continue
            if not _matches(sport_b, intensity_b, rule.sport_b, rule.intensity_b):
                continue
            conflicts.append((a, b, rule))
            break  # one rule per pair

    return conflicts


def _matches(sport: str, intensity: str, rule_sport: str, rule_intensity: str) -> bool:
    """Check if a session matches a rule's sport/intensity pattern."""
    if rule_sport not in sport:
        return False
    if rule_intensity == "any":
        return True
    return intensity == rule_intensity


def format_conflicts_for_prompt(
    conflicts: list[tuple[dict, dict, InterferenceRule]],
) -> str:
    """Format conflicts for LLM prompt injection."""
    if not conflicts:
        return ""
    lines = ["Conflits multisport detectes:"]
    for a, b, rule in conflicts:
        lines.append(
            f"- {a.get('sport_type', '?')} ({a.get('intensity', '?')}) → "
            f"{b.get('sport_type', '?')} ({b.get('intensity', '?')}): "
            f"{rule.level} — {rule.reason}"
        )
    return "\n".join(lines)
