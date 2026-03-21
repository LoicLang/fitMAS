"""FitMAS Telegram bot — bridges Telegram to the FastAPI backend."""
from __future__ import annotations

import logging
import os
from datetime import datetime

import httpx
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    PicklePersistence,
    filters,
)
from fitmas import repository as repo
from fitmas.db import SessionLocal
from fitmas.time_context import build_time_context

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

SPORT_EMOJIS = {
    "running": "🏃",
    "cycling": "🚴",
    "swimming": "🏊",
    "climbing": "🧗",
    "strength": "💪",
    "rest": "🛌",
}

(
    ONBOARD_SPORTS,
    ONBOARD_OBJECTIVE,
    ONBOARD_WEEK,
    ONBOARD_LOAD,
    ONBOARD_CONSTRAINTS,
    ONBOARD_COACH_NAME,
    ONBOARD_COACH_STYLE,
    ONBOARD_COACH_RELATIONSHIP,
    ONBOARD_COACH_DO,
    ONBOARD_COACH_DONT,
    ONBOARD_COACH_SOUL,
    ONBOARD_PREVIEW,
    ONBOARD_CONFIRM,
) = range(13)


async def _api_get(path: str, *, retries: int = 3) -> dict:
    for attempt in range(retries):
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(f"{API_BASE}{path}", timeout=30)
                r.raise_for_status()
                return r.json()
        except httpx.ConnectError:
            if attempt < retries - 1:
                import asyncio
                await asyncio.sleep(2)
            else:
                raise


async def _api_post(path: str, data: dict, *, retries: int = 3) -> dict:
    for attempt in range(retries):
        try:
            async with httpx.AsyncClient() as client:
                r = await client.post(f"{API_BASE}{path}", json=data, timeout=60)
                r.raise_for_status()
                return r.json()
        except httpx.ConnectError:
            if attempt < retries - 1:
                import asyncio
                await asyncio.sleep(2)
            else:
                raise


def _resolve_chat_id() -> int | None:
    explicit = os.getenv("TELEGRAM_CHAT_ID")
    if explicit:
        try:
            return int(explicit)
        except ValueError:
            logger.warning("Invalid TELEGRAM_CHAT_ID env value: %s", explicit)

    db = SessionLocal()
    try:
        user = repo.get_user_optional(db)
        if user and user.telegram_chat_id:
            return int(user.telegram_chat_id)
        return None
    finally:
        db.close()


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    context.user_data["name"] = update.effective_user.first_name or "Loic"
    await update.message.reply_text(
        "On repart proprement.\n\n"
        "D'abord: tu pratiques quoi en ce moment ?\n"
        "Ecris librement. Exemple: course, velo, natation, escalade, renfo.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ONBOARD_SPORTS


async def cmd_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        week = await _api_get("/api/v0/week")
        lines = [f"*{week['intention']}*\n{week['summary']}\n"]
        for d in week["days"]:
            emoji = SPORT_EMOJIS.get(d.get("sport_type", "rest"), "⚪")
            lines.append(f"{emoji} *{d['label']}* — {d['session_title']}")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            await update.message.reply_text("Pas de profil encore. Lance /start.")
            return
    except Exception:
        logger.exception("Error in /plan")
        await update.message.reply_text("Impossible de charger le plan.")


async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        profile = await _api_get("/api/v0/profile")
        today_key = build_time_context(profile.get("timezone")).get("day_key", DAY_MAP[datetime.now().weekday()])
        today = await _api_get(f"/api/v0/today/{today_key}")
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
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            await update.message.reply_text("Je n'ai pas encore ton setup. Lance /start.")
            return
    except Exception:
        logger.exception("Error forwarding message")
        await update.message.reply_text("Probleme de connexion avec FitMAS. Reessaie dans un instant.")


async def onboarding_sports(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["sports"] = [update.message.text]
    await update.message.reply_text(
        "Ton objectif principal maintenant ?\n"
        "Exemple: preparer un 10k, garder une routine multisport, reprendre proprement."
    )
    return ONBOARD_OBJECTIVE


async def onboarding_objective(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["primary_objective"] = update.message.text.strip()
    await update.message.reply_text(
        "Raconte-moi ta vraie semaine.\n"
        "Jours bloques, jours fragiles, long session preferee, rythme global."
    )
    return ONBOARD_WEEK


async def onboarding_week(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["weekly_structure_notes"] = update.message.text.strip()
    await update.message.reply_text(
        "Charge recente / niveau du moment ?\n"
        "Simple. Exemple: course 3x/sem, velo le week-end, natation legere, escalade 2x."
    )
    return ONBOARD_LOAD


async def onboarding_load(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["preferences"] = [update.message.text.strip()]
    await update.message.reply_text(
        "Contraintes ou fragilites a respecter ?\n"
        "Blessure, sommeil, boulot, materiel, piscine, fatigue, etc."
    )
    return ONBOARD_CONSTRAINTS


async def onboarding_constraints(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["constraints"] = [update.message.text.strip()]
    await update.message.reply_text(
        "Comment tu veux appeler ce coach ?\n"
        "Tu peux donner un nom, ou juste ecrire FitMAS."
    )
    return ONBOARD_COACH_NAME


async def onboarding_coach_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["coach_name"] = update.message.text.strip() or "FitMAS"
    keyboard = ReplyKeyboardMarkup(
        [["direct", "calme"], ["data", "tough"]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await update.message.reply_text(
        "Style general du coach ?",
        reply_markup=keyboard,
    )
    return ONBOARD_COACH_STYLE


async def onboarding_coach_style(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    style_map = {
        "direct": "direct",
        "calme": "calm",
        "data": "data_driven",
        "tough": "tough_friend",
    }
    context.user_data["coach_style"] = style_map.get(update.message.text.strip().lower(), "direct")
    await update.message.reply_text(
        "Quelle relation tu veux avec lui ?\n"
        "Exemple: exigeant mais lucide, sec mais juste, tres humain sans blabla.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ONBOARD_COACH_RELATIONSHIP


async def onboarding_coach_relationship(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["coach_relationship"] = update.message.text.strip()
    await update.message.reply_text(
        "Qu'est-ce qu'il doit faire tres bien ?\n"
        "Exemple: recadrer vite, sentir quand alleger, rester lucide."
    )
    return ONBOARD_COACH_DO


async def onboarding_coach_do(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["coach_do"] = update.message.text.strip()
    await update.message.reply_text(
        "Qu'est-ce qu'il ne doit jamais faire ?\n"
        "Exemple: cheerleader, phrases creuses, culpabiliser, parler pour rien."
    )
    return ONBOARD_COACH_DONT


async def onboarding_coach_dont(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["coach_dont"] = update.message.text.strip()
    await update.message.reply_text(
        "Derniere couche: donne-lui une ame.\n"
        "Tu peux ecrire librement ce qui le rend humain et reconnaissable."
    )
    return ONBOARD_COACH_SOUL


async def onboarding_coach_soul(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["coach_soul"] = update.message.text.strip()
    return await _send_preview(update, context)


async def onboarding_preview(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    answer = update.message.text.strip()
    previews: list[str] = context.user_data.get("coach_preview", [])
    if answer in {"1", "2", "3"} and previews:
        chosen = previews[int(answer) - 1]
        context.user_data["coach_soul"] = (
            f"{context.user_data.get('coach_soul', '').strip()}\n"
            f"Phrase etalon: {chosen}"
        ).strip()
        await update.message.reply_text(
            f"{context.user_data['recap']}\n\n"
            "Si c'est bon, reponds `go`.\n"
            "Sinon reponds `restart`."
        )
        return ONBOARD_CONFIRM

    if answer.lower() == "restart":
        return await cmd_start(update, context)

    context.user_data["coach_soul"] = (
        f"{context.user_data.get('coach_soul', '').strip()}\n"
        f"Ajustement voix: {answer}"
    ).strip()
    await update.message.reply_text("Je resserre la voix.")
    return await _send_preview(update, context)


async def onboarding_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    answer = update.message.text.strip().lower()
    if answer == "restart":
        return await cmd_start(update, context)
    if answer != "go":
        await update.message.reply_text("Reponds `go` pour generer, ou `restart` pour repartir.")
        return ONBOARD_CONFIRM

    payload = _build_onboarding_payload(update, context)
    try:
        result = await _api_post("/api/v0/onboard", payload)
    except Exception:
        logger.exception("Error during onboarding")
        await update.message.reply_text("Je n'ai pas pu generer ton setup. Reessaie /start.")
        return ConversationHandler.END

    week = result["week_plan"]
    lines = [
        result["recap"],
        "",
        f"*{week['intention']}*",
        week["summary"],
        "",
    ]
    for day in week["days"]:
        emoji = SPORT_EMOJIS.get(day.get("sport_type", "rest"), "⚪")
        lines.append(f"{emoji} *{day['label']}* — {day['session_title']}")
    lines.append("")
    lines.append("/plan pour revoir la semaine. /today pour le point du jour.")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=ReplyKeyboardRemove())
    context.user_data.clear()
    return ConversationHandler.END


async def onboarding_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("On coupe ici. Relance /start quand tu veux.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


async def _send_preview(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    payload = _build_onboarding_payload(update, context)
    preview = await _api_post("/api/v0/onboard/preview", payload)
    context.user_data["coach_preview"] = preview["coach_preview"]
    context.user_data["recap"] = preview["recap"]
    lines = [preview["recap"], "", "Preview de voix:"]
    for index, message in enumerate(preview["coach_preview"], start=1):
        lines.append(f"{index}. {message}")
    lines.append("")
    lines.append("Reponds `1`, `2`, `3`.")
    lines.append("Ou ecris un ajustement libre pour resserrer la voix.")
    await update.message.reply_text("\n".join(lines), reply_markup=ReplyKeyboardRemove())
    return ONBOARD_PREVIEW


def _build_onboarding_payload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> dict:
    return {
        "name": context.user_data.get("name") or update.effective_user.first_name or "Loic",
        "primary_objective": context.user_data.get("primary_objective", ""),
        "sports": context.user_data.get("sports", []),
        "weekly_structure_notes": context.user_data.get("weekly_structure_notes", ""),
        "constraints": context.user_data.get("constraints", []),
        "preferences": context.user_data.get("preferences", []),
        "coach_name": context.user_data.get("coach_name", "FitMAS"),
        "coach_style": context.user_data.get("coach_style", "direct"),
        "coach_relationship": context.user_data.get("coach_relationship", ""),
        "coach_do": context.user_data.get("coach_do", ""),
        "coach_dont": context.user_data.get("coach_dont", ""),
        "coach_soul": context.user_data.get("coach_soul", ""),
        "telegram_chat_id": update.effective_chat.id if update.effective_chat else None,
    }


async def cmd_newweek(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Regenerate the weekly plan."""
    try:
        result = await _api_post("/api/v0/week/regenerate", {})
        intention = result.get("intention", "")
        lines = [f"Nouvelle semaine generee.\n*{intention}*\n"]
        for d in result.get("days", []):
            emoji = SPORT_EMOJIS.get(d.get("sport_type", "rest"), "⚪")
            lines.append(f"{emoji} *{d['label']}* — {d['session_title']}")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    except Exception:
        logger.exception("Error in /newweek")
        await update.message.reply_text("Impossible de regenerer la semaine.")


async def cmd_sync(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manually trigger a Strava sync."""
    try:
        result = await _api_post("/api/v0/strava/sync", {})
        if result.get("synced"):
            imported = result.get("imported", 0)
            if imported:
                await update.message.reply_text(f"Strava sync : {imported} nouvelle(s) activite(s) importee(s).")
            else:
                await update.message.reply_text("Strava sync OK. Rien de nouveau.")
        else:
            await update.message.reply_text(f"Sync impossible : {result.get('reason', '?')}")
    except Exception:
        logger.exception("Error in /sync")
        await update.message.reply_text("Probleme de sync Strava.")


async def cmd_heartbeat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Force a lightweight heartbeat run for debugging."""
    try:
        from fitmas.heartbeat import morning_briefing

        msg = morning_briefing()
        if msg:
            await update.message.reply_text(msg, parse_mode="Markdown")
            return
        await update.message.reply_text("Heartbeat no-op. Cause probable: pas de seance today ou cooldown proactif.")
    except Exception:
        logger.exception("Error in /heartbeat")
        await update.message.reply_text("Impossible de lancer le heartbeat.")


async def _strava_sync_cron(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Background Strava sync every 2 hours."""
    try:
        result = await _api_post("/api/v0/strava/sync", {})
        imported = result.get("imported", 0)
        if imported:
            chat_id = _resolve_chat_id()
            if chat_id:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"Strava sync automatique : {imported} activite(s) importee(s).",
                )
        logger.info("Strava cron sync: %d imported", imported)
    except Exception:
        logger.exception("Strava cron sync failed")


async def _weekly_review_cron(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sunday evening: weekly review + regenerate next week's plan."""
    chat_id = _resolve_chat_id()
    if not chat_id:
        logger.warning("No Telegram chat id available for weekly review")
        return

    try:
        from fitmas.heartbeat import weekly_review
        review_msg = weekly_review(regenerate=True)
        if review_msg:
            await context.bot.send_message(chat_id=chat_id, text=review_msg, parse_mode="Markdown")

        # Show the new plan
        week = await _api_get("/api/v0/week")
        lines = [f"\n*Nouvelle semaine:*\n*{week['intention']}*\n"]
        for d in week["days"]:
            emoji = SPORT_EMOJIS.get(d.get("sport_type", "rest"), "⚪")
            lines.append(f"{emoji} *{d['label']}* — {d['session_title']}")
        await context.bot.send_message(chat_id=chat_id, text="\n".join(lines), parse_mode="Markdown")
    except Exception:
        logger.exception("Weekly review cron failed")


async def send_morning_briefing(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send the daily briefing via heartbeat (LLM-generated, cooldown-aware)."""
    chat_id = _resolve_chat_id()
    if not chat_id:
        logger.warning("No Telegram chat id available, skipping morning briefing")
        return

    try:
        from fitmas.heartbeat import morning_briefing
        msg = morning_briefing()
        if msg:
            await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
        else:
            logger.info("Morning briefing returned None (cooldown or no session)")
    except Exception:
        logger.exception("Failed to send morning briefing")


async def send_pre_session_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send the evening reminder via heartbeat (LLM-generated, cooldown-aware)."""
    chat_id = _resolve_chat_id()
    if not chat_id:
        logger.warning("No Telegram chat id available, skipping pre-session reminder")
        return

    try:
        from fitmas.heartbeat import pre_session_reminder

        msg = pre_session_reminder()
        if msg:
            await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
        else:
            logger.info("Pre-session reminder returned None (cooldown, recent exchange, or no key session)")
    except Exception:
        logger.exception("Failed to send pre-session reminder")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN not set in environment")

    # Persist conversation state across restarts
    from pathlib import Path
    db_path = os.getenv("FITMAS_DB_PATH", "fitmas.db")
    persistence_path = str(Path(db_path).parent / "telegram_persistence.pickle")
    persistence = PicklePersistence(filepath=persistence_path)

    app = Application.builder().token(token).persistence(persistence).build()

    onboarding_handler = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        states={
            ONBOARD_SPORTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboarding_sports)],
            ONBOARD_OBJECTIVE: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboarding_objective)],
            ONBOARD_WEEK: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboarding_week)],
            ONBOARD_LOAD: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboarding_load)],
            ONBOARD_CONSTRAINTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboarding_constraints)],
            ONBOARD_COACH_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboarding_coach_name)],
            ONBOARD_COACH_STYLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboarding_coach_style)],
            ONBOARD_COACH_RELATIONSHIP: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboarding_coach_relationship)],
            ONBOARD_COACH_DO: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboarding_coach_do)],
            ONBOARD_COACH_DONT: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboarding_coach_dont)],
            ONBOARD_COACH_SOUL: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboarding_coach_soul)],
            ONBOARD_PREVIEW: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboarding_preview)],
            ONBOARD_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboarding_confirm)],
        },
        fallbacks=[CommandHandler("cancel", onboarding_cancel)],
        name="onboarding",
        persistent=True,
    )

    # Commands
    app.add_handler(onboarding_handler)
    app.add_handler(CommandHandler("plan", cmd_plan))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("sync", cmd_sync))
    app.add_handler(CommandHandler("newweek", cmd_newweek))
    app.add_handler(CommandHandler("heartbeat", cmd_heartbeat))

    # Free-text messages → coach
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Scheduled jobs
    job_queue = app.job_queue
    if job_queue:
        from datetime import time as dt_time
        import pytz
        tz = pytz.timezone(os.getenv("TZ", "Europe/Paris"))

        # Morning briefing (7:30 AM)
        job_queue.run_daily(
            send_morning_briefing,
            time=dt_time(hour=7, minute=30, tzinfo=tz),
            name="morning_briefing",
        )
        logger.info("Morning briefing scheduled at 07:30 %s", tz)

        job_queue.run_daily(
            send_pre_session_reminder,
            time=dt_time(hour=18, minute=0, tzinfo=tz),
            name="pre_session_reminder",
        )
        logger.info("Pre-session reminder scheduled at 18:00 %s", tz)

        # Strava sync every 2 hours
        job_queue.run_repeating(
            _strava_sync_cron,
            interval=7200,  # 2 hours
            first=60,  # start 60s after boot
            name="strava_sync",
        )
        logger.info("Strava sync scheduled every 2h")

        # Weekly review + new plan (Sunday 20:00)
        job_queue.run_daily(
            _weekly_review_cron,
            time=dt_time(hour=20, minute=0, tzinfo=tz),
            days=(6,),  # Sunday only
            name="weekly_review",
        )
        logger.info("Weekly review scheduled Sunday 20:00 %s", tz)

    logger.info("FitMAS Telegram bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    from pathlib import Path
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[3] / ".env")
    main()
