from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Any, Sequence

from fitmas.legacy.domain.athlete.profile import AthleteProfileSnapshot


class CalibrationPhase(StrEnum):
    DRAFT = "draft"
    CALIBRATING = "calibrating"
    STABLE = "stable"


@dataclass(frozen=True, slots=True)
class CalibrationStatus:
    phase: CalibrationPhase
    label: str
    summary: str
    next_step: str
    known_unknowns: tuple[str, ...]
    days_since_start: int
    activity_count_14d: int
    pattern_count: int
    adaptation_count_14d: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase.value,
            "label": self.label,
            "summary": self.summary,
            "next_step": self.next_step,
            "known_unknowns": list(self.known_unknowns),
            "days_since_start": self.days_since_start,
            "activity_count_14d": self.activity_count_14d,
            "pattern_count": self.pattern_count,
            "adaptation_count_14d": self.adaptation_count_14d,
        }


def build_initial_calibration_status(payload: dict) -> CalibrationStatus:
    known_unknowns = build_onboarding_unknowns(payload)
    return CalibrationStatus(
        phase=CalibrationPhase.DRAFT,
        label="First Week Draft",
        summary="Premiere semaine credible, encore surtout basee sur ce que tu as declare.",
        next_step="On affine vite apres les premieres seances et les premiers imprévus reels.",
        known_unknowns=tuple(known_unknowns),
        days_since_start=0,
        activity_count_14d=0,
        pattern_count=0,
        adaptation_count_14d=0,
    )


def build_calibration_status(
    *,
    profile: AthleteProfileSnapshot,
    memory_items: Sequence[object],
    activities: Sequence[Any],
    adaptation_events: Sequence[Any],
    today: date | datetime | None = None,
) -> CalibrationStatus:
    current_date = _as_date(today) or date.today()
    profile_rows = [row for row in memory_items if getattr(row, "pattern_type", None) in {None, ""}]
    patterns = [row for row in memory_items if getattr(row, "pattern_type", None)]

    availability_days = len(profile.weekly_availability)
    has_training_state = any(str(getattr(row, "category", "") or "") == "training_state" for row in profile_rows)
    activity_count_14d = sum(1 for activity in activities if _as_date(_value(activity, "started_at") or _value(activity, "created_at")) and _as_date(_value(activity, "started_at") or _value(activity, "created_at")) >= current_date - timedelta(days=14))
    adaptation_count_14d = sum(1 for event in adaptation_events if _as_date(_value(event, "created_at")) and _as_date(_value(event, "created_at")) >= current_date - timedelta(days=14))
    pattern_count = len(patterns)
    anchor_date = _anchor_date(profile_rows, current_date=current_date)
    days_since_start = max((current_date - anchor_date).days, 0) if anchor_date else 0

    known_unknowns = _build_runtime_unknowns(
        availability_days=availability_days,
        has_training_state=has_training_state,
        activity_count_14d=activity_count_14d,
        pattern_count=pattern_count,
    )

    if (not profile.onboarding_completed) or activity_count_14d < 2 or availability_days < 2:
        return CalibrationStatus(
            phase=CalibrationPhase.DRAFT,
            label="First Week Draft",
            summary="Le plan reste une premiere hypothese forte. Il connait le cap, pas encore toutes tes vraies frictions.",
            next_step="Log 2 ou 3 seances et signale tout creneau faux. C'est la matiere qui fait monter la precision.",
            known_unknowns=known_unknowns,
            days_since_start=days_since_start,
            activity_count_14d=activity_count_14d,
            pattern_count=pattern_count,
            adaptation_count_14d=adaptation_count_14d,
        )

    if days_since_start < 14 or activity_count_14d < 5 or pattern_count < 1:
        return CalibrationStatus(
            phase=CalibrationPhase.CALIBRATING,
            label="Calibration en cours",
            summary="FitMAS croise maintenant ton declaratif, tes seances reelles et les premiers ajustements de vie.",
            next_step="Continue a corriger ce qui sonne faux. Le but est de stabiliser les bons creneaux, pas de tout redemander.",
            known_unknowns=known_unknowns,
            days_since_start=days_since_start,
            activity_count_14d=activity_count_14d,
            pattern_count=pattern_count,
            adaptation_count_14d=adaptation_count_14d,
        )

    return CalibrationStatus(
        phase=CalibrationPhase.STABLE,
        label="Base stable",
        summary="Les grands repères de semaine, la charge recente et les patterns principaux sont assez clairs pour planifier proprement.",
        next_step="Les prochains ajustements servent surtout a proteger la semaine, pas a redecouvrir ton fonctionnement.",
        known_unknowns=known_unknowns,
        days_since_start=days_since_start,
        activity_count_14d=activity_count_14d,
        pattern_count=pattern_count,
        adaptation_count_14d=adaptation_count_14d,
    )


def build_onboarding_unknowns(payload: dict) -> list[str]:
    unknowns: list[str] = []
    if not str(payload.get("goal_context") or "").strip():
        unknowns.append("l'horizon exact du cap")
    if not str(payload.get("current_state_notes") or "").strip():
        unknowns.append("ta forme recente exacte")
    if not payload.get("preferences"):
        unknowns.append("tes preferences fortes de pratique")
    return unknowns


def _build_runtime_unknowns(
    *,
    availability_days: int,
    has_training_state: bool,
    activity_count_14d: int,
    pattern_count: int,
) -> tuple[str, ...]:
    unknowns: list[str] = []
    if availability_days < 2:
        unknowns.append("la vraie semaine reste encore partielle")
    if not has_training_state:
        unknowns.append("la forme recente reste peu documentee")
    if activity_count_14d < 2:
        unknowns.append("il manque encore du reel execute")
    if pattern_count < 1:
        unknowns.append("les patterns utiles au planner ne sont pas encore stabilises")
    return tuple(unknowns)


def _anchor_date(rows: Sequence[object], *, current_date: date) -> date | None:
    candidates: list[date] = []
    for row in rows:
        if str(getattr(row, "source", "") or "") != "onboarding":
            continue
        candidate = _as_date(getattr(row, "created_at", None))
        if candidate:
            candidates.append(candidate)
    return min(candidates) if candidates else current_date


def _value(row: Any, field: str) -> Any:
    if row is None:
        return None
    if isinstance(row, dict):
        return row.get(field)
    return getattr(row, field, None)


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            return None
    return None
