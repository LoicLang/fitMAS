from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import date
from typing import Any, Sequence

from sqlalchemy.orm import Session

from fitmas import mutations, plan_actions, repository as repo, schema as s
from fitmas.llm import MutationDecision


@dataclass(frozen=True, slots=True)
class PlanMutationServiceResult:
    plan_id: int
    applied_count: int
    attempted_count: int
    event_count: int = 0


@dataclass(frozen=True, slots=True)
class PlanSessionActionResult:
    action_type: str
    source: str
    session: s.ScheduledSession
    event_id: int | None = None


def apply_decisions_for_user(
    db: Session,
    *,
    user: s.User,
    decisions: Sequence[MutationDecision],
    source: str = "conversation",
    trigger_type: str = "mutation_decision",
    explained_to_user: bool = False,
    conversation_turn_id: int | None = None,
) -> PlanMutationServiceResult | None:
    if not decisions:
        return None

    plan = repo.get_active_plan(db, user.id)
    applied_count = 0
    event_count = 0
    for decision in decisions:
        pre_result, post_result = mutations.apply(
            db,
            plan.id,
            decision,
        )
        if pre_result.allowed and post_result is not None:
            applied_count += 1
            repo.add_plan_mutation_event(
                db,
                user_id=user.id,
                source=source,
                trigger_type=trigger_type,
                command_type=decision.mutation_type,
                target_session_ids=_decision_session_ids(decision),
                before_snapshot={},
                after_snapshot={},
                reason={"rationale": decision.rationale} if decision.rationale else {},
                impact=_jsonable_dict(post_result),
                user_visible_summary=decision.fitmas_message,
                explained_to_user=explained_to_user,
                conversation_turn_id=conversation_turn_id,
            )
            event_count += 1

    return PlanMutationServiceResult(
        plan_id=plan.id,
        applied_count=applied_count,
        attempted_count=len(decisions),
        event_count=event_count,
    )


def complete_session_for_user(
    db: Session,
    *,
    user: s.User,
    session_id: int,
    source: str,
) -> PlanSessionActionResult | None:
    before = _session_snapshot(repo.get_scheduled_session(db, user.id, session_id))
    session = plan_actions.complete_session(db, user=user, session_id=session_id)
    if session is None:
        return None
    event = _record_session_action(
        db,
        user=user,
        source=source,
        command_type="complete_session",
        session=session,
        before_snapshot=before,
    )
    return PlanSessionActionResult(action_type="complete_session", source=source, session=session, event_id=_event_id(event))


def skip_session_for_user(
    db: Session,
    *,
    user: s.User,
    session_id: int,
    source: str,
) -> PlanSessionActionResult | None:
    before = _session_snapshot(repo.get_scheduled_session(db, user.id, session_id))
    session = plan_actions.skip_session(db, user=user, session_id=session_id)
    if session is None:
        return None
    event = _record_session_action(
        db,
        user=user,
        source=source,
        command_type="skip_session",
        session=session,
        before_snapshot=before,
    )
    return PlanSessionActionResult(action_type="skip_session", source=source, session=session, event_id=_event_id(event))


def move_session_for_user(
    db: Session,
    *,
    user: s.User,
    session_id: int,
    target_date: date | None,
    source: str,
) -> PlanSessionActionResult | None:
    before = _session_snapshot(repo.get_scheduled_session(db, user.id, session_id))
    session = plan_actions.move_session(db, user=user, session_id=session_id, target_date=target_date)
    if session is None:
        return None
    event = _record_session_action(
        db,
        user=user,
        source=source,
        command_type="move_session",
        session=session,
        before_snapshot=before,
        reason={"target_date": target_date.isoformat()} if target_date else {},
    )
    return PlanSessionActionResult(action_type="move_session", source=source, session=session, event_id=_event_id(event))


def mark_session_completed_for_user(
    db: Session,
    *,
    user: s.User,
    session_id: int | None,
    source: str,
) -> PlanSessionActionResult | None:
    if session_id is None:
        return None
    before = _session_snapshot(repo.get_scheduled_session(db, user.id, session_id))
    session = plan_actions.complete_session(db, user=user, session_id=session_id)
    if session is None:
        return None
    event = _record_session_action(
        db,
        user=user,
        source=source,
        command_type="activity_completed",
        session=session,
        before_snapshot=before,
    )
    return PlanSessionActionResult(action_type="activity_completed", source=source, session=session, event_id=_event_id(event))


def mark_day_completed_for_user(
    db: Session,
    *,
    plan_id: int,
    day: str,
    source: str,
    user_id: int | None = None,
) -> bool:
    applied = repo.mark_day_completed(db, plan_id, day)
    if applied:
        repo.add_plan_mutation_event(
            db,
            user_id=user_id or 0,
            source=source,
            trigger_type="activity_completed",
            command_type="legacy_day_completed",
            target_session_ids=[],
            before_snapshot={"plan_id": plan_id, "day": day},
            after_snapshot={"plan_id": plan_id, "day": day, "completion_status": "done"},
            reason={},
            impact={},
            user_visible_summary="",
            explained_to_user=False,
            conversation_turn_id=None,
        )
    return applied


def _record_session_action(
    db: Session,
    *,
    user: s.User,
    source: str,
    command_type: str,
    session: s.ScheduledSession,
    before_snapshot: dict[str, Any],
    reason: dict[str, Any] | None = None,
) -> s.PlanMutationEventRecord:
    return repo.add_plan_mutation_event(
        db,
        user_id=user.id,
        source=source,
        trigger_type="session_action",
        command_type=command_type,
        target_session_ids=[session.id],
        before_snapshot=before_snapshot,
        after_snapshot=_session_snapshot(session),
        reason=reason or {},
        impact={},
        user_visible_summary="",
        explained_to_user=False,
        conversation_turn_id=None,
    )


def _decision_session_ids(decision: MutationDecision) -> list[int]:
    ids = []
    if decision.target_session_id is not None:
        ids.append(int(decision.target_session_id))
    if decision.second_session_id is not None:
        ids.append(int(decision.second_session_id))
    return ids


def _session_snapshot(session: s.ScheduledSession | None) -> dict[str, Any]:
    if session is None:
        return {}
    scheduled_date = getattr(session, "scheduled_date", None)
    return {
        "id": getattr(session, "id", None),
        "day": getattr(session, "day", None),
        "scheduled_date": scheduled_date.isoformat() if scheduled_date else None,
        "sport_type": getattr(session, "sport_type", None),
        "session_type": getattr(session, "session_type", None),
        "session_title": getattr(session, "session_title", None),
        "duration_min": getattr(session, "duration_min", None),
        "completion_status": getattr(session, "completion_status", None),
    }


def _jsonable_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if hasattr(value, "as_dict"):
        return dict(value.as_dict())
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "__dict__"):
        return {key: item for key, item in vars(value).items() if not key.startswith("_")}
    return {"value": str(value)}


def _event_id(event: Any) -> int | None:
    value = getattr(event, "id", None)
    return int(value) if value is not None else None
