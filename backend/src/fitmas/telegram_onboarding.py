from __future__ import annotations

import logging

from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import (
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from fitmas.telegram_api import api_post
from fitmas.telegram_shared import SPORT_EMOJIS

logger = logging.getLogger(__name__)

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
    await update.message.reply_text("Style general du coach ?", reply_markup=keyboard)
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
    return await send_preview(update, context)


async def onboarding_preview(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    answer = update.message.text.strip()
    previews: list[str] = context.user_data.get("coach_preview", [])

    if answer in {"1", "2", "3"}:
        index = int(answer) - 1
        if not previews or index >= len(previews):
            await update.message.reply_text(
                "Je n'ai pas de preview a ce numero. Reessaie avec 1, 2 ou 3, "
                "ou ecris un ajustement libre."
            )
            return ONBOARD_PREVIEW
        chosen = previews[index]
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
    return await send_preview(update, context)


async def onboarding_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    answer = update.message.text.strip().lower()
    if answer == "restart":
        return await cmd_start(update, context)
    if answer != "go":
        await update.message.reply_text("Reponds `go` pour generer, ou `restart` pour repartir.")
        return ONBOARD_CONFIRM

    payload = build_onboarding_payload(update, context)
    try:
        result = await api_post("/api/v0/onboard", payload)
    except Exception:
        logger.exception("Error during onboarding")
        await update.message.reply_text("Je n'ai pas pu generer ton setup. Reessaie /start.")
        return ConversationHandler.END

    week = result["week_plan"]
    lines = [result["recap"], "", f"*{week['intention']}*", week["summary"], ""]
    for day in week["days"]:
        emoji = SPORT_EMOJIS.get(day.get("sport_type", "rest"), "⚪")
        lines.append(f"{emoji} *{day['label']}* — {day['session_title']}")
    lines.append("")
    lines.append("/plan pour revoir la semaine. /today pour le point du jour.")
    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    context.user_data.clear()
    return ConversationHandler.END


async def onboarding_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "On coupe ici. Relance /start quand tu veux.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


async def send_preview(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    payload = build_onboarding_payload(update, context)
    preview = await api_post("/api/v0/onboard/preview", payload)
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


def build_onboarding_payload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> dict:
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


def build_onboarding_handler() -> ConversationHandler:
    return ConversationHandler(
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
