"""FitMAS Telegram bot — bridges Telegram to the FastAPI backend."""
from __future__ import annotations

import logging
import os
from datetime import datetime

import httpx
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

logger = logging.getLogger(__name__)

API_BASE = os.getenv("FITMAS_API_URL", "http://127.0.0.1:8000")

DAY_MAP = {
    0: "monday", 1: "tuesday", 2: "wednesday",
    3: "thursday", 4: "friday", 5: "saturday", 6: "sunday",
}

DAY_LABELS = {
    "monday": "Lundi", "tuesday": "Mardi", "wednesday": "Mercredi",
    "thursday": "Jeudi", "friday": "Vendredi", "saturday": "Samedi",
    "sunday": "Dimanche",
}


async def _api_get(path: str) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{API_BASE}{path}", timeout=30)
        r.raise_for_status()
        return r.json()


async def _api_post(path: str, data: dict) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{API_BASE}{path}", json=data, timeout=30)
        r.raise_for_status()
        return r.json()


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "FitMAS est la. Parle-moi comme tu parlerais a ton coach — "
        "je lis, j'ajuste, et je te montre ce qui change.\n\n"
        "/plan — voir ta semaine\n"
        "/today — voir la seance du jour\n"
        "Ou ecris simplement ce que tu veux."
    )


async def cmd_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        week = await _api_get("/api/v0/week")
        lines = [f"*{week['intention']}*\n{week['summary']}\n"]
        for d in week["days"]:
            emoji = "🔴" if "cle" in d["priority"].lower() or "fort" in d["priority"].lower() else "🟢" if "leger" in d["priority"].lower() or "flexible" in d["flexibility"].lower() else "⚪"
            lines.append(f"{emoji} *{d['label']}* — {d['session_title']}")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    except Exception:
        logger.exception("Error in /plan")
        await update.message.reply_text("Impossible de charger le plan.")


async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        today_key = DAY_MAP[datetime.now().weekday()]
        today = await _api_get(f"/api/v0/today/{today_key}")
        label = DAY_LABELS.get(today["day"], today["day"])
        text = (
            f"*{label} — {today['session_title']}*\n\n"
            f"{today['session_goal']}\n\n"
            f"Priorite: {today['priority']}\n"
            f"Nutrition: {today['nutrition_focus']}"
        )
        if today.get("change_notes"):
            text += "\n\n_Ce qui a change:_"
            for note in today["change_notes"]:
                text += f"\n• {note['title']} — {note['detail']}"
        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception:
        logger.exception("Error in /today")
        await update.message.reply_text("Impossible de charger la journee.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Forward any text message to the FitMAS API and relay the coach response."""
    user_text = update.message.text
    if not user_text:
        return

    try:
        result = await _api_post("/api/v0/messages", {"text": user_text})
        reply = result.get("assistant_message", {}).get("text", "...")
        await update.message.reply_text(reply)
    except Exception:
        logger.exception("Error forwarding message")
        await update.message.reply_text("Probleme de connexion avec FitMAS. Reessaie dans un instant.")


async def send_morning_briefing(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send the daily briefing to the configured chat. Called by APScheduler."""
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not chat_id:
        logger.warning("TELEGRAM_CHAT_ID not set, skipping morning briefing")
        return

    try:
        today_key = DAY_MAP[datetime.now().weekday()]
        today = await _api_get(f"/api/v0/today/{today_key}")
        label = DAY_LABELS.get(today["day"], today["day"])
        text = (
            f"Bonjour. Voila ta journee.\n\n"
            f"*{label} — {today['session_title']}*\n"
            f"{today['session_goal']}\n\n"
            f"Priorite: {today['priority']}"
        )
        if today.get("change_notes"):
            for note in today["change_notes"]:
                text += f"\n• {note['title']}"
        await context.bot.send_message(chat_id=int(chat_id), text=text, parse_mode="Markdown")
    except Exception:
        logger.exception("Failed to send morning briefing")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN not set in environment")

    app = Application.builder().token(token).build()

    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("plan", cmd_plan))
    app.add_handler(CommandHandler("today", cmd_today))

    # Free-text messages → coach
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Morning briefing cron (7:30 AM)
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if chat_id:
        job_queue = app.job_queue
        if job_queue:
            from datetime import time as dt_time
            import pytz
            tz = pytz.timezone(os.getenv("TZ", "Europe/Paris"))
            job_queue.run_daily(
                send_morning_briefing,
                time=dt_time(hour=7, minute=30, tzinfo=tz),
                name="morning_briefing",
            )
            logger.info("Morning briefing scheduled at 07:30 %s", tz)

    logger.info("FitMAS Telegram bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    from pathlib import Path
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[3] / ".env")
    main()
