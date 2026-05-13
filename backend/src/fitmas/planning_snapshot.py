from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from typing import Any, Sequence

from sqlalchemy.orm import Session

from fitmas import repository as repo, schema as s
from fitmas.fact_memory import fact_is_current

REST_SPORTS = {"rest", "off"}
INACTIVE_STATUSES = {"resolved", "superseded", "stale", "archived", "closed"}


@dataclass(frozen=True, slots=True)
class PlanningSnapshotItem:
    ref: str
    session_id: int
    scheduled_date: str
    sport_type: str
    session_type: str
    role: str
    title: str
    goal: str
    description: str
    duration_min: int | None
    intensity: str
    load_score: int
    load_kind: str
    unscored_reason: str | None
    status: str
    movability: str


@dataclass(frozen=True, slots=True)
class PlanningSnapshotDay:
    date: str
    day_kind: str
    is_full_rest: bool
    load_score: int
    load_kind: str
    items: tuple[PlanningSnapshotItem, ...]


@dataclass(frozen=True, slots=True)
class PlanningSnapshotConstraint:
    kind: str
    key: str
    value: str
    status: str
    starts_on: str | None
    ends_on: str | None
    freshness: str


@dataclass(frozen=True, slots=True)
class PlanningSnapshot:
    snapshot_id: str
    user_id: int
    user_timezone: str
    horizon_start: str
    horizon_end: str
    days: tuple[PlanningSnapshotDay, ...]
    active_constraints: tuple[PlanningSnapshotConstraint, ...]
    diagnostics: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_planning_snapshot(
    db: Session,
    *,
    user: s.User,
    start_date: date,
    end_date: date,
    now: datetime | None = None,
) -> PlanningSnapshot:
    sessions = repo.get_scheduled_sessions_between_dates(
        db,
        user.id,
        start_date=start_date,
        end_date=end_date,
        limit=84,
    )
    facts = db.query(s.UserFact).filter(s.UserFact.user_id == user.id).all()
    working = db.query(s.WorkingMemoryEntry).filter(s.WorkingMemoryEntry.user_id == user.id).all()
    return build_planning_snapshot_from_records(
        user_id=user.id,
        timezone_name=user.timezone,
        start_date=start_date,
        end_date=end_date,
        sessions=sessions,
        memory_rows=[*facts, *working],
        now=now,
    )


def build_planning_snapshot_from_records(
    *,
    user_id: int,
    timezone_name: str | None,
    start_date: date,
    end_date: date,
    sessions: Sequence[Any],
    memory_rows: Sequence[Any],
    now: datetime | None = None,
) -> PlanningSnapshot:
    session_rows = [
        session
        for session in sessions
        if (session_date := _as_date(_value(session, "scheduled_date"))) is not None
        and start_date <= session_date <= end_date
    ]
    grouped: dict[date, list[Any]] = {day: [] for day in _date_range(start_date, end_date)}
    for session in session_rows:
        session_date = _as_date(_value(session, "scheduled_date"))
        if session_date in grouped:
            grouped[session_date].append(session)

    diagnostics: list[str] = []
    days = tuple(
        _snapshot_day(day, grouped.get(day, []), diagnostics=diagnostics)
        for day in _date_range(start_date, end_date)
    )
    constraints = tuple(
        constraint
        for row in memory_rows
        if (constraint := _snapshot_constraint(row, now=now)) is not None
    )

    stamp = (now or datetime.utcnow()).replace(microsecond=0).isoformat()
    return PlanningSnapshot(
        snapshot_id=f"user:{user_id}:{start_date.isoformat()}:{end_date.isoformat()}:{stamp}",
        user_id=user_id,
        user_timezone=timezone_name or "UTC",
        horizon_start=start_date.isoformat(),
        horizon_end=end_date.isoformat(),
        days=days,
        active_constraints=constraints,
        diagnostics=tuple(diagnostics),
    )


def _snapshot_day(day: date, sessions: Sequence[Any], *, diagnostics: list[str]) -> PlanningSnapshotDay:
    items = tuple(_snapshot_item(session, diagnostics=diagnostics) for session in sessions)
    total_load = sum(item.load_score for item in items)
    if not items:
        day_kind = "empty"
        load_kind = "zero"
    elif all(item.load_kind == "zero" and item.sport_type in REST_SPORTS for item in items):
        day_kind = "rest_total"
        load_kind = "zero"
    elif any(item.load_kind in {"unscored_recovery", "scored_low"} and item.role == "recovery" for item in items) and total_load <= 1:
        day_kind = "active_recovery"
        load_kind = "unscored_recovery" if any(item.load_kind == "unscored_recovery" for item in items) else "scored_low"
    else:
        day_kind = "training"
        load_kind = _load_kind(total_load)
    return PlanningSnapshotDay(
        date=day.isoformat(),
        day_kind=day_kind,
        is_full_rest=day_kind == "rest_total",
        load_score=total_load,
        load_kind=load_kind,
        items=items,
    )


def _snapshot_item(session: Any, *, diagnostics: list[str]) -> PlanningSnapshotItem:
    session_id = int(_value(session, "id") or 0)
    sport_type = str(_value(session, "sport_type") or "").strip().lower()
    session_type = str(_value(session, "session_type") or "").strip().lower()
    duration_min = _optional_int(_value(session, "duration_min"))
    load_score = max(_optional_int(_value(session, "load_score")) or 0, 0)
    description = str(_value(session, "session_description") or "")
    goal = str(_value(session, "session_goal") or "")
    has_session_content = bool(description.strip() or goal.strip() or duration_min)
    role = _role_for_session(sport_type=sport_type, session_type=session_type, load_score=load_score)
    load_kind = _load_kind(load_score)
    unscored_reason = None

    if sport_type in REST_SPORTS and has_session_content:
        diagnostics.append(f"REST_WITH_SESSION_CONTENT:session:{session_id}")
        role = "recovery"
        if load_score == 0:
            load_kind = "unscored_recovery"
            unscored_reason = "rest_with_session_content"
        else:
            load_kind = _load_kind(load_score)
    elif sport_type in REST_SPORTS:
        load_kind = "zero"

    return PlanningSnapshotItem(
        ref=f"session:{session_id}",
        session_id=session_id,
        scheduled_date=_date_iso(_value(session, "scheduled_date")) or "",
        sport_type=sport_type,
        session_type=session_type,
        role=role,
        title=str(_value(session, "session_title") or ""),
        goal=goal,
        description=description,
        duration_min=duration_min,
        intensity=str(_value(session, "intensity") or "").strip().lower(),
        load_score=load_score,
        load_kind=load_kind,
        unscored_reason=unscored_reason,
        status=str(_value(session, "completion_status") or "planned"),
        movability=str(_value(session, "flexibility") or "stable"),
    )


def _snapshot_constraint(row: Any, *, now: datetime | None) -> PlanningSnapshotConstraint | None:
    if str(_value(row, "category") or "").strip().lower() != "availability":
        return None
    if not fact_is_current(row, now=now):
        return None
    kind = str(_value(row, "signal_kind") or "availability").strip() or "availability"
    return PlanningSnapshotConstraint(
        kind=kind,
        key=str(_value(row, "key") or ""),
        value=str(_value(row, "value") or ""),
        status=str(_value(row, "status") or "open"),
        starts_on=_date_iso(_value(row, "valid_from")),
        ends_on=_exclusive_end_iso(_value(row, "valid_until") or _value(row, "expires_at")),
        freshness="confirmed" if bool(_value(row, "confirmed")) else "observed",
    )


def _role_for_session(*, sport_type: str, session_type: str, load_score: int) -> str:
    if sport_type in REST_SPORTS or session_type in {"rest", "recovery", "mobility"}:
        return "recovery"
    if load_score >= 4:
        return "key"
    if load_score <= 1:
        return "support"
    return "normal"


def _load_kind(load_score: int) -> str:
    if load_score <= 0:
        return "zero"
    if load_score <= 1:
        return "scored_low"
    if load_score <= 3:
        return "scored_moderate"
    return "scored_high"


def _date_range(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current = current + timedelta(days=1)


def _value(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError:
        return None


def _date_iso(value: Any) -> str | None:
    parsed = _as_date(value)
    return parsed.isoformat() if parsed is not None else None


def _exclusive_end_iso(value: Any) -> str | None:
    parsed = _as_date(value)
    if parsed is None:
        return None
    return (parsed - timedelta(days=1)).isoformat()


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
