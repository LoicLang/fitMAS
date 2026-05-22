"""Shared activity query helpers used by heartbeat, signals, and other modules."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Sequence

from sqlalchemy.orm import Session

from fitmas import repository as repo, schema as s
from fitmas.domain.execution.claims import ActivityClaim, extract_claims_from_facts
from fitmas.time_context import get_local_now, get_timezone


def activities_on_local_date(db: Session, user: s.User, *, target_date: date) -> list[s.Activity]:
    """Return activities whose local start date matches *target_date*."""
    timezone = get_timezone(user.timezone)
    matched: list[s.Activity] = []
    for activity in repo.get_activities(db, user.id, limit=120):
        if activity.started_at is None:
            continue
        started_at = activity.started_at
        if started_at.tzinfo is None:
            local_date = started_at.date()
        else:
            local_date = started_at.astimezone(timezone).date()
        if local_date == target_date:
            matched.append(activity)
    return matched


def claimed_activities_on_local_date(
    db: Session, user: s.User, *, target_date: date,
) -> Sequence[ActivityClaim]:
    """Return activity claims from facts for *target_date*."""
    facts = repo.get_active_memory_items(db, user.id, profile_limit=24, working_limit=48, total_limit=64)
    return extract_claims_from_facts(facts, target_date=target_date)


def activities_last_days(db: Session, user: s.User, *, days: int) -> list[s.Activity]:
    """Return activities from the last *days* days (timezone-aware)."""
    cutoff = get_local_now(user.timezone).date() - timedelta(days=max(0, days - 1))
    timezone = get_timezone(user.timezone)
    matched: list[s.Activity] = []
    for activity in repo.get_activities(db, user.id, limit=160):
        if activity.started_at is None:
            continue
        started_at = activity.started_at
        if started_at.tzinfo is None:
            local_date = started_at.date()
        else:
            local_date = started_at.astimezone(timezone).date()
        if local_date >= cutoff:
            matched.append(activity)
    return matched


def claimed_activities_last_days(
    db: Session, user: s.User, *, days: int,
) -> list[ActivityClaim]:
    """Return activity claims from facts for the last *days* days."""
    cutoff = get_local_now(user.timezone).date() - timedelta(days=max(0, days - 1))
    facts = repo.get_active_memory_items(db, user.id, profile_limit=24, working_limit=64, total_limit=80)
    return [
        claim
        for claim in extract_claims_from_facts(facts)
        if claim.resolved_date_iso and date.fromisoformat(claim.resolved_date_iso) >= cutoff
    ]
