from __future__ import annotations

import json
from datetime import date, datetime

from sqlalchemy.orm import Session

from fitmas.core import orm as s
from fitmas.domain.coaching.adaptation_log import AdaptationLogEntry, _impact_label, _mission_label, _reason_label
from fitmas.domain.planning.adaptation_decision import DecisionReasonCode, TrajectoryImpact, WeekMissionStatus


def to_domain_adaptation_event(record: s.AdaptationEventRecord) -> AdaptationLogEntry:
    reason_code = DecisionReasonCode(str(record.reason_code or DecisionReasonCode.LOGISTICS_CONFLICT.value))
    week_mission_status = WeekMissionStatus(str(record.week_mission_status or WeekMissionStatus.UNCHANGED.value))
    trajectory_impact = TrajectoryImpact(str(record.trajectory_impact or TrajectoryImpact.LOW.value))
    return AdaptationLogEntry(
        created_at=record.created_at.isoformat() if record.created_at else None,
        reason_code=record.reason_code,
        reason_label=_reason_label(reason_code),
        adaptation_level=record.adaptation_level,
        week_mission_status=record.week_mission_status,
        mission_label=_mission_label(week_mission_status),
        trajectory_impact=record.trajectory_impact,
        impact_label=_impact_label(trajectory_impact),
        scenario_type=record.scenario_type,
        mutation_type=record.mutation_type,
        summary=record.summary,
        what_changed=record.what_changed,
        what_protected=record.what_protected,
        user_message=record.user_message,
        source_text=record.source_text,
        change_cost=int(record.change_cost or 0),
        stability_penalty=float(record.stability_penalty or 0.0),
        protected_session_ids=tuple(int(value) for value in _json_loads_list(record.protected_session_ids_json)),
    )


def add_adaptation_event(db: Session, user_id: int, entry: AdaptationLogEntry) -> s.AdaptationEventRecord:
    row = s.AdaptationEventRecord(
        user_id=user_id,
        reason_code=entry.reason_code,
        adaptation_level=entry.adaptation_level,
        week_mission_status=entry.week_mission_status,
        trajectory_impact=entry.trajectory_impact,
        scenario_type=entry.scenario_type,
        mutation_type=entry.mutation_type,
        summary=entry.summary,
        what_changed=entry.what_changed,
        what_protected=entry.what_protected,
        user_message=entry.user_message,
        source_text=entry.source_text,
        change_cost=entry.change_cost,
        stability_penalty=entry.stability_penalty,
        protected_session_ids_json=_json_dumps(list(entry.protected_session_ids)),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_latest_adaptation_event(db: Session, user_id: int) -> AdaptationLogEntry | None:
    row = (
        db.query(s.AdaptationEventRecord)
        .filter(s.AdaptationEventRecord.user_id == user_id)
        .order_by(s.AdaptationEventRecord.created_at.desc(), s.AdaptationEventRecord.id.desc())
        .first()
    )
    return to_domain_adaptation_event(row) if row else None


def get_recent_adaptation_events(db: Session, user_id: int, *, limit: int = 4) -> list[AdaptationLogEntry]:
    rows = (
        db.query(s.AdaptationEventRecord)
        .filter(s.AdaptationEventRecord.user_id == user_id)
        .order_by(s.AdaptationEventRecord.created_at.desc(), s.AdaptationEventRecord.id.desc())
        .limit(limit)
        .all()
    )
    return [to_domain_adaptation_event(row) for row in rows]


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, default=_json_default)


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
