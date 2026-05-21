from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import random
from datetime import datetime, time as dt_time, timedelta
from typing import Callable, Mapping

import pytz
from telegram.ext import Application, ContextTypes

from fitmas.coach_messages import CoachDraft
from fitmas.telegram_api import api_post
from fitmas.telegram_shared import (
    persist_draft_for_owner,
    persistable_plan_draft,
    resolve_owner_chat_id,
)

logger = logging.getLogger(__name__)
_SEND_LOCK: asyncio.Lock | None = None


def _heartbeat_runtime_verifier_enforced() -> bool:
    import fitmas.skills.heartbeat.runtime_adapter as adapter

    return adapter.heartbeat_runtime_verifier_enforced()


def _get_send_lock() -> asyncio.Lock:
    global _SEND_LOCK
    if _SEND_LOCK is None:
        _SEND_LOCK = asyncio.Lock()
    return _SEND_LOCK


def _jittered_time(hour: int, minute: int, timezone) -> dt_time:
    base = datetime(2000, 1, 1, hour, minute)
    jittered = base + timedelta(minutes=random.randint(-15, 15))
    return dt_time(hour=jittered.hour, minute=jittered.minute, tzinfo=timezone)


def _daily_target_time(
    *,
    now: datetime,
    label: str,
    base_hour: int,
    base_minute: int,
    spread_minutes: int = 30,
) -> datetime:
    seed_input = f"{label}:{now.date().isoformat()}".encode()
    digest = hashlib.sha256(seed_input).digest()
    raw = int.from_bytes(digest[:4], "big")
    offset = (raw % ((spread_minutes * 2) + 1)) - spread_minutes
    return now.replace(hour=base_hour, minute=base_minute, second=0, microsecond=0) + timedelta(minutes=offset)


def _within_daily_send_window(
    *,
    now: datetime,
    label: str,
    base_hour: int,
    base_minute: int,
    spread_minutes: int = 30,
    grace_minutes: int = 12,
) -> bool:
    target = _daily_target_time(
        now=now,
        label=label,
        base_hour=base_hour,
        base_minute=base_minute,
        spread_minutes=spread_minutes,
    )
    return target <= now <= (target + timedelta(minutes=grace_minutes))


def _morning_briefing_window_status(
    *,
    now: datetime,
    already_sent_today: bool,
    base_hour: int = 7,
    base_minute: int = 30,
    spread_minutes: int = 30,
    grace_minutes: int = 12,
    catchup_until_hour: int = 10,
) -> str:
    """Return why the morning briefing should run or be skipped.

    The normal target window stays narrow, but dogfood should not lose the
    briefing completely if the interval scheduler misses the jittered window.
    """
    target = _daily_target_time(
        now=now,
        label="morning_briefing",
        base_hour=base_hour,
        base_minute=base_minute,
        spread_minutes=spread_minutes,
    )
    window_end = target + timedelta(minutes=grace_minutes)
    if target <= now <= window_end:
        return "target_window"
    if already_sent_today:
        return "already_sent"
    catchup_until = now.replace(hour=catchup_until_hour, minute=0, second=0, microsecond=0)
    if window_end < now <= catchup_until:
        return "catchup"
    return "outside_window"


def _has_proactive_message_today(timezone_name: str) -> bool:
    from datetime import timezone as dt_timezone

    from fitmas import repository as repo, schema as s
    from fitmas.db import SessionLocal

    timezone = pytz.timezone(timezone_name)
    local_now = datetime.now(timezone)
    local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    utc_midnight = local_midnight.astimezone(dt_timezone.utc).replace(tzinfo=None)
    db = SessionLocal()
    try:
        user = repo.get_user_optional(db)
        if user is None:
            return False
        return (
            db.query(s.CoachMessage)
            .filter(
                s.CoachMessage.user_id == user.id,
                s.CoachMessage.role == "agent",
                s.CoachMessage.proactive.is_(True),
                s.CoachMessage.created_at >= utc_midnight,
            )
            .count()
            > 0
        )
    finally:
        db.close()


async def _send_serialized_draft(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    draft_factory,
    empty_log_message: str,
) -> None:
    async with _get_send_lock():
        draft = draft_factory()
        if not draft:
            logger.info(empty_log_message)
            return
        await context.bot.send_message(chat_id=chat_id, text=draft.text, parse_mode=draft.parse_mode)
        # Persist and reserve module guard only AFTER successful Telegram send.
        # This prevents a failed send from blocking retries or marking a ghost message as sent.
        persist_draft_for_owner(draft)
        _reserve_heartbeat_guard_after_send()


def _reserve_heartbeat_guard_after_send() -> None:
    from fitmas import repository as repo
    from fitmas.db import SessionLocal
    from fitmas.skills.heartbeat.heartbeat import _reserve_module_guard

    db = SessionLocal()
    try:
        user = repo.get_user_optional(db)
        if user:
            _reserve_module_guard(user.id)
    finally:
        db.close()


def _heartbeat_draft_factory(
    trigger: str,
    legacy_factory: Callable[[], CoachDraft | None],
    *,
    metadata: Mapping[str, object] | None = None,
    user_id: int = 0,
    source: str = "scheduler",
    delivery_channel: str = "telegram",
    manual: bool = False,
) -> Callable[[], CoachDraft | None]:
    def _factory() -> CoachDraft | None:
        import fitmas.skills.heartbeat.runtime_adapter as adapter

        result = adapter.run_heartbeat_trigger(
            trigger=trigger,
            legacy_factory=legacy_factory,
            user_id=user_id,
            source=source,
            delivery_channel=delivery_channel,
            manual=manual,
            metadata=metadata,
            enforce_verifier=_heartbeat_runtime_verifier_enforced(),
        )
        _log_heartbeat_runtime_result(result)
        return result.draft

    return _factory


def _log_heartbeat_runtime_result(result) -> None:
    logger.info(
        "Heartbeat runtime trigger=%s outcome=%s sent=%s verifier_reason=%s",
        result.event.payload.get("trigger"),
        result.outcome.kind,
        bool(result.draft),
        result.verifier_reason,
    )


async def strava_sync_cron(context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        result = await api_post("/api/v0/strava/sync", {})
        imported = result.get("imported", 0)
        logger.info("Strava cron sync: %d imported", imported)
    except Exception:
        logger.exception("Strava cron sync failed")


async def memory_maintenance_cron(context: ContextTypes.DEFAULT_TYPE) -> None:
    from fitmas.db import SessionLocal
    from fitmas.memory_maintenance import run_memory_maintenance

    db = SessionLocal()
    try:
        result = run_memory_maintenance(db)
        logger.info(
            "Memory maintenance: users=%d working_archived=%d patterns_upserted=%d patterns_archived=%d",
            result.users_processed,
            result.working_entries_archived,
            result.patterns_upserted,
            result.patterns_archived,
        )
    except Exception:
        logger.exception("Memory maintenance cron failed")
    finally:
        db.close()


async def weekly_review_cron(context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = resolve_owner_chat_id()
    if not chat_id:
        logger.warning("No Telegram chat id available for weekly review")
        return

    try:
        from fitmas.skills.heartbeat.heartbeat import weekly_review

        await _send_serialized_draft(
            context,
            chat_id=chat_id,
            draft_factory=_heartbeat_draft_factory("weekly_review", weekly_review),
            empty_log_message="Weekly review returned None",
        )
    except Exception:
        logger.exception("Weekly review cron failed")


async def send_new_week_plan(context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = resolve_owner_chat_id()
    if not chat_id:
        logger.warning("No Telegram chat id available for new week plan")
        return

    try:
        async with _get_send_lock():
            week = await api_post("/api/v0/week/regenerate", {})
            draft = persistable_plan_draft(week)
            await context.bot.send_message(chat_id=chat_id, text=draft.text, parse_mode=draft.parse_mode)
            persist_draft_for_owner(draft)
    except Exception:
        logger.exception("New week plan cron failed")


async def send_morning_briefing(context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = resolve_owner_chat_id()
    if not chat_id:
        logger.warning("No Telegram chat id available, skipping morning briefing")
        return

    timezone = pytz.timezone(os.getenv("TZ", "Europe/Paris"))
    local_now = datetime.now(timezone)
    window_status = _morning_briefing_window_status(
        now=local_now,
        already_sent_today=_has_proactive_message_today(str(timezone)),
    )
    if window_status not in {"target_window", "catchup"}:
        logger.info("Morning briefing scheduler skipped — %s", window_status)
        return
    if window_status == "catchup":
        logger.warning("Morning briefing catch-up window active; target window was missed")

    try:
        from fitmas.skills.heartbeat.heartbeat import morning_briefing

        await _send_serialized_draft(
            context,
            chat_id=chat_id,
            draft_factory=_heartbeat_draft_factory(
                "morning_briefing",
                morning_briefing,
                metadata={"window_status": window_status},
            ),
            empty_log_message="Morning briefing returned None (cooldown, daily cap, or no session)",
        )
    except Exception:
        logger.exception("Failed to send morning briefing")


async def send_pre_session_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = resolve_owner_chat_id()
    if not chat_id:
        logger.warning("No Telegram chat id available, skipping pre-session reminder")
        return

    try:
        from fitmas.skills.heartbeat.heartbeat import pre_session_reminder

        await _send_serialized_draft(
            context,
            chat_id=chat_id,
            draft_factory=_heartbeat_draft_factory("pre_session_reminder", pre_session_reminder),
            empty_log_message="Pre-session reminder returned None (cooldown, daily cap, recent exchange, or no key session)",
        )
    except Exception:
        logger.exception("Failed to send pre-session reminder")


def register_jobs(app: Application) -> None:
    job_queue = app.job_queue
    if not job_queue:
        return

    timezone = pytz.timezone(os.getenv("TZ", "Europe/Paris"))

    job_queue.run_repeating(
        send_morning_briefing,
        interval=600,
        first=60,
        name="morning_briefing",
    )
    logger.info("Morning briefing scheduled as repeating morning window in %s", timezone)

    job_queue.run_daily(
        send_pre_session_reminder,
        time=_jittered_time(18, 0, timezone),
        name="pre_session_reminder",
    )
    logger.info("Pre-session reminder scheduled with jitter in %s", timezone)

    job_queue.run_repeating(
        strava_sync_cron,
        interval=7200,
        first=60,
        name="strava_sync",
    )
    logger.info("Strava sync scheduled every 2h")

    job_queue.run_repeating(
        memory_maintenance_cron,
        interval=21600,
        first=300,
        name="memory_maintenance",
    )
    logger.info("Memory maintenance scheduled every 6h")

    job_queue.run_daily(
        weekly_review_cron,
        time=_jittered_time(20, 0, timezone),
        # python-telegram-bot v20+ uses 0=Sunday ... 6=Saturday.
        days=(0,),
        name="weekly_review",
    )
    logger.info("Weekly review scheduled with jitter on Sunday in %s", timezone)

    job_queue.run_daily(
        send_new_week_plan,
        time=_jittered_time(6, 0, timezone),
        # python-telegram-bot v20+ uses 0=Sunday ... 6=Saturday.
        days=(1,),
        name="new_week_plan",
    )
    logger.info("New week plan scheduled with jitter on Monday in %s", timezone)
