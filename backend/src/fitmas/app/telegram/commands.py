from __future__ import annotations

import logging
import os

import httpx
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from fitmas.app.telegram.api import api_get, api_post
from fitmas.app.telegram.debounce import (
    build_batched_text,
    consume_messages_with_ids,
    enqueue_message,
    has_pending_messages,
    is_in_flight,
    mark_in_flight,
)
from fitmas.app.telegram.shared import DAY_LABELS, SPORT_EMOJIS, persist_draft_for_owner

logger = logging.getLogger(__name__)

_DEBOUNCE_SECONDS = float(os.getenv("FITMAS_TELEGRAM_DEBOUNCE_SECONDS", "2.5"))


async def cmd_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        timeline = await api_get("/api/v0/timeline?limit=14")
        if not timeline:
            await update.message.reply_text("Pas de séance datée pour le moment.")
            return
        lines = ["*Planning daté*\n"]
        for session in timeline[:7]:
            emoji = SPORT_EMOJIS.get(session.get("sport_type", "rest"), "⚪")
            label = session.get("label") or DAY_LABELS.get(session.get("day", ""), session.get("day", ""))
            status = session.get("completion_status", "planned")
            lines.append(f"{emoji} *{label}* — {session['session_title']} _{status}_")
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
        today = await api_get("/api/v0/today")
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
            detail = ""
            try:
                detail = str(exc.response.json().get("detail") or "")
            except Exception:
                detail = ""
            if detail == "No onboarded user yet":
                await update.message.reply_text("Pas de profil encore. Lance /start.")
                return
            await update.message.reply_text("Rien de planifie aujourd'hui.")
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
    chat_id = int(update.effective_chat.id)
    message_id = getattr(update.message, "message_id", None)
    if context.job_queue is None:
        await _forward_message_immediately(update, user_text, chat_id=chat_id, message_id=message_id)
        return
    enqueue_message(chat_id, user_text, message_id=message_id)
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

    batched_messages, message_ids = consume_messages_with_ids(chat_id)
    if not batched_messages:
        return

    user_text = build_batched_text(batched_messages)
    if not user_text:
        return

    mark_in_flight(chat_id, True)
    try:
        result = await _post_message_with_idempotent_retry(
            _message_payload(user_text, chat_id=chat_id, message_ids=message_ids)
        )
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


async def _forward_message_immediately(
    update: Update,
    user_text: str,
    *,
    chat_id: int,
    message_id: int | None,
) -> None:
    try:
        result = await _post_message_with_idempotent_retry(
            _message_payload(user_text, chat_id=chat_id, message_ids=[message_id])
        )
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


async def _post_message_with_idempotent_retry(payload: dict[str, object]) -> dict:
    try:
        return await api_post("/api/v0/messages", payload)
    except httpx.HTTPStatusError as exc:
        if not _should_retry_message_post(payload, exc):
            raise
        logger.warning("Retrying message post after server error with client key")
        return await api_post("/api/v0/messages", payload)
    except httpx.RequestError:
        if not payload.get("client_message_key"):
            raise
        logger.warning("Retrying message post after lost response with client key")
        return await api_post("/api/v0/messages", payload)


def _should_retry_message_post(payload: dict[str, object], exc: httpx.HTTPStatusError) -> bool:
    return bool(payload.get("client_message_key")) and exc.response.status_code >= 500


def _message_payload(
    text: str,
    *,
    chat_id: int,
    message_ids: list[int | None],
) -> dict[str, object]:
    payload: dict[str, object] = {"text": text}
    key = _client_message_key(chat_id=chat_id, message_ids=message_ids)
    if key:
        payload["client_message_key"] = key
        payload["source"] = "telegram"
    return payload


def _client_message_key(*, chat_id: int, message_ids: list[int | None]) -> str | None:
    ids = [int(message_id) for message_id in message_ids if message_id is not None]
    if not ids:
        return None
    suffix = str(ids[0]) if len(ids) == 1 else f"{ids[0]}-{ids[-1]}"
    return f"telegram:{chat_id}:{suffix}"


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
        from fitmas.skills.heartbeat.heartbeat import morning_briefing

        draft = _manual_heartbeat_draft(morning_briefing)
        if draft:
            await update.message.reply_text(draft.text, parse_mode=draft.parse_mode)
            persist_draft_for_owner(draft)
            return
        await update.message.reply_text("Heartbeat no-op. Cause probable: pas de seance today ou cooldown proactif.")
    except Exception:
        logger.exception("Error in /heartbeat")
        await update.message.reply_text("Impossible de lancer le heartbeat.")


def _manual_heartbeat_draft(legacy_factory):
    import fitmas.skills.heartbeat.runtime_adapter as adapter

    result = adapter.run_heartbeat_trigger(
        trigger="morning_briefing",
        legacy_factory=legacy_factory,
        source="telegram",
        delivery_channel="telegram",
        manual=True,
        enforce_verifier=adapter.heartbeat_runtime_verifier_enforced(),
    )
    logger.info(
        "Manual heartbeat runtime outcome=%s sent=%s verifier_reason=%s",
        result.outcome.kind,
        bool(result.draft),
        result.verifier_reason,
    )
    return result.draft


def register_command_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("plan", cmd_plan))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("sync", cmd_sync))
    app.add_handler(CommandHandler("newweek", cmd_newweek))
    app.add_handler(CommandHandler("heartbeat", cmd_heartbeat))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
