from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable, Literal, Sequence

from fitmas.fitness_snapshot import estimate_scheduled_session_tss
from fitmas.plan_patch import PlanPatch, PlanPatchValidation

WeekCoherenceStatus = Literal["valid", "warning", "requires_confirmation", "blocked"]
SportQuality = Literal["good", "acceptable", "fragile", "poor"]
WeekCoherenceFindingSeverity = Literal["info", "warning", "requires_confirmation", "blocked"]
WeekCoherenceRecommendedPolicy = Literal[
    "commit_original",
    "confirm_original",
    "block_original",
    "retry_with_revised_patch",
    "confirm_revised",
]
WeekCoherencePolicyStatus = Literal["valid", "requires_confirmation", "blocked"]


@dataclass(frozen=True, slots=True)
class WeekSnapshot:
    week_start: date
    sessions: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class WeekPatchDiff:
    changed_sessions: tuple[dict[str, Any], ...]
    created_sessions: tuple[dict[str, Any], ...]
    removed_or_lightened_sessions: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class DeterministicWeekChecks:
    hard_sessions_before: int
    hard_sessions_after: int
    min_hard_gap_hours_after: int | None
    recovery_sessions_before: int
    recovery_sessions_after: int
    key_session_ids_touched: tuple[int, ...]
    completed_session_ids_touched: tuple[int, ...]
    weekly_duration_delta_min: int
    estimated_tss_delta: float | None
    change_budget_remaining_before: int | None
    change_budget_remaining_after: int | None
    flags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class WeekCoherenceFinding:
    code: str
    severity: WeekCoherenceFindingSeverity
    detail: str
    target_session_ids: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class WeekCoherenceReview:
    status: WeekCoherenceStatus
    sport_quality: SportQuality
    confidence: float
    summary: str
    findings: tuple[WeekCoherenceFinding, ...]
    suggested_adjustments: tuple[dict[str, Any], ...]
    recommended_policy: WeekCoherenceRecommendedPolicy
    revised_patch: PlanPatch | None = None


@dataclass(frozen=True, slots=True)
class WeekCoherenceContext:
    patch: PlanPatch
    validation: PlanPatchValidation
    before_week: WeekSnapshot
    after_week: WeekSnapshot
    diff: WeekPatchDiff
    deterministic_checks: DeterministicWeekChecks
    planning_contract: dict[str, Any] | None
    week_mission: dict[str, Any] | None
    session_policies: tuple[dict[str, Any], ...]
    recent_reality: dict[str, Any] | None
    active_constraints: tuple[dict[str, Any], ...]


def simulate_plan_patch(
    scheduled_sessions: Sequence[Any],
    patch: PlanPatch,
    *,
    timezone_name: str | None,
) -> tuple[WeekSnapshot, WeekSnapshot, WeekPatchDiff]:
    """Simulate a PlanPatch against ScheduledSession-like objects without writing."""
    del timezone_name
    before_sessions = [_session_snapshot(session) for session in scheduled_sessions]
    after_sessions = deepcopy(before_sessions)
    created_sessions: list[dict[str, Any]] = []
    lightened_sessions: list[dict[str, Any]] = []

    for operation in patch.operations:
        if operation.operation_type == "create_session":
            created = _created_session_snapshot(operation)
            after_sessions.append(created)
            created_sessions.append(created)
            continue

        target = _find_session_dict(after_sessions, operation.target_session_id)
        if target is None:
            continue

        if operation.operation_type == "move_session" and operation.target_date:
            target["scheduled_date"] = operation.target_date
            target["day"] = _day_key(operation.target_date) or target.get("day")
            continue

        if operation.operation_type == "swap_sessions":
            second = _find_session_dict(after_sessions, operation.second_session_id)
            if second is None:
                continue
            first_date = target.get("scheduled_date")
            second_date = second.get("scheduled_date")
            target["scheduled_date"], second["scheduled_date"] = second_date, first_date
            target["day"] = _day_key(target.get("scheduled_date")) or target.get("day")
            second["day"] = _day_key(second.get("scheduled_date")) or second.get("day")
            continue

        if operation.operation_type in {"replace_session", "update_session"}:
            _apply_session_field_updates(target, operation)
            continue

        if operation.operation_type == "lighten_day":
            before_lighten = deepcopy(target)
            target["intensity"] = "easy"
            target["load_score"] = min(_int(target.get("load_score"), default=1), 1)
            if target.get("duration_min"):
                target["duration_min"] = max(20, int(target["duration_min"]) // 2)
            lightened_sessions.append({"id": target.get("id"), "before": before_lighten, "after": deepcopy(target)})

    before = WeekSnapshot(week_start=_week_start(before_sessions), sessions=tuple(_sort_sessions(before_sessions)))
    after = WeekSnapshot(week_start=_week_start(after_sessions), sessions=tuple(_sort_sessions(after_sessions)))
    return before, after, _build_diff(before.sessions, after.sessions, created_sessions, lightened_sessions)


def build_week_coherence_context(
    *,
    patch: PlanPatch,
    validation: PlanPatchValidation,
    scheduled_sessions: Sequence[Any],
    coach_state_bundle: Any | None = None,
    activities: Sequence[Any] = (),
    active_facts: Sequence[Any] = (),
    timezone_name: str | None = None,
) -> WeekCoherenceContext:
    before, after, diff = simulate_plan_patch(scheduled_sessions, patch, timezone_name=timezone_name)
    initial = WeekCoherenceContext(
        patch=patch,
        validation=validation,
        before_week=before,
        after_week=after,
        diff=diff,
        deterministic_checks=_empty_checks(),
        planning_contract=_as_dict(getattr(coach_state_bundle, "planning_contract", None)),
        week_mission=_as_dict(getattr(coach_state_bundle, "week_mission", None)),
        session_policies=tuple(_as_dict(item) or {} for item in getattr(coach_state_bundle, "session_policies", ()) or ()),
        recent_reality=_as_dict(getattr(coach_state_bundle, "recent_reality", None)) or _recent_reality_payload(activities),
        active_constraints=tuple(_as_dict(item) or {} for item in active_facts),
    )
    checks = evaluate_week_invariants(initial)
    return WeekCoherenceContext(
        patch=patch,
        validation=validation,
        before_week=before,
        after_week=after,
        diff=diff,
        deterministic_checks=checks,
        planning_contract=initial.planning_contract,
        week_mission=initial.week_mission,
        session_policies=initial.session_policies,
        recent_reality=initial.recent_reality,
        active_constraints=initial.active_constraints,
    )


def evaluate_week_invariants(context: WeekCoherenceContext) -> DeterministicWeekChecks:
    before_sessions = context.before_week.sessions
    after_sessions = context.after_week.sessions
    changed_ids = tuple(
        int(item["id"])
        for item in context.diff.changed_sessions
        if item.get("id") is not None
    )
    before_by_id = {int(item["id"]): item for item in before_sessions if item.get("id") is not None}
    key_touched = tuple(
        session_id
        for session_id in changed_ids
        if _is_key_session(before_by_id.get(session_id, {}))
    )
    completed_touched = tuple(
        session_id
        for session_id in changed_ids
        if _is_completed(before_by_id.get(session_id, {}))
    )
    hard_before = sum(1 for session in before_sessions if _is_hard_session(session))
    hard_after = sum(1 for session in after_sessions if _is_hard_session(session))
    recovery_before = sum(1 for session in before_sessions if _is_recovery_session(session))
    recovery_after = sum(1 for session in after_sessions if _is_recovery_session(session))
    duration_before = sum(_int(session.get("duration_min"), default=0) for session in before_sessions)
    duration_after = sum(_int(session.get("duration_min"), default=0) for session in after_sessions)
    tss_before = sum(estimate_scheduled_session_tss(session) for session in before_sessions)
    tss_after = sum(estimate_scheduled_session_tss(session) for session in after_sessions)
    min_hard_gap = _min_hard_gap_hours(after_sessions)

    flags: list[str] = []
    if len(context.patch.operations) > 1:
        flags.append("multi_session_patch")
    if key_touched:
        flags.append("key_session_touched")
    if completed_touched:
        flags.append("completed_session_touched")
    if recovery_after < recovery_before:
        flags.append("recovery_session_lost")
    if hard_after > 3:
        flags.append("too_many_hard_sessions")
    if min_hard_gap is not None and min_hard_gap < 36:
        flags.append("hard_sessions_too_close")
    if abs(duration_after - duration_before) >= 45:
        flags.append("weekly_duration_delta_high")
    if abs(tss_after - tss_before) >= 35:
        flags.append("weekly_load_delta_high")

    return DeterministicWeekChecks(
        hard_sessions_before=hard_before,
        hard_sessions_after=hard_after,
        min_hard_gap_hours_after=min_hard_gap,
        recovery_sessions_before=recovery_before,
        recovery_sessions_after=recovery_after,
        key_session_ids_touched=key_touched,
        completed_session_ids_touched=completed_touched,
        weekly_duration_delta_min=duration_after - duration_before,
        estimated_tss_delta=round(tss_after - tss_before, 1),
        change_budget_remaining_before=None,
        change_budget_remaining_after=None,
        flags=tuple(dict.fromkeys(flags)),
    )


def aggregate_week_coherence_policy(
    *,
    patch_validation: PlanPatchValidation,
    week_review: WeekCoherenceReview | None,
    deterministic_checks: DeterministicWeekChecks,
    allow_requires_confirmation: bool,
) -> WeekCoherencePolicyStatus:
    if patch_validation.status == "blocked":
        return "blocked"
    if deterministic_checks.completed_session_ids_touched:
        return "blocked"
    if week_review is not None:
        if week_review.status == "blocked" or week_review.recommended_policy == "block_original":
            return "blocked"
        if week_review.status in {"warning", "requires_confirmation"} or week_review.recommended_policy in {
            "confirm_original",
            "retry_with_revised_patch",
            "confirm_revised",
        }:
            return "valid" if allow_requires_confirmation else "requires_confirmation"
    if patch_validation.status in {"warning", "requires_confirmation"}:
        return "valid" if allow_requires_confirmation else "requires_confirmation"
    return "valid"


def review_week_coherence_with_llm(
    context: WeekCoherenceContext,
    *,
    request_json_fn: Callable[..., Any] | None = None,
) -> WeekCoherenceReview:
    if request_json_fn is None:
        return fallback_week_coherence_review(context)
    try:
        payload = request_json_fn(context=_context_payload(context))
        if payload is None:
            return fallback_week_coherence_review(context)
        return _parse_review_payload(payload)
    except Exception as exc:
        return fallback_week_coherence_review(context, reason=f"reviewer_invalid_response: {exc}")


def fallback_week_coherence_review(
    context: WeekCoherenceContext,
    *,
    reason: str | None = None,
) -> WeekCoherenceReview:
    checks = context.deterministic_checks
    findings: list[WeekCoherenceFinding] = []
    if reason:
        findings.append(
            WeekCoherenceFinding(
                code="reviewer_invalid_response",
                severity="warning",
                detail="Le reviewer sportif n'a pas retourne un JSON exploitable; fallback conservateur.",
            )
        )
    if context.validation.status in {"warning", "requires_confirmation"}:
        findings.append(
            WeekCoherenceFinding(
                code="runtime_validation_requires_confirmation",
                severity="requires_confirmation",
                detail="La validation runtime demande deja confirmation.",
            )
        )
    if context.validation.status == "blocked":
        findings.append(
            WeekCoherenceFinding(
                code="runtime_validation_blocked",
                severity="blocked",
                detail="La validation runtime bloque ce patch.",
            )
        )
    for flag in checks.flags:
        findings.append(_finding_for_flag(flag, checks=checks))
    if checks.completed_session_ids_touched:
        findings.append(
            WeekCoherenceFinding(
                code="completed_session_touched",
                severity="blocked",
                detail="Le patch touche une seance dont l'execution est deja resolue.",
                target_session_ids=checks.completed_session_ids_touched,
            )
        )

    severities = {finding.severity for finding in findings}
    if "blocked" in severities or context.validation.status == "blocked":
        status: WeekCoherenceStatus = "blocked"
        quality: SportQuality = "poor"
        policy: WeekCoherenceRecommendedPolicy = "block_original"
    elif "requires_confirmation" in severities or "warning" in severities:
        status = "requires_confirmation"
        quality = "fragile"
        policy = "confirm_original"
    else:
        status = "valid"
        quality = "acceptable"
        policy = "commit_original"
        findings.append(
            WeekCoherenceFinding(
                code="patch_sportively_good",
                severity="info",
                detail="Aucun risque sportif structurel detecte par le fallback.",
            )
        )
    return WeekCoherenceReview(
        status=status,
        sport_quality=quality,
        confidence=0.55 if reason else 0.65,
        summary=_fallback_summary(status=status, reason=reason),
        findings=tuple(findings),
        suggested_adjustments=(),
        recommended_policy=policy,
    )


def _session_snapshot(session: Any) -> dict[str, Any]:
    scheduled_date = _as_date(_value(session, "scheduled_date"))
    return {
        "id": _value(session, "id"),
        "user_id": _value(session, "user_id"),
        "day": str(_value(session, "day") or (_day_key(scheduled_date) if scheduled_date else "")),
        "label": str(_value(session, "label") or ""),
        "scheduled_date": scheduled_date.isoformat() if scheduled_date else None,
        "sport_type": str(_value(session, "sport_type") or ""),
        "session_type": str(_value(session, "session_type") or ""),
        "session_title": str(_value(session, "session_title") or ""),
        "session_goal": str(_value(session, "session_goal") or ""),
        "session_note": str(_value(session, "session_note") or ""),
        "session_description": str(_value(session, "session_description") or ""),
        "duration_min": _value(session, "duration_min"),
        "intensity": str(_value(session, "intensity") or ""),
        "load_score": _int(_value(session, "load_score"), default=0),
        "priority": str(_value(session, "priority") or ""),
        "nutrition_focus": str(_value(session, "nutrition_focus") or ""),
        "flexibility": str(_value(session, "flexibility") or ""),
        "completion_status": str(_value(session, "completion_status") or ""),
    }


def _parse_review_payload(payload: Any) -> WeekCoherenceReview:
    if not isinstance(payload, dict):
        raise ValueError("review payload must be an object")
    status = _expect_literal(payload.get("status"), {"valid", "warning", "requires_confirmation", "blocked"}, "status")
    sport_quality = _expect_literal(payload.get("sport_quality"), {"good", "acceptable", "fragile", "poor"}, "sport_quality")
    recommended_policy = _expect_literal(
        payload.get("recommended_policy"),
        {"commit_original", "confirm_original", "block_original", "retry_with_revised_patch", "confirm_revised"},
        "recommended_policy",
    )
    summary = str(payload.get("summary") or "").strip()
    if not summary:
        raise ValueError("summary is required")
    confidence = float(payload.get("confidence"))
    if confidence < 0 or confidence > 1:
        raise ValueError("confidence must be between 0 and 1")
    raw_findings = payload.get("findings") or []
    if not isinstance(raw_findings, list):
        raise ValueError("findings must be a list")
    findings = tuple(_parse_finding(item) for item in raw_findings)
    raw_adjustments = payload.get("suggested_adjustments") or []
    if not isinstance(raw_adjustments, list) or not all(isinstance(item, dict) for item in raw_adjustments):
        raise ValueError("suggested_adjustments must be a list of objects")
    revised_patch = None
    if isinstance(payload.get("revised_patch"), dict):
        revised_patch = PlanPatch.model_validate(payload["revised_patch"])
    return WeekCoherenceReview(
        status=status,  # type: ignore[arg-type]
        sport_quality=sport_quality,  # type: ignore[arg-type]
        confidence=confidence,
        summary=summary,
        findings=findings,
        suggested_adjustments=tuple(dict(item) for item in raw_adjustments),
        recommended_policy=recommended_policy,  # type: ignore[arg-type]
        revised_patch=revised_patch,
    )


def _parse_finding(payload: Any) -> WeekCoherenceFinding:
    if not isinstance(payload, dict):
        raise ValueError("finding must be an object")
    code = str(payload.get("code") or "").strip()
    detail = str(payload.get("detail") or "").strip()
    if not code or not detail:
        raise ValueError("finding code/detail are required")
    severity = _expect_literal(payload.get("severity"), {"info", "warning", "requires_confirmation", "blocked"}, "finding.severity")
    targets = payload.get("target_session_ids") or []
    if not isinstance(targets, list):
        raise ValueError("target_session_ids must be a list")
    return WeekCoherenceFinding(
        code=code,
        severity=severity,  # type: ignore[arg-type]
        detail=detail,
        target_session_ids=tuple(int(item) for item in targets),
    )


def _finding_for_flag(flag: str, *, checks: DeterministicWeekChecks) -> WeekCoherenceFinding:
    mapping: dict[str, tuple[WeekCoherenceFindingSeverity, str]] = {
        "multi_session_patch": ("requires_confirmation", "Le patch touche plusieurs operations."),
        "key_session_touched": ("requires_confirmation", "Le patch touche une seance cle."),
        "recovery_session_lost": ("requires_confirmation", "Le patch retire une recuperation de la semaine."),
        "hard_sessions_too_close": ("requires_confirmation", "Deux seances dures se retrouvent trop proches."),
        "too_many_hard_sessions": ("requires_confirmation", "La semaine contient trop de seances dures."),
        "weekly_duration_delta_high": ("requires_confirmation", "Le delta de duree hebdomadaire est eleve."),
        "weekly_load_delta_high": ("requires_confirmation", "Le delta de charge estimee est eleve."),
    }
    severity, detail = mapping.get(flag, ("warning", f"Signal sportif a relire: {flag}."))
    targets = checks.key_session_ids_touched if flag == "key_session_touched" else ()
    return WeekCoherenceFinding(code=flag, severity=severity, detail=detail, target_session_ids=targets)


def _fallback_summary(*, status: WeekCoherenceStatus, reason: str | None) -> str:
    if status == "blocked":
        return "Patch bloque par la gate sportive fallback."
    if status == "requires_confirmation":
        return "Patch possible mais fragile sportivement; confirmation requise."
    if reason:
        return "Patch accepte par fallback conservateur apres reviewer invalide."
    return "Patch accepte par fallback sportif deterministe."


def _expect_literal(value: Any, allowed: set[str], field: str) -> str:
    normalized = str(value or "").strip()
    if normalized not in allowed:
        raise ValueError(f"invalid {field}: {normalized!r}")
    return normalized


def _context_payload(context: WeekCoherenceContext) -> dict[str, Any]:
    return {
        "patch": context.patch.model_dump(),
        "validation": _jsonable(context.validation),
        "before_week": _jsonable(context.before_week),
        "after_week": _jsonable(context.after_week),
        "diff": _jsonable(context.diff),
        "deterministic_checks": _jsonable(context.deterministic_checks),
        "planning_contract": context.planning_contract,
        "week_mission": context.week_mission,
        "session_policies": list(context.session_policies),
        "recent_reality": context.recent_reality,
        "active_constraints": list(context.active_constraints),
    }


def _created_session_snapshot(operation: Any) -> dict[str, Any]:
    target_date = _parse_date(getattr(operation, "target_date", None))
    return {
        "id": None,
        "user_id": None,
        "day": _day_key(target_date) if target_date else "",
        "label": "",
        "scheduled_date": target_date.isoformat() if target_date else None,
        "sport_type": str(operation.new_sport_type or ""),
        "session_type": str(operation.new_session_type or ""),
        "session_title": str(operation.new_title or ""),
        "session_goal": str(operation.new_goal or ""),
        "session_note": "",
        "session_description": str(operation.new_description or ""),
        "duration_min": operation.new_duration_min,
        "intensity": str(operation.new_intensity or "easy"),
        "load_score": 3 if str(operation.new_intensity or "").lower() == "hard" else 1,
        "priority": "Normal",
        "nutrition_focus": "",
        "flexibility": "stable",
        "completion_status": "planned",
    }


def _apply_session_field_updates(target: dict[str, Any], operation: Any) -> None:
    updates = {
        "sport_type": operation.new_sport_type,
        "session_type": operation.new_session_type,
        "session_title": operation.new_title,
        "session_goal": operation.new_goal,
        "duration_min": operation.new_duration_min,
        "intensity": operation.new_intensity,
        "session_description": operation.new_description,
    }
    for key, value in updates.items():
        if value is not None:
            target[key] = value
    if operation.new_intensity is not None:
        target["load_score"] = 3 if str(operation.new_intensity).lower() == "hard" else min(_int(target.get("load_score"), default=1), 2)


def _build_diff(
    before_sessions: Sequence[dict[str, Any]],
    after_sessions: Sequence[dict[str, Any]],
    created_sessions: Sequence[dict[str, Any]],
    lightened_sessions: Sequence[dict[str, Any]],
) -> WeekPatchDiff:
    before_by_id = {item.get("id"): item for item in before_sessions if item.get("id") is not None}
    changed: list[dict[str, Any]] = []
    for after in after_sessions:
        session_id = after.get("id")
        if session_id is None:
            continue
        before = before_by_id.get(session_id)
        if before is not None and before != after:
            changed.append({"id": session_id, "before": before, "after": after})
    return WeekPatchDiff(
        changed_sessions=tuple(changed),
        created_sessions=tuple(deepcopy(tuple(created_sessions))),
        removed_or_lightened_sessions=tuple(deepcopy(tuple(lightened_sessions))),
    )


def _sort_sessions(sessions: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        (deepcopy(session) for session in sessions),
        key=lambda item: (_parse_date(item.get("scheduled_date")) or date.max, int(item.get("id") or 0)),
    )


def _find_session_dict(sessions: Sequence[dict[str, Any]], session_id: int | None) -> dict[str, Any] | None:
    if session_id is None:
        return None
    for session in sessions:
        if session.get("id") == session_id:
            return session
    return None


def _week_start(sessions: Sequence[dict[str, Any]]) -> date:
    dates = [_parse_date(session.get("scheduled_date")) for session in sessions]
    dates = [item for item in dates if item is not None]
    if not dates:
        today = date.today()
        return today.replace(day=today.day)
    first = min(dates)
    return first.fromordinal(first.toordinal() - first.weekday())


def _min_hard_gap_hours(sessions: Sequence[dict[str, Any]]) -> int | None:
    hard_dates = [
        item
        for item in (_parse_date(session.get("scheduled_date")) for session in sessions if _is_hard_session(session))
        if item is not None
    ]
    hard_dates.sort()
    if len(hard_dates) < 2:
        return None
    return min(int((current - previous).days * 24) for previous, current in zip(hard_dates, hard_dates[1:]))


def _is_hard_session(session: dict[str, Any]) -> bool:
    intensity = str(session.get("intensity") or "").strip().lower()
    return intensity in {"hard", "key", "threshold"} or _is_key_session(session)


def _is_key_session(session: dict[str, Any]) -> bool:
    priority = str(session.get("priority") or "").strip().lower()
    title = str(session.get("session_title") or "").strip().lower()
    session_type = str(session.get("session_type") or "").strip().lower()
    load_score = _int(session.get("load_score"), default=0)
    return (
        session_type in {"tempo", "threshold", "vo2", "interval", "intervals", "long", "race"}
        or load_score >= 4
        or any(token in f"{priority} {title}" for token in ("cle", "clé", "key", "fort", "qualite", "qualité"))
    )


def _is_recovery_session(session: dict[str, Any]) -> bool:
    sport = str(session.get("sport_type") or "").strip().lower()
    session_type = str(session.get("session_type") or "").strip().lower()
    return sport in {"rest", "off"} or session_type in {"rest", "recovery", "mobility"}


def _is_completed(session: dict[str, Any]) -> bool:
    return str(session.get("completion_status") or "").strip().lower() in {"done", "skipped", "canceled"}


def _empty_checks() -> DeterministicWeekChecks:
    return DeterministicWeekChecks(
        hard_sessions_before=0,
        hard_sessions_after=0,
        min_hard_gap_hours_after=None,
        recovery_sessions_before=0,
        recovery_sessions_after=0,
        key_session_ids_touched=(),
        completed_session_ids_touched=(),
        weekly_duration_delta_min=0,
        estimated_tss_delta=None,
        change_budget_remaining_before=None,
        change_budget_remaining_after=None,
        flags=(),
    )


def _recent_reality_payload(activities: Sequence[Any]) -> dict[str, Any] | None:
    if not activities:
        return None
    return {"activity_count": len(activities)}


def _as_dict(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "as_dict"):
        return value.as_dict()
    if hasattr(value, "__dataclass_fields__"):
        return {
            key: _jsonable(getattr(value, key))
            for key in value.__dataclass_fields__
        }
    return None


def _jsonable(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if hasattr(value, "as_dict"):
        return value.as_dict()
    if hasattr(value, "__dataclass_fields__"):
        return {key: _jsonable(getattr(value, key)) for key in value.__dataclass_fields__}
    return value


def _value(obj: Any, key: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            return None


def _as_date(value: Any) -> date | None:
    return _parse_date(value)


def _day_key(value: Any) -> str | None:
    parsed = _parse_date(value)
    if parsed is None:
        return None
    return ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")[parsed.weekday()]


def _int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
