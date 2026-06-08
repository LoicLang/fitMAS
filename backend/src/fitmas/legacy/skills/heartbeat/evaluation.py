from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from fitmas.legacy.core import orm as s
from fitmas.legacy.core.time_context import get_local_now, hours_since

logger = logging.getLogger(__name__)

PROACTIVE_COOLDOWN_HOURS = 6
RECENT_EXCHANGE_HOURS = 2
MAX_PROACTIVE_MESSAGES_PER_DAY = 2
MODULE_GUARD_WINDOW = timedelta(minutes=2)
LAST_PROACTIVE_GUARD_AT: dict[int, datetime] = {}


@dataclass(frozen=True, slots=True)
class HeartbeatGate:
    allowed: bool
    reason: str | None = None


def check_module_guard(user_id: int, *, now: datetime | None = None) -> bool:
    current = now or datetime.now(timezone.utc)
    last_guard_at = LAST_PROACTIVE_GUARD_AT.get(user_id)
    if not last_guard_at:
        return True
    if current - last_guard_at < MODULE_GUARD_WINDOW:
        logger.info("Module guard active for user %s", user_id)
        return False
    return True


def reserve_module_guard(user_id: int, *, now: datetime | None = None) -> None:
    LAST_PROACTIVE_GUARD_AT[user_id] = now or datetime.now(timezone.utc)


def check_daily_cap(
    db: Session,
    user: s.User,
    *,
    max_messages: int = MAX_PROACTIVE_MESSAGES_PER_DAY,
) -> bool:
    local_now = get_local_now(user.timezone)
    local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    utc_midnight = local_midnight.astimezone(timezone.utc).replace(tzinfo=None)
    sent_today = (
        db.query(s.CoachMessage)
        .filter(
            s.CoachMessage.user_id == user.id,
            s.CoachMessage.role == "agent",
            s.CoachMessage.proactive.is_(True),
            s.CoachMessage.created_at >= utc_midnight,
        )
        .count()
    )
    if sent_today >= max_messages:
        logger.info("Daily proactive cap reached for user %s: %d/%d", user.id, sent_today, max_messages)
        return False
    return True


def check_cooldown(
    db: Session,
    user_id: int,
    *,
    cooldown_hours: float = PROACTIVE_COOLDOWN_HOURS,
) -> bool:
    last_agent_msg = (
        db.query(s.CoachMessage)
        .filter(
            s.CoachMessage.user_id == user_id,
            s.CoachMessage.role == "agent",
            s.CoachMessage.proactive.is_(True),
        )
        .order_by(s.CoachMessage.created_at.desc())
        .first()
    )
    if not last_agent_msg or not last_agent_msg.created_at:
        return True
    elapsed = hours_since(last_agent_msg.created_at)
    if elapsed is None:
        return True
    if elapsed < cooldown_hours:
        logger.info("Cooldown active: last agent msg %.1fh ago (need %.1fh)", elapsed, cooldown_hours)
        return False
    return True


def had_recent_exchange(
    db: Session,
    user_id: int,
    *,
    hours: float = RECENT_EXCHANGE_HOURS,
) -> bool:
    last_user_msg = (
        db.query(s.CoachMessage)
        .filter(s.CoachMessage.user_id == user_id, s.CoachMessage.role == "user")
        .order_by(s.CoachMessage.created_at.desc())
        .first()
    )
    if not last_user_msg or not last_user_msg.created_at:
        return False
    elapsed = hours_since(last_user_msg.created_at)
    if elapsed is None:
        return False
    return elapsed < hours


def evaluate_proactive_gate(
    db: Session,
    user: s.User,
    *,
    require_recent_exchange_gap: bool = False,
    recent_exchange_hours: float = RECENT_EXCHANGE_HOURS,
    cooldown_hours: float = PROACTIVE_COOLDOWN_HOURS,
) -> HeartbeatGate:
    if not check_module_guard(user.id):
        return HeartbeatGate(allowed=False, reason="module_guard")
    if not check_cooldown(db, user.id, cooldown_hours=cooldown_hours):
        return HeartbeatGate(allowed=False, reason="cooldown")
    if not check_daily_cap(db, user):
        return HeartbeatGate(allowed=False, reason="daily_cap")
    if require_recent_exchange_gap and had_recent_exchange(db, user.id, hours=recent_exchange_hours):
        return HeartbeatGate(allowed=False, reason="recent_exchange")
    return HeartbeatGate(allowed=True, reason=None)
