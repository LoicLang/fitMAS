"""Week context — surfaces the planning narrative for the app.

Provides:
- week_summary: prévu vs réalisé with per-session detail
- planning_context: enriched week metadata (readiness, structure, deload countdown)
- next_week_cadrage: S+1 preview (mode, charge cible, structure)
- coach_reading: LLM-generated contextual narrative
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from fitmas.fitness_snapshot import estimate_scheduled_session_tss
from fitmas.load_projection import planning_mode_label_fr

logger = logging.getLogger(__name__)

REST_SPORTS = {"rest", "off"}

_SPORT_LABELS_FR = {
    "running": "Course",
    "cycling": "Vélo",
    "swimming": "Natation",
    "climbing": "Escalade",
    "strength": "Renfo",
    "rest": "Repos",
}


def sport_label_fr(sport: str) -> str:
    return _SPORT_LABELS_FR.get(sport.lower(), sport.capitalize())


# ---------------------------------------------------------------------------
# Week summary (prévu vs réalisé)
# ---------------------------------------------------------------------------


def build_week_summary(
    *,
    today: date,
    scheduled_sessions: list[Any],
    activities: list[Any],
) -> dict[str, Any]:
    """Build a prévu-vs-réalisé summary for the current week."""
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)

    week_sessions = [
        s for s in scheduled_sessions
        if (d := _as_date(_value(s, "scheduled_date"))) is not None
        and week_start <= d <= week_end
    ]
    week_activities = [
        a for a in activities
        if (d := _as_date(_value(a, "started_at") or _value(a, "created_at"))) is not None
        and week_start <= d <= week_end
    ]

    non_rest = [s for s in week_sessions if str(_value(s, "sport_type") or "").lower() not in REST_SPORTS]
    done = [s for s in non_rest if str(_value(s, "completion_status") or "").lower() == "done"]
    skipped = [s for s in non_rest if str(_value(s, "completion_status") or "").lower() in ("skipped", "adapted")]
    planned = [s for s in non_rest if str(_value(s, "completion_status") or "").lower() == "planned"]

    planned_tss = round(sum(estimate_scheduled_session_tss(s) for s in non_rest), 1)
    actual_tss = round(sum(float(_value(a, "tss") or 0.0) for a in week_activities), 1)
    planned_hours = round(sum(float(_value(s, "duration_min") or 0.0) for s in non_rest) / 60.0, 1)
    actual_hours = round(sum(float(_value(a, "duration_min") or 0.0) for a in week_activities) / 60.0, 1)

    session_items = []
    for s in week_sessions:
        sport = str(_value(s, "sport_type") or "").lower()
        status = str(_value(s, "completion_status") or "planned").lower()
        linked = _find_linked_activity(s, week_activities)
        item: dict[str, Any] = {
            "date": (_as_date(_value(s, "scheduled_date")) or today).isoformat(),
            "sport": sport_label_fr(sport),
            "sport_type": sport,
            "title": _value(s, "session_title") or "",
            "planned_duration_min": int(_value(s, "duration_min") or 0),
            "status": status,
        }
        if linked:
            item["actual_duration_min"] = int(float(_value(linked, "duration_min") or 0))
            item["actual_tss"] = round(float(_value(linked, "tss") or 0.0), 1)
        session_items.append(item)

    return {
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "total_sessions": len(non_rest),
        "done": len(done),
        "skipped": len(skipped),
        "remaining": len(planned),
        "completion_pct": round(len(done) / max(len(non_rest), 1) * 100),
        "planned_tss": planned_tss,
        "actual_tss": actual_tss,
        "planned_hours": planned_hours,
        "actual_hours": actual_hours,
        "sessions": session_items,
    }


# ---------------------------------------------------------------------------
# Enriched planning context
# ---------------------------------------------------------------------------


def build_planning_context(
    *,
    planning_decision: Any | None,
    mesocycle_week: int,
    mesocycle_number: int,
    is_deload: bool,
    total_weeks: int = 0,
    readiness: Any | None = None,
    recent_reality: Any | None = None,
) -> dict[str, Any]:
    """Expose the essential planning context for the current week."""
    mode_raw = str(_value(planning_decision, "planning_mode") or "maintain_load")
    deload_in = max(0, 4 - mesocycle_week) if not is_deload else 0

    ctx: dict[str, Any] = {
        "mode": planning_mode_label_fr(mode_raw),
        "mode_key": mode_raw,
        "mesocycle_week": mesocycle_week,
        "mesocycle_number": mesocycle_number,
        "cycle_position": f"{mesocycle_week}/4",
        "is_deload": is_deload,
        "deload_in_weeks": deload_in,
        "total_weeks": total_weeks,
        "target_tss": round(float(_value(planning_decision, "weekly_target_tss") or 0.0), 1),
        "key_sessions": int(_value(planning_decision, "key_session_count") or 0),
        "strength_sessions": int(_value(planning_decision, "strength_session_count") or 0),
        "long_session": bool(_value(planning_decision, "long_session")),
        "adaptations": list(_value(planning_decision, "adaptations") or ()),
        "rationale": list(_value(planning_decision, "rationale") or ()),
    }

    if readiness is not None:
        ctx["readiness"] = {
            "physical": _value(readiness, "physical") or "medium",
            "mental": _value(readiness, "mental") or "medium",
            "logistical": _value(readiness, "logistical") or "clear",
            "injury_risk": _value(readiness, "injury_risk") or "low",
        }
    if recent_reality is not None:
        if isinstance(recent_reality, dict):
            ctx["recent_reality"] = dict(recent_reality)
        elif hasattr(recent_reality, "as_dict"):
            ctx["recent_reality"] = recent_reality.as_dict()

    return ctx


# ---------------------------------------------------------------------------
# Next week cadrage (S+1 preview)
# ---------------------------------------------------------------------------


def build_next_week_cadrage(
    *,
    current_mesocycle_week: int,
    current_planning_mode: str,
    current_target_tss: float,
) -> dict[str, Any]:
    """Preview the next week's cadrage without generating sessions."""
    next_cycle_week = (current_mesocycle_week % 4) + 1
    next_is_deload = next_cycle_week == 4

    if next_is_deload:
        next_mode = "deload"
        tss_factor = 0.65
    elif current_planning_mode in ("deload", "injury_protection", "restart_consistency"):
        next_mode = "maintain_load"
        tss_factor = 1.0
    else:
        next_mode = current_planning_mode
        tss_factor = {"increase_load": 1.05, "maintain_load": 1.0, "reduce_load": 0.9, "restart_consistency": 0.98}.get(current_planning_mode, 1.0)

    next_target_tss = round(current_target_tss * tss_factor, 1)

    _FOCUS_LABELS = {
        1: "Relance",
        2: "Consolidation",
        3: "Pic contrôlé",
        4: "Assimilation",
    }

    return {
        "cycle_week": next_cycle_week,
        "cycle_position": f"{next_cycle_week}/4",
        "is_deload": next_is_deload,
        "mode": planning_mode_label_fr(next_mode),
        "mode_key": next_mode,
        "target_tss": next_target_tss,
        "focus": _FOCUS_LABELS.get(next_cycle_week, "Consolidation"),
    }


# ---------------------------------------------------------------------------
# Coach reading (deterministic fallback)
# ---------------------------------------------------------------------------


def build_deterministic_coach_reading(
    *,
    week_summary: dict[str, Any],
    planning_context: dict[str, Any],
    next_week: dict[str, Any],
    screen: str = "overview",
) -> str:
    """Build a short deterministic coach reading (fallback if LLM unavailable)."""
    mode = planning_context["mode"]
    position = planning_context["cycle_position"]
    done = week_summary["done"]
    total = week_summary["total_sessions"]
    actual_tss = week_summary["actual_tss"]
    target_tss = planning_context["target_tss"]
    deload_in = planning_context["deload_in_weeks"]

    parts = []

    # Position
    if planning_context["is_deload"]:
        parts.append(f"Semaine d'assimilation ({position}).")
    else:
        parts.append(f"Semaine {position}, {mode.lower()}.")

    # Completion
    if total > 0:
        if done == total:
            parts.append(f"{done}/{total} séances faites, semaine bouclée.")
        elif done > 0:
            remaining = total - done
            parts.append(f"{done}/{total} faites, {remaining} restante{'s' if remaining > 1 else ''}.")
        else:
            parts.append(f"Rien encore cette semaine.")

    recent_reality = planning_context.get("recent_reality") or {}
    if planning_context.get("mode_key") == "restart_consistency" and recent_reality:
        confirmed = int(recent_reality.get("confirmed_sessions_7d") or 0)
        planned = int(recent_reality.get("planned_sessions_7d") or 0)
        if planned > 0:
            parts.append(f"Relance après {confirmed}/{planned} séances confirmées sur 7 jours.")

    # Charge
    if target_tss > 0 and actual_tss > 0:
        pct = round(actual_tss / target_tss * 100)
        parts.append(f"Charge : {pct}% de la cible ({int(actual_tss)}/{int(target_tss)} TSS).")

    # Next week
    if screen == "overview" and deload_in > 0:
        parts.append(f"Assimilation dans {deload_in} semaine{'s' if deload_in > 1 else ''}.")
    elif screen == "overview" and deload_in == 0 and not planning_context["is_deload"]:
        parts.append(f"Semaine prochaine : {next_week['focus'].lower()}.")

    return " ".join(parts)


def build_coach_reading_prompt(
    *,
    week_summary: dict[str, Any],
    planning_context: dict[str, Any],
    next_week: dict[str, Any],
    coach_name: str,
    coach_soul: str = "",
    screen: str = "overview",
) -> tuple[str, str]:
    """Build system + prompt for LLM coach reading."""
    system = (
        f"Tu es {coach_name}, coach multisport IA. "
        "Tu tutoies. Tu parles en français. "
        "Tu es clair, court, direct, chaleureux sans cheerleading. "
        "Tu donnes un diagnostic de la semaine en 2-3 phrases maximum. "
        "Pas de bullet points. Pas de chiffres bruts sans contexte. "
        "Parle comme un coach qui regarde le tableau de bord avec l'athlète."
    )
    if coach_soul:
        system += f"\nÂme du coach : {coach_soul}"

    mode = planning_context["mode"]
    position = planning_context["cycle_position"]
    done = week_summary["done"]
    total = week_summary["total_sessions"]
    actual_tss = week_summary["actual_tss"]
    target_tss = planning_context["target_tss"]
    deload_in = planning_context["deload_in_weeks"]
    readiness = planning_context.get("readiness", {})

    prompt_parts = [
        f"Écran : {screen}.",
        f"Semaine {position}, mode {mode}.",
        f"Complétion : {done}/{total} séances.",
        f"Charge : {int(actual_tss)}/{int(target_tss)} TSS.",
    ]
    if readiness:
        prompt_parts.append(f"Readiness : physique {readiness.get('physical', '?')}, mental {readiness.get('mental', '?')}, risque {readiness.get('injury_risk', '?')}.")
    if deload_in > 0:
        prompt_parts.append(f"Assimilation dans {deload_in} semaine(s).")
    else:
        prompt_parts.append(f"Semaine prochaine : {next_week['focus']}.")

    if planning_context.get("adaptations"):
        prompt_parts.append(f"Adaptations : {'; '.join(planning_context['adaptations'][:2])}.")

    prompt_parts.append("Génère un diagnostic coach en 2-3 phrases. Pas de listes.")

    return system, "\n".join(prompt_parts)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_linked_activity(session: Any, activities: list[Any]) -> Any | None:
    session_id = _value(session, "id")
    if session_id is None:
        return None
    for a in activities:
        if _value(a, "scheduled_session_id") == session_id:
            return a
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
    from datetime import datetime
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
