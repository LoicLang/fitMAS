from __future__ import annotations


def compute_load_band(
    *,
    sport_type: str,
    session_type: str,
    intensity: str,
    load_score: int,
) -> str:
    sport_key = (sport_type or "").strip().lower()
    type_key = (session_type or "").strip().lower()
    intensity_key = (intensity or "").strip().lower()
    load_value = int(load_score or 0)

    if sport_key == "rest" or type_key in {"rest", "recovery"}:
        return "recovery"
    if type_key == "mobility":
        return "mobility"
    if intensity_key == "hard" or load_value >= 4:
        return "hard"
    if intensity_key == "moderate" or load_value >= 3:
        return "moderate"
    return "easy"
