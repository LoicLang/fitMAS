from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence

from fitmas.domain.planning.adaptation_decision import AdaptationDecision, DecisionReasonCode, TrajectoryImpact, WeekMissionStatus


@dataclass(frozen=True, slots=True)
class AdaptationLogEntry:
    created_at: str | None
    reason_code: str
    reason_label: str
    adaptation_level: str
    week_mission_status: str
    mission_label: str
    trajectory_impact: str
    impact_label: str
    scenario_type: str
    mutation_type: str
    summary: str
    what_changed: str
    what_protected: str
    user_message: str
    source_text: str
    change_cost: int
    stability_penalty: float
    protected_session_ids: tuple[int, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "created_at": self.created_at,
            "reason_code": self.reason_code,
            "reason_label": self.reason_label,
            "adaptation_level": self.adaptation_level,
            "week_mission_status": self.week_mission_status,
            "mission_label": self.mission_label,
            "trajectory_impact": self.trajectory_impact,
            "impact_label": self.impact_label,
            "scenario_type": self.scenario_type,
            "mutation_type": self.mutation_type,
            "summary": self.summary,
            "what_changed": self.what_changed,
            "what_protected": self.what_protected,
            "user_message": self.user_message,
            "source_text": self.source_text,
            "change_cost": self.change_cost,
            "stability_penalty": round(self.stability_penalty, 1),
            "protected_session_ids": list(self.protected_session_ids),
        }


def build_adaptation_log_entry(
    *,
    decision: AdaptationDecision,
    scheduled_sessions: Sequence[Any],
    created_at: datetime | None = None,
) -> AdaptationLogEntry:
    scenario = decision.selected_scenario
    session_by_id = {int(_value(session, "id") or 0): session for session in scheduled_sessions}
    impacted = session_by_id.get(decision.event.affected_session_id or 0)
    impacted_title = str(_value(impacted, "session_title") or "la seance")
    protected_titles = [
        str(_value(session_by_id.get(session_id), "session_title") or "la suite de la semaine")
        for session_id in scenario.protected_session_ids
    ]
    what_protected = (
        ", ".join(protected_titles[:2])
        if protected_titles
        else "la mission de semaine et les autres creneaux utiles"
    )

    if scenario.mutation.mutation_type == "move_session" and scenario.mutation.target_date:
        what_changed = f"{impacted_title} passe au {scenario.mutation.target_date}."
    elif scenario.mutation.mutation_type == "replace_session" and scenario.mutation.new_duration_min:
        what_changed = f"{impacted_title} passe en version courte {scenario.mutation.new_duration_min} min."
    elif scenario.mutation.mutation_type == "lighten_day":
        what_changed = f"{impacted_title} est allegee pour garder une semaine lisible."
    elif scenario.summary:
        what_changed = scenario.summary
    else:
        what_changed = "Le plan a ete ajuste."

    return AdaptationLogEntry(
        created_at=created_at.isoformat() if created_at else None,
        reason_code=decision.event.reason_code.value,
        reason_label=_reason_label(decision.event.reason_code),
        adaptation_level=scenario.adaptation_level.value,
        week_mission_status=scenario.week_mission_status.value,
        mission_label=_mission_label(scenario.week_mission_status),
        trajectory_impact=scenario.trajectory_impact.value,
        impact_label=_impact_label(scenario.trajectory_impact),
        scenario_type=scenario.scenario_type,
        mutation_type=scenario.mutation.mutation_type,
        summary=scenario.summary,
        what_changed=what_changed,
        what_protected=what_protected,
        user_message=decision.user_message,
        source_text=decision.event.source_text,
        change_cost=scenario.change_cost,
        stability_penalty=scenario.stability_penalty,
        protected_session_ids=scenario.protected_session_ids,
    )


def _reason_label(reason_code: DecisionReasonCode) -> str:
    labels = {
        DecisionReasonCode.LOGISTICS_CONFLICT: "Imprevu logistique",
        DecisionReasonCode.FATIGUE_SIGNAL: "Signal de fatigue",
        DecisionReasonCode.TRAVEL_CONSTRAINT: "Contrainte de voyage",
        DecisionReasonCode.NO_FEASIBLE_MOVE: "Pas de deplacement propre possible",
    }
    return labels.get(reason_code, "Adaptation du plan")


def _mission_label(status: WeekMissionStatus) -> str:
    labels = {
        WeekMissionStatus.UNCHANGED: "Mission inchangée",
        WeekMissionStatus.SOFTENED: "Mission adoucie",
        WeekMissionStatus.REVISED: "Mission révisée",
    }
    return labels.get(status, "Mission ajustée")


def _impact_label(impact: TrajectoryImpact) -> str:
    labels = {
        TrajectoryImpact.NONE: "Impact nul",
        TrajectoryImpact.LOW: "Impact faible",
        TrajectoryImpact.MODERATE: "Impact modéré",
        TrajectoryImpact.SIGNIFICANT: "Impact significatif",
    }
    return labels.get(impact, "Impact en cours")


def _value(obj: Any, key: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)
