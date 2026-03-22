from __future__ import annotations

import logging
import os
from datetime import time as dt_time

import pytz
from telegram.ext import Application, ContextTypes

from fitmas.telegram_api import api_post
from fitmas.telegram_shared import (
    persist_draft_for_owner,
    persistable_plan_draft,
    resolve_owner_chat_id,
)

logger = logging.getLogger(__name__)


async def strava_sync_cron(context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        result = await api_post("/api/v0/strava/sync", {})
        imported = result.get("imported", 0)
        if imported:
            await signal_check_cron(context)
        logger.info("Strava cron sync: %d imported", imported)
    except Exception:
        logger.exception("Strava cron sync failed")


async def weekly_review_cron(context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = resolve_owner_chat_id()
    if not chat_id:
        logger.warning("No Telegram chat id available for weekly review")
        return

    try:
        from fitmas.heartbeat import weekly_review

        review_draft = weekly_review()
        if review_draft:
            await context.bot.send_message(chat_id=chat_id, text=review_draft.text, parse_mode=review_draft.parse_mode)
            persist_draft_for_owner(review_draft)
    except Exception:
        logger.exception("Weekly review cron failed")


async def send_new_week_plan(context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = resolve_owner_chat_id()
    if not chat_id:
        logger.warning("No Telegram chat id available for new week plan")
        return

    try:
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

        draft = morning_briefing()
        if draft:
            await context.bot.send_message(chat_id=chat_id, text=draft.text, parse_mode=draft.parse_mode)
            persist_draft_for_owner(draft)
        else:
            logger.info("Morning briefing returned None (cooldown or no session)")
    except Exception:
        logger.exception("Failed to send morning briefing")


async def signal_check_cron(context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = resolve_owner_chat_id()
    if not chat_id:
        return

    try:
        from fitmas.heartbeat import signal_check

        draft = signal_check()
        if draft:
            await context.bot.send_message(chat_id=chat_id, text=draft.text, parse_mode=draft.parse_mode)
            persist_draft_for_owner(draft)
            logger.info("Signal check sent a message")
        else:
            logger.info("Signal check: no actionable signals")
    except Exception:
        logger.exception("Signal check cron failed")


async def send_pre_session_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = resolve_owner_chat_id()
    if not chat_id:
        logger.warning("No Telegram chat id available, skipping pre-session reminder")
        return

    try:
        from fitmas.heartbeat import pre_session_reminder

        draft = pre_session_reminder()
        if draft:
            await context.bot.send_message(chat_id=chat_id, text=draft.text, parse_mode=draft.parse_mode)
            persist_draft_for_owner(draft)
        else:
            logger.info("Pre-session reminder returned None (cooldown, recent exchange, or no key session)")
    except Exception:
        logger.exception("Failed to send pre-session reminder")


def register_jobs(app: Application) -> None:
    job_queue = app.job_queue
    if not job_queue:
        return

    timezone = pytz.timezone(os.getenv("TZ", "Europe/Paris"))

    job_queue.run_daily(
        send_morning_briefing,
        time=dt_time(hour=7, minute=30, tzinfo=timezone),
        name="morning_briefing",
    )
    logger.info("Morning briefing scheduled at 07:30 %s", timezone)

    job_queue.run_daily(
        signal_check_cron,
        time=dt_time(hour=14, minute=0, tzinfo=timezone),
        name="signal_check",
    )
    logger.info("Signal check scheduled at 14:00 %s", timezone)

    job_queue.run_daily(
        send_pre_session_reminder,
        time=dt_time(hour=18, minute=0, tzinfo=timezone),
        name="pre_session_reminder",
    )
    logger.info("Pre-session reminder scheduled at 18:00 %s", timezone)

    job_queue.run_repeating(
        strava_sync_cron,
        interval=7200,
        first=60,
        name="strava_sync",
    )
    logger.info("Strava sync scheduled every 2h")

    job_queue.run_daily(
        weekly_review_cron,
        time=dt_time(hour=20, minute=0, tzinfo=timezone),
        # python-telegram-bot v20+ uses 0=Sunday ... 6=Saturday.
        days=(0,),
        name="weekly_review",
    )
    logger.info("Weekly review scheduled Sunday 20:00 %s", timezone)

    job_queue.run_daily(
        send_new_week_plan,
        time=dt_time(hour=6, minute=0, tzinfo=timezone),
        # python-telegram-bot v20+ uses 0=Sunday ... 6=Saturday.
        days=(1,),
        name="new_week_plan",
    )
    logger.info("New week plan scheduled Monday 06:00 %s", timezone)
