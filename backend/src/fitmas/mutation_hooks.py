"""Mutation middleware: pre/post hooks for validation, logging, and impact tracking.

Pre-hooks run before a mutation is applied and can block or annotate it.
Post-hooks run after a mutation succeeds and handle logging + side effects.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Sequence

from sqlalchemy.orm import Session

from fitmas import repository as repo
from fitmas.llm import MutationDecision
from fitmas.planning_config import GLOBAL_PLANNING_CONFIG, get_sport_planning_config
from fitmas.time_context import get_local_now

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MutationWarning:
    code: str
    message: str
    severity: str = "warning"  # warning | info


@dataclass(slots=True)
class PreMutationResult:
    allowed: bool = True
    block_reason: str | None = None
    warnings: list[MutationWarning] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class MutationImpact:
    delta_weekly_load: float | None = None
    delta_weekly_duration_min: int | None = None
    key_sessions_affected: int = 0
    fragile_day_targeted: bool = False
    recovery_day_lost: bool = False


@dataclass(frozen=True, slots=True)
class PostMutationResult:
    impact: MutationImpact
    log_entry: dict[str, Any]
    recalibration_triggered: bool = False


# ---------------------------------------------------------------------------
# Pre-mutation hooks
# ---------------------------------------------------------------------------

def run_pre_mutation_hooks(
    db: Session,
    plan_id: int,
    decision: MutationDecision,
    *,
    scheduled_sessions: Sequence[Any] = (),
    timezone_name: str | None = None,
) -> PreMutationResult:
    """Run all pre-mutation validations. Returns combined result."""
    result = PreMutationResult()

    if decision.mutation_type == "no_change":
        return result

    _check_plausibility(result, decision, scheduled_sessions=scheduled_sessions, timezone_name=timezone_name)
    _check_fragile_day(result, decision, scheduled_sessions=scheduled_sessions, timezone_name=timezone_name)
    _check_same_sport_proximity(result, decision, scheduled_sessions=scheduled_sessions, timezone_name=timezone_name)
    _check_load_coherence(result, decision, scheduled_sessions=scheduled_sessions)

    if result.warnings:
        codes = [w.code for w in result.warnings]
        logger.info("Pre-mutation warnings for %s: %s", decision.mutation_type, codes)

    return result


def _check_plausibility(
    result: PreMutationResult,
    decision: MutationDecision,
    *,
    scheduled_sessions: Sequence[Any],
    timezone_name: str | None,
) -> None:
    """Block moves to dates in the past."""
    if decision.mutation_type != "move_session":
        return
    target_date = _resolve_decision_target_date(decision, timezone_name=timezone_name)
    if target_date is None:
        return
    local_today = get_local_now(timezone_name).date()
    if target_date < local_today:
        result.warnings.append(MutationWarning(
            code="move_to_past",
            message=f"La date cible {target_date.isoformat()} est dans le passe.",
            severity="warning",
        ))


def _check_fragile_day(
    result: PreMutationResult,
    decision: MutationDecision,
    *,
    scheduled_sessions: Sequence[Any],
    timezone_name: str | None,
) -> None:
    """Warn if moving a key session to a day that already has a hard session."""
    if decision.mutation_type not in ("move_session", "swap_sessions"):
        return
    target_date = _resolve_decision_target_date(decision, timezone_name=timezone_name)
    if target_date is None:
        return

    sessions_on_target = [
        s for s in scheduled_sessions
        if _session_date(s, timezone_name) == target_date
        and _value(s, "id") != decision.target_session_id
    ]
    has_hard = any(
        str(_value(s, "intensity") or "").lower() in ("hard", "key")
        or str(_value(s, "priority") or "").lower() in ("cle", "forte", "key")
        for s in sessions_on_target
    )
    if has_hard:
        result.warnings.append(MutationWarning(
            code="hard_session_collision",
            message=f"Le {target_date.isoformat()} a deja une seance intense.",
        ))


def _check_load_coherence(
    result: PreMutationResult,
    decision: MutationDecision,
    *,
    scheduled_sessions: Sequence[Any],
) -> None:
    """Warn if replacing with a session that pushes weekly hard count over limit."""
    if decision.mutation_type != "replace_session":
        return
    new_intensity = (decision.new_intensity or "").lower()
    if new_intensity not in ("hard", "key"):
        return

    week_hard_count = sum(
        1 for s in scheduled_sessions
        if str(_value(s, "intensity") or "").lower() in ("hard", "key")
        and str(_value(s, "completion_status") or "") == "planned"
    )
    limit = GLOBAL_PLANNING_CONFIG.max_hard_sessions_per_week
    if week_hard_count >= limit:
        result.warnings.append(MutationWarning(
            code="hard_session_limit",
            message=f"Deja {week_hard_count} seances intenses cette semaine (max {limit}).",
        ))


def _check_same_sport_proximity(
    result: PreMutationResult,
    decision: MutationDecision,
    *,
    scheduled_sessions: Sequence[Any],
    timezone_name: str | None,
) -> None:
    """Block quasi-duplicate sessions of the same sport/type within 48h."""
    if decision.mutation_type != "move_session" or decision.target_session_id is None:
        return
    target_date = _resolve_decision_target_date(decision, timezone_name=timezone_name)
    if target_date is None:
        return
    target_session = _find_session(scheduled_sessions, decision.target_session_id)
    if target_session is None:
        return
    target_sport = str(_value(target_session, "sport_type") or "").strip().lower()
    target_type = str(_value(target_session, "session_type") or "").strip().lower()
    if target_sport in {"", "rest", "off"}:
        return

    for session in scheduled_sessions:
        if _value(session, "id") == decision.target_session_id:
            continue
        if str(_value(session, "completion_status") or "").strip().lower() in {"done", "skipped"}:
            continue
        session_sport = str(_value(session, "sport_type") or "").strip().lower()
        session_type = str(_value(session, "session_type") or "").strip().lower()
        session_date = _session_date(session, timezone_name)
        if session_date is None:
            continue
        if session_sport != target_sport or session_type != target_type:
            continue
        if abs((session_date - target_date).days) <= 2:
            result.allowed = False
            result.block_reason = "same_sport_proximity"
            result.warnings.append(MutationWarning(
                code="same_sport_proximity",
                message=f"Le {target_date.isoformat()} placerait deux seances {target_sport}/{target_type} a moins de 48h.",
                severity="warning",
            ))
            return


# ---------------------------------------------------------------------------
# Post-mutation hooks
# ---------------------------------------------------------------------------

def run_post_mutation_hooks(
    db: Session,
    plan_id: int,
    decision: MutationDecision,
    *,
    scheduled_sessions: Sequence[Any] = (),
    timezone_name: str | None = None,
    pre_result: PreMutationResult | None = None,
) -> PostMutationResult:
    """Run all post-mutation processing. Returns impact + log entry."""
    impact = _calculate_impact(decision, scheduled_sessions=scheduled_sessions, timezone_name=timezone_name)
    log_entry = _build_mutation_log(decision, impact=impact, pre_warnings=pre_result.warnings if pre_result else [])

    logger.info(
        "Post-mutation: type=%s delta_load=%s delta_duration=%s key_affected=%d",
        decision.mutation_type,
        impact.delta_weekly_load,
        impact.delta_weekly_duration_min,
        impact.key_sessions_affected,
    )

    recalibration = _should_trigger_recalibration(impact)
    if recalibration:
        logger.info("Recalibration triggered after %s", decision.mutation_type)

    return PostMutationResult(
        impact=impact,
        log_entry=log_entry,
        recalibration_triggered=recalibration,
    )


def _calculate_impact(
    decision: MutationDecision,
    *,
    scheduled_sessions: Sequence[Any],
    timezone_name: str | None,
) -> MutationImpact:
    """Calculate the impact of a mutation on the weekly plan."""
    delta_duration: int | None = None
    delta_load: float | None = None
    key_affected = 0
    fragile = False
    recovery_lost = False

    target = _find_session(scheduled_sessions, decision.target_session_id)

    if decision.mutation_type == "lighten_day" and target:
        old_load = float(_value(target, "load_score") or 0)
        old_duration = int(_value(target, "duration_min") or 0)
        delta_load = -old_load
        delta_duration = -old_duration
        if _is_key_session(target):
            key_affected = 1

    elif decision.mutation_type == "replace_session" and target:
        old_duration = int(_value(target, "duration_min") or 0)
        new_duration = decision.new_duration_min or old_duration
        delta_duration = new_duration - old_duration
        if _is_key_session(target):
            key_affected = 1

    elif decision.mutation_type == "move_session":
        target_date = _resolve_decision_target_date(decision, timezone_name=timezone_name)
        if target_date:
            rest_sessions = [
                s for s in scheduled_sessions
                if _session_date(s, timezone_name) == target_date
                and str(_value(s, "sport_type") or "").lower() == "rest"
            ]
            if rest_sessions:
                recovery_lost = True

    return MutationImpact(
        delta_weekly_load=delta_load,
        delta_weekly_duration_min=delta_duration,
        key_sessions_affected=key_affected,
        fragile_day_targeted=fragile,
        recovery_day_lost=recovery_lost,
    )


def _should_trigger_recalibration(impact: MutationImpact) -> bool:
    """Decide if the impact warrants a recalibration flag."""
    if impact.key_sessions_affected >= 2:
        return True
    if impact.delta_weekly_load is not None and abs(impact.delta_weekly_load) > 3.0:
        return True
    if impact.recovery_day_lost:
        return True
    return False


def _build_mutation_log(
    decision: MutationDecision,
    *,
    impact: MutationImpact,
    pre_warnings: list[MutationWarning],
) -> dict[str, Any]:
    """Build a structured log entry for the mutation."""
    return {
        "mutation_type": decision.mutation_type,
        "target_session_id": decision.target_session_id,
        "second_session_id": decision.second_session_id,
        "rationale": decision.rationale,
        "impact": {
            "delta_weekly_load": impact.delta_weekly_load,
            "delta_weekly_duration_min": impact.delta_weekly_duration_min,
            "key_sessions_affected": impact.key_sessions_affected,
            "fragile_day_targeted": impact.fragile_day_targeted,
            "recovery_day_lost": impact.recovery_day_lost,
        },
        "pre_warnings": [{"code": w.code, "message": w.message} for w in pre_warnings],
        "recalibration_triggered": _should_trigger_recalibration(impact),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_session(sessions: Sequence[Any], session_id: int | None) -> Any | None:
    if session_id is None:
        return None
    for s in sessions:
        if _value(s, "id") == session_id:
            return s
    return None


def _is_key_session(session: Any) -> bool:
    priority = str(_value(session, "priority") or "").lower()
    title = str(_value(session, "session_title") or "").lower()
    return any(kw in f"{priority} {title}" for kw in ("cle", "qualite", "bloc", "key", "fort"))


def _session_date(session: Any, timezone_name: str | None) -> date | None:
    raw = _value(session, "scheduled_date")
    if raw is None:
        return None
    if isinstance(raw, date):
        return raw
    try:
        return date.fromisoformat(str(raw)[:10])
    except (ValueError, TypeError):
        return None


def _resolve_decision_target_date(decision: MutationDecision, *, timezone_name: str | None) -> date | None:
    if decision.target_date:
        try:
            return date.fromisoformat(decision.target_date)
        except ValueError:
            return None
    if decision.to_day:
        day_index = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        try:
            idx = day_index.index(decision.to_day)
        except ValueError:
            return None
        today = get_local_now(timezone_name).date()
        delta = (idx - today.weekday()) % 7
        if delta == 0:
            delta = 7
        return today + timedelta(days=delta)
    return None


def _value(obj: Any, key: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)
