from __future__ import annotations

import asyncio
import logging
import os
import random
from datetime import datetime, time as dt_time, timedelta

import pytz
from telegram.ext import Application, ContextTypes

from fitmas.telegram_api import api_post
from fitmas.telegram_shared import (
    persist_draft_for_owner,
    persistable_plan_draft,
    resolve_owner_chat_id,
)

logger = logging.getLogger(__name__)
_SEND_LOCK: asyncio.Lock | None = None


def _get_send_lock() -> asyncio.Lock:
    global _SEND_LOCK
    if _SEND_LOCK is None:
        _SEND_LOCK = asyncio.Lock()
    return _SEND_LOCK


def _jittered_time(hour: int, minute: int, timezone) -> dt_time:
    base = datetime(2000, 1, 1, hour, minute)
    jittered = base + timedelta(minutes=random.randint(-15, 15))
    return dt_time(hour=jittered.hour, minute=jittered.minute, tzinfo=timezone)


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
        from fitmas.heartbeat import _reserve_module_guard
        from fitmas.db import SessionLocal
        from fitmas import repository as repo
        db = SessionLocal()
        try:
            user = repo.get_user_optional(db)
            if user:
                _reserve_module_guard(user.id)
        finally:
            db.close()


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
        from fitmas.heartbeat import weekly_review

        await _send_serialized_draft(
            context,
            chat_id=chat_id,
            draft_factory=weekly_review,
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

    try:
        from fitmas.heartbeat import morning_briefing

        await _send_serialized_draft(
            context,
            chat_id=chat_id,
            draft_factory=morning_briefing,
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
        from fitmas.heartbeat import pre_session_reminder

        await _send_serialized_draft(
            context,
            chat_id=chat_id,
            draft_factory=pre_session_reminder,
            empty_log_message="Pre-session reminder returned None (cooldown, daily cap, recent exchange, or no key session)",
        )
    except Exception:
        logger.exception("Failed to send pre-session reminder")


def register_jobs(app: Application) -> None:
    job_queue = app.job_queue
    if not job_queue:
        return

    timezone = pytz.timezone(os.getenv("TZ", "Europe/Paris"))

    job_queue.run_daily(
        send_morning_briefing,
        time=_jittered_time(7, 30, timezone),
        name="morning_briefing",
    )
    logger.info("Morning briefing scheduled with jitter in %s", timezone)

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
