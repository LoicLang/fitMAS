from __future__ import annotations

import json
from datetime import date, datetime

from sqlalchemy.orm import Session

from fitmas import schema as s
from fitmas.domain.athlete.fitness_snapshot import FitnessSnapshot
from fitmas.domain.athlete.readiness import ReadinessState
from fitmas.models import Profile


def to_pydantic_profile(user: s.User) -> Profile:
    return Profile(
        name=user.name,
        age=user.age,
        objective=user.primary_objective or user.objective,
        coaching_style=user.coach_soul or user.coaching_style,
        primary_objective=user.primary_objective,
        weekly_structure_notes=user.weekly_structure_notes,
        coach_name=user.coach_name,
        coach_style=user.coach_style,
        coach_relationship=user.coach_relationship,
        coach_do=user.coach_do,
        coach_dont=user.coach_dont,
        coach_soul=user.coach_soul,
        onboarding_status=user.onboarding_status,
        sports=[sport.sport_type for sport in user.sports if sport.active],
        constraints=[constraint.text for constraint in user.constraints],
        preferences=[preference.text for preference in user.preferences],
        integrations=["Strava", "Telegram", "Manual"],
    )


def get_user(db: Session) -> s.User:
    user = get_user_optional(db)
    if user is None:
        raise RuntimeError("No user in DB - onboarding required")
    return user


def get_user_optional(db: Session) -> s.User | None:
    return db.query(s.User).first()


def replace_user_lists(
    db: Session,
    user: s.User,
    *,
    sports: list[str],
    constraints: list[str],
    preferences: list[str],
) -> None:
    db.query(s.UserSport).filter(s.UserSport.user_id == user.id).delete()
    db.query(s.UserConstraint).filter(s.UserConstraint.user_id == user.id).delete()
    db.query(s.UserPreference).filter(s.UserPreference.user_id == user.id).delete()

    for index, sport in enumerate(sports):
        db.add(s.UserSport(user_id=user.id, sport_type=sport, priority_rank=index))
    for text in constraints:
        db.add(s.UserConstraint(user_id=user.id, text=text))
    for text in preferences:
        db.add(s.UserPreference(user_id=user.id, text=text))

    db.commit()


def to_domain_fitness_snapshot(row: s.FitnessSnapshotRecord) -> FitnessSnapshot:
    return FitnessSnapshot(
        user_id=row.user_id,
        date=row.snapshot_date,
        ctl=row.ctl,
        atl=row.atl,
        tsb=row.tsb,
        ramp_rate=row.ramp_rate,
        weekly_target_tss=row.weekly_target_tss,
        weekly_actual_tss=row.weekly_actual_tss,
        completion_rate_14d=row.completion_rate_14d,
        key_sessions_done_14d=row.key_sessions_done_14d,
        volume_sessions_done_14d=row.volume_sessions_done_14d,
        sport_ctl=_json_loads_dict(row.sport_ctl_json),
        sport_volume_hours=_json_loads_dict(row.sport_volume_hours_json),
    )


def to_domain_readiness_snapshot(row: s.ReadinessSnapshotRecord) -> ReadinessState:
    return ReadinessState(
        user_id=row.user_id,
        date=row.snapshot_date,
        physical=row.physical,
        mental=row.mental,
        logistical=row.logistical,
        injury_risk=row.injury_risk,
        risk_flags=tuple(_json_loads_list(row.risk_flags_json)),
        summary=row.summary,
    )


def get_latest_fitness_snapshot_record(db: Session, user_id: int) -> s.FitnessSnapshotRecord | None:
    return (
        db.query(s.FitnessSnapshotRecord)
        .filter(s.FitnessSnapshotRecord.user_id == user_id)
        .order_by(s.FitnessSnapshotRecord.snapshot_date.desc(), s.FitnessSnapshotRecord.id.desc())
        .first()
    )


def get_latest_readiness_snapshot_record(db: Session, user_id: int) -> s.ReadinessSnapshotRecord | None:
    return (
        db.query(s.ReadinessSnapshotRecord)
        .filter(s.ReadinessSnapshotRecord.user_id == user_id)
        .order_by(s.ReadinessSnapshotRecord.snapshot_date.desc(), s.ReadinessSnapshotRecord.id.desc())
        .first()
    )


def save_fitness_snapshot(db: Session, snapshot: FitnessSnapshot) -> s.FitnessSnapshotRecord:
    row = (
        db.query(s.FitnessSnapshotRecord)
        .filter(
            s.FitnessSnapshotRecord.user_id == snapshot.user_id,
            s.FitnessSnapshotRecord.snapshot_date == snapshot.date,
        )
        .first()
    )
    if row is None:
        row = s.FitnessSnapshotRecord(user_id=snapshot.user_id, snapshot_date=snapshot.date)
        db.add(row)

    row.ctl = snapshot.ctl
    row.atl = snapshot.atl
    row.tsb = snapshot.tsb
    row.ramp_rate = snapshot.ramp_rate
    row.weekly_target_tss = snapshot.weekly_target_tss
    row.weekly_actual_tss = snapshot.weekly_actual_tss
    row.completion_rate_14d = snapshot.completion_rate_14d
    row.key_sessions_done_14d = snapshot.key_sessions_done_14d
    row.volume_sessions_done_14d = snapshot.volume_sessions_done_14d
    row.sport_ctl_json = _json_dumps(snapshot.sport_ctl)
    row.sport_volume_hours_json = _json_dumps(snapshot.sport_volume_hours)
    db.commit()
    db.refresh(row)
    return row


def save_readiness_snapshot(db: Session, readiness: ReadinessState) -> s.ReadinessSnapshotRecord:
    row = (
        db.query(s.ReadinessSnapshotRecord)
        .filter(
            s.ReadinessSnapshotRecord.user_id == readiness.user_id,
            s.ReadinessSnapshotRecord.snapshot_date == readiness.date,
        )
        .first()
    )
    if row is None:
        row = s.ReadinessSnapshotRecord(user_id=readiness.user_id, snapshot_date=readiness.date)
        db.add(row)

    row.physical = readiness.physical
    row.mental = readiness.mental
    row.logistical = readiness.logistical
    row.injury_risk = readiness.injury_risk
    row.risk_flags_json = _json_dumps(list(readiness.risk_flags))
    row.summary = readiness.summary
    db.commit()
    db.refresh(row)
    return row


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, default=_json_default)


def _json_loads_dict(raw_value: str) -> dict[str, float]:
    if not raw_value:
        return {}
    return {str(key): float(value) for key, value in json.loads(raw_value).items()}


def _json_loads_list(raw_value: str) -> list[str]:
    if not raw_value:
        return []
    return [str(value) for value in json.loads(raw_value)]


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)
