from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class AdaptationLevel(StrEnum):
    MICRO = "micro"
    MESO = "meso"
    MACRO = "macro"


class WeekMissionStatus(StrEnum):
    UNCHANGED = "unchanged"
    SOFTENED = "softened"
    REVISED = "revised"


class TrajectoryImpact(StrEnum):
    NONE = "none"
    LOW = "low"
    MODERATE = "moderate"
    SIGNIFICANT = "significant"


class DecisionReasonCode(StrEnum):
    LOGISTICS_CONFLICT = "logistics_conflict"
    FATIGUE_SIGNAL = "fatigue_signal"
    TRAVEL_CONSTRAINT = "travel_constraint"
    NO_FEASIBLE_MOVE = "no_feasible_move"


@dataclass(frozen=True, slots=True)
class ProposedMutation:
    mutation_type: str
    target_session_id: int | None
    rationale: str
    target_date: str | None = None
    from_day: str | None = None
    to_day: str | None = None
    new_title: str | None = None
    new_goal: str | None = None
    new_sport_type: str | None = None
    new_session_type: str | None = None
    new_duration_min: int | None = None
    new_intensity: str | None = None
    new_description: str | None = None


@dataclass(frozen=True, slots=True)
class LifeChangeEvent:
    reason_code: DecisionReasonCode
    adaptation_level: AdaptationLevel
    confidence: float
    affected_session_id: int | None
    affected_date: date | None
    temporal_label: str
    details: str
    source_text: str
    requested_day: str | None = None
    requested_days: tuple[str, ...] = ()
    requested_window: str | None = None
    earliest_date: date | None = None


@dataclass(frozen=True, slots=True)
class ReplanScenario:
    scenario_type: str
    mutation: ProposedMutation
    score: float
    change_cost: int
    stability_penalty: float
    adaptation_level: AdaptationLevel
    week_mission_status: WeekMissionStatus
    trajectory_impact: TrajectoryImpact
    protected_session_ids: tuple[int, ...]
    summary: str


@dataclass(frozen=True, slots=True)
class AdaptationDecision:
    event: LifeChangeEvent
    selected_scenario: ReplanScenario
    alternative_scenarios: tuple[ReplanScenario, ...]
    user_message: str
