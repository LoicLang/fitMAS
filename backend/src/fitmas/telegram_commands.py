from __future__ import annotations

import logging
import os

import httpx
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from fitmas.telegram_api import api_get, api_post
from fitmas.telegram_debounce import (
    build_batched_text,
    consume_messages,
    enqueue_message,
    has_pending_messages,
    is_in_flight,
    mark_in_flight,
)
from fitmas.telegram_shared import DAY_LABELS, SPORT_EMOJIS, persist_draft_for_owner
from fitmas.time_context import build_time_context

logger = logging.getLogger(__name__)

_DEBOUNCE_SECONDS = float(os.getenv("FITMAS_TELEGRAM_DEBOUNCE_SECONDS", "2.5"))


async def cmd_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        week = await api_get("/api/v0/week")
        lines = [f"*{week['intention']}*\n{week['summary']}\n"]
        for day in week["days"]:
            emoji = SPORT_EMOJIS.get(day.get("sport_type", "rest"), "⚪")
            lines.append(f"{emoji} *{day['label']}* — {day['session_title']}")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            await update.message.reply_text("Pas de profil encore. Lance /start.")
            return
        logger.exception("Error in /plan")
        await update.message.reply_text("Impossible de charger le plan.")
    except Exception:
        logger.exception("Error in /plan")
        await update.message.reply_text("Impossible de charger le plan.")


async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        profile = await api_get("/api/v0/profile")
        today_key = build_time_context(profile.get("timezone")).get("day_key") or build_time_context(None)["day_key"]
        today = await api_get(f"/api/v0/today/{today_key}")
        label = DAY_LABELS.get(today["day"], today["day"])
        emoji = SPORT_EMOJIS.get(today.get("sport_type", "rest"), "⚪")
        text = (
            f"*{emoji} {label} — {today['session_title']}*\n\n"
            f"{today['session_goal']}\n\n"
            f"Priorite: {today['priority']}\n"
            f"Nutrition: {today['nutrition_focus']}"
        )
        if today.get("change_notes"):
            text += "\n\n_Ce qui a change:_"
            for note in today["change_notes"]:
                text += f"\n• {note['title']} — {note['detail']}"
        await update.message.reply_text(text, parse_mode="Markdown")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            await update.message.reply_text("Pas de profil encore. Lance /start.")
            return
        logger.exception("Error in /today")
        await update.message.reply_text("Impossible de charger la journee.")
    except Exception:
        logger.exception("Error in /today")
        await update.message.reply_text("Impossible de charger la journee.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_text = update.message.text
    if not user_text or update.effective_chat is None:
        return
    if context.job_queue is None:
        await _forward_message_immediately(update, user_text)
        return
    chat_id = int(update.effective_chat.id)
    enqueue_message(chat_id, user_text)
    _schedule_debounced_flush(context, chat_id)


async def _flush_debounced_messages(context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.job is None:
        return
    chat_id = int(context.job.chat_id or (context.job.data or {}).get("chat_id") or 0)
    if chat_id <= 0:
        return
    if is_in_flight(chat_id):
        if has_pending_messages(chat_id):
            _schedule_debounced_flush(context, chat_id)
        return

    batched_messages = consume_messages(chat_id)
    if not batched_messages:
        return

    user_text = build_batched_text(batched_messages)
    if not user_text:
        return

    mark_in_flight(chat_id, True)
    try:
        result = await api_post("/api/v0/messages", {"text": user_text})
        reply = result.get("assistant_message", {}).get("text", "...")
        await context.bot.send_message(chat_id=chat_id, text=reply)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            await context.bot.send_message(chat_id=chat_id, text="Je n'ai pas encore ton setup. Lance /start.")
            return
        logger.exception("Error forwarding debounced message")
        await context.bot.send_message(
            chat_id=chat_id,
            text="Probleme de connexion avec FitMAS. Reessaie dans un instant.",
        )
    except Exception:
        logger.exception("Error forwarding debounced message")
        await context.bot.send_message(
            chat_id=chat_id,
            text="Probleme de connexion avec FitMAS. Reessaie dans un instant.",
        )
    finally:
        mark_in_flight(chat_id, False)
        if has_pending_messages(chat_id):
            _schedule_debounced_flush(context, chat_id)


def _schedule_debounced_flush(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    job_queue = context.job_queue
    if job_queue is None:
        return
    name = _debounce_job_name(chat_id)
    for job in job_queue.get_jobs_by_name(name):
        job.schedule_removal()
    job_queue.run_once(
        _flush_debounced_messages,
        when=_DEBOUNCE_SECONDS,
        data={"chat_id": chat_id},
        name=name,
        chat_id=chat_id,
    )


def _debounce_job_name(chat_id: int) -> str:
    return f"telegram_debounce:{chat_id}"


async def _forward_message_immediately(update: Update, user_text: str) -> None:
    try:
        result = await api_post("/api/v0/messages", {"text": user_text})
        reply = result.get("assistant_message", {}).get("text", "...")
        await update.message.reply_text(reply)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            await update.message.reply_text("Je n'ai pas encore ton setup. Lance /start.")
            return
        logger.exception("Error forwarding message")
        await update.message.reply_text("Probleme de connexion avec FitMAS. Reessaie dans un instant.")
    except Exception:
        logger.exception("Error forwarding message")
        await update.message.reply_text("Probleme de connexion avec FitMAS. Reessaie dans un instant.")


async def cmd_newweek(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        result = await api_post("/api/v0/week/regenerate", {})
        intention = result.get("intention", "")
        lines = [f"Nouvelle semaine generee.\n*{intention}*\n"]
        for day in result.get("days", []):
            emoji = SPORT_EMOJIS.get(day.get("sport_type", "rest"), "⚪")
            lines.append(f"{emoji} *{day['label']}* — {day['session_title']}")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    except Exception:
        logger.exception("Error in /newweek")
        await update.message.reply_text("Impossible de regenerer la semaine.")


async def cmd_sync(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        result = await api_post("/api/v0/strava/sync", {})
        if result.get("synced"):
            imported = result.get("imported", 0)
            if imported:
                await update.message.reply_text(f"Strava sync : {imported} nouvelle(s) activite(s) importee(s).")
            else:
                await update.message.reply_text("Strava sync OK. Rien de nouveau.")
            return
        await update.message.reply_text(f"Sync impossible : {result.get('reason', '?')}")
    except Exception:
        logger.exception("Error in /sync")
        await update.message.reply_text("Probleme de sync Strava.")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "*FitMAS — Commandes disponibles*\n\n"
        "/start — Relancer l'onboarding\n"
        "/today — Seance du jour\n"
        "/plan — Voir la semaine\n"
        "/newweek — Regenerer le plan\n"
        "/sync — Synchroniser Strava\n"
        "/help — Ce message\n\n"
        "Tu peux aussi ecrire librement : je comprends les demandes "
        "de decalage, d'allegement, les retours d'activite, etc."
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_heartbeat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        from fitmas.heartbeat import morning_briefing

        draft = morning_briefing()
        if draft:
            await update.message.reply_text(draft.text, parse_mode=draft.parse_mode)
            persist_draft_for_owner(draft)
            return
        await update.message.reply_text("Heartbeat no-op. Cause probable: pas de seance today ou cooldown proactif.")
    except Exception:
        logger.exception("Error in /heartbeat")
        await update.message.reply_text("Impossible de lancer le heartbeat.")


def register_command_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("plan", cmd_plan))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("sync", cmd_sync))
    app.add_handler(CommandHandler("newweek", cmd_newweek))
    app.add_handler(CommandHandler("heartbeat", cmd_heartbeat))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
