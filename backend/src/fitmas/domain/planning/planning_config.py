from __future__ import annotations

from dataclasses import dataclass

SUPPORTED_SPORTS = ("running", "cycling", "swimming", "strength", "climbing")
SUPPORTED_LEVELS = ("beginner", "intermediate", "advanced", "unknown")


@dataclass(frozen=True, slots=True)
class GlobalPlanningConfig:
    max_key_sessions_per_week: int = 2
    max_hard_sessions_per_week: int = 3
    min_recovery_days_per_week: int = 1
    min_hours_between_hard_sessions: int = 36
    max_llm_validation_retries: int = 2
    tsb_floor: float = -20.0
    max_weekly_ramp_rate: float = 0.08
    max_monotony: float = 2.2


@dataclass(frozen=True, slots=True)
class SportPlanningConfig:
    sport: str
    key_sessions_default: int
    supports_long_session: bool
    min_session_duration_min: int
    max_session_duration_min: int
    default_tss_per_hour: float
    requires_fixed_slot: bool = False


@dataclass(frozen=True, slots=True)
class LevelPlanningConfig:
    level: str
    weekly_tss_floor: float
    weekly_tss_ceiling: float
    long_session_ceiling_min: int


GLOBAL_PLANNING_CONFIG = GlobalPlanningConfig()

SPORT_PLANNING_CONFIGS: dict[str, SportPlanningConfig] = {
    "running": SportPlanningConfig(
        sport="running",
        key_sessions_default=2,
        supports_long_session=True,
        min_session_duration_min=25,
        max_session_duration_min=140,
        default_tss_per_hour=55.0,
    ),
    "cycling": SportPlanningConfig(
        sport="cycling",
        key_sessions_default=2,
        supports_long_session=True,
        min_session_duration_min=30,
        max_session_duration_min=240,
        default_tss_per_hour=50.0,
    ),
    "swimming": SportPlanningConfig(
        sport="swimming",
        key_sessions_default=1,
        supports_long_session=False,
        min_session_duration_min=25,
        max_session_duration_min=90,
        default_tss_per_hour=38.0,
        requires_fixed_slot=True,
    ),
    "strength": SportPlanningConfig(
        sport="strength",
        key_sessions_default=1,
        supports_long_session=False,
        min_session_duration_min=20,
        max_session_duration_min=75,
        default_tss_per_hour=32.0,
    ),
    "climbing": SportPlanningConfig(
        sport="climbing",
        key_sessions_default=1,
        supports_long_session=False,
        min_session_duration_min=45,
        max_session_duration_min=150,
        default_tss_per_hour=42.0,
    ),
}

LEVEL_PLANNING_CONFIGS: dict[str, LevelPlanningConfig] = {
    "beginner": LevelPlanningConfig(
        level="beginner",
        weekly_tss_floor=80.0,
        weekly_tss_ceiling=280.0,
        long_session_ceiling_min=90,
    ),
    "intermediate": LevelPlanningConfig(
        level="intermediate",
        weekly_tss_floor=180.0,
        weekly_tss_ceiling=520.0,
        long_session_ceiling_min=150,
    ),
    "advanced": LevelPlanningConfig(
        level="advanced",
        weekly_tss_floor=260.0,
        weekly_tss_ceiling=800.0,
        long_session_ceiling_min=240,
    ),
    "unknown": LevelPlanningConfig(
        level="unknown",
        weekly_tss_floor=120.0,
        weekly_tss_ceiling=380.0,
        long_session_ceiling_min=120,
    ),
}


def get_global_planning_config() -> GlobalPlanningConfig:
    return GLOBAL_PLANNING_CONFIG


def get_sport_planning_config(sport: str) -> SportPlanningConfig:
    return SPORT_PLANNING_CONFIGS.get(sport, SPORT_PLANNING_CONFIGS["running"])


def get_level_planning_config(level: str) -> LevelPlanningConfig:
    return LEVEL_PLANNING_CONFIGS.get(level, LEVEL_PLANNING_CONFIGS["unknown"])
