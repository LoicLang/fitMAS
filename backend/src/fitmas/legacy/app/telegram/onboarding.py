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

from fitmas.legacy.app.telegram.api import api_post
from fitmas.legacy.app.telegram.shared import SPORT_EMOJIS

logger = logging.getLogger(__name__)

(
    ONBOARD_SPORTS,
    ONBOARD_OBJECTIVE,
    ONBOARD_GOAL_CONTEXT,
    ONBOARD_WEEK,
    ONBOARD_CURRENT_STATE,
    ONBOARD_PREFERENCES,
    ONBOARD_CONSTRAINTS,
    ONBOARD_COACH_NAME,
    ONBOARD_COACH_PRESET,
    ONBOARD_COACH_DO,
    ONBOARD_COACH_DONT,
    ONBOARD_PREVIEW,
    ONBOARD_CONFIRM,
) = range(13)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    context.user_data["name"] = update.effective_user.first_name or "Loic"
    await update.message.reply_text(
        "On repart proprement. On fait court.\n"
        "Reponses telegraphiques ok. Je sors un premier draft, puis on affine ensuite.\n\n"
        "D'abord: tu pratiques quoi en ce moment ?\n"
        "Ecris librement. Exemple: course, velo, natation, escalade, renfo.\n"
        "Si un sport compte plus, mets-le en premier.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ONBOARD_SPORTS


async def onboarding_sports(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["sports"] = [update.message.text]
    await update.message.reply_text(
        "Ton cap principal sur les prochaines semaines ?\n"
        "Exemple: preparer un 10k, retrouver du volume, reprendre proprement."
    )
    return ONBOARD_OBJECTIVE


async def onboarding_objective(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["primary_objective"] = update.message.text.strip()
    await update.message.reply_text(
        "Tu as une date, une course, ou juste une direction ?\n"
        "Exemple: trail dans 7 semaines, pas de course mais envie de construire."
    )
    return ONBOARD_GOAL_CONTEXT


async def onboarding_goal_context(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["goal_context"] = update.message.text.strip()
    await update.message.reply_text(
        "Raconte-moi ta vraie semaine.\n"
        "Jours fiables, jours fragiles, meilleur creneau, sortie longue ideale."
    )
    return ONBOARD_WEEK


async def onboarding_week(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["weekly_structure_notes"] = update.message.text.strip()
    await update.message.reply_text(
        "Tu en es ou en ce moment, en vrai ?\n"
        "Volume recent, fatigue, blessure, reprise, sport le plus solide."
    )
    return ONBOARD_CURRENT_STATE


async def onboarding_current_state(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["current_state_notes"] = update.message.text.strip()
    await update.message.reply_text(
        "Tu as des preferences fortes a respecter des le debut ?\n"
        "Exemple: matin > soir, trail > route, renfo court, pas deux intensites collees."
    )
    return ONBOARD_PREFERENCES


async def onboarding_preferences(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["preferences"] = [update.message.text.strip()]
    await update.message.reply_text(
        "Contraintes ou fragilites a respecter ?\n"
        "Boulot, famille, sommeil, douleur, materiel, piscine, etc."
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
        [["Direct", "Calme"], ["Analytique", "Exigeant"], ["Protecteur"]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await update.message.reply_text("Tu veux quel type de coach au quotidien ?", reply_markup=keyboard)
    return ONBOARD_COACH_PRESET


async def onboarding_coach_preset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["coach_preset"] = _coach_preset_from_text(update.message.text)
    await update.message.reply_text(
        "Qu'est-ce qu'il doit faire vraiment bien avec toi ?\n"
        "Exemple: recadrer vite, sentir quand alleger, rester precis.",
        reply_markup=ReplyKeyboardRemove(),
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
        context.user_data["coach_adjustment_notes"] = _append_adjustment_note(
            context.user_data.get("coach_adjustment_notes", ""),
            f"Phrase etalon: {chosen}",
        )
        setup_preview = context.user_data.get("setup_preview", [])
        lines = []
        if setup_preview:
            lines.append("Ce que j'ai compris:")
            lines.extend(f"- {line}" for line in setup_preview)
            lines.append("")
        lines.append(context.user_data["recap"])
        lines.append("")
        lines.append("Statut initial: first week draft.")
        lines.append("Si c'est bon, reponds `go`.")
        lines.append("Sinon reponds `restart`.")
        await update.message.reply_text(
            "\n".join(lines),
        )
        return ONBOARD_CONFIRM

    if answer.lower() == "restart":
        return await cmd_start(update, context)

    context.user_data["coach_adjustment_notes"] = _append_adjustment_note(
        context.user_data.get("coach_adjustment_notes", ""),
        answer,
    )
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
    calibration = result.get("calibration_status")
    if calibration:
        lines.extend([f"_Statut: {calibration['label']}_", ""])
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
    context.user_data["setup_preview"] = preview.get("setup_preview", [])
    lines: list[str] = []
    if context.user_data["setup_preview"]:
        lines.append("Ce que j'ai compris:")
        lines.extend(f"- {line}" for line in context.user_data["setup_preview"])
        lines.append("")
    lines.extend([preview["recap"], "", "Preview de voix:"])
    for index, message in enumerate(preview["coach_preview"], start=1):
        lines.append(f"{index}. {message}")
    lines.append("")
    if preview.get("calibration_status"):
        lines.append(f"Statut initial: {preview['calibration_status']['label']}")
        lines.append("")
    lines.append("Reponds `1`, `2`, `3`.")
    lines.append("Ou ecris un ajustement libre pour resserrer la voix.")
    await update.message.reply_text("\n".join(lines), reply_markup=ReplyKeyboardRemove())
    return ONBOARD_PREVIEW


def build_onboarding_payload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> dict:
    return {
        "name": context.user_data.get("name") or update.effective_user.first_name or "Loic",
        "primary_objective": context.user_data.get("primary_objective", ""),
        "goal_context": context.user_data.get("goal_context", ""),
        "sports": context.user_data.get("sports", []),
        "weekly_structure_notes": context.user_data.get("weekly_structure_notes", ""),
        "current_state_notes": context.user_data.get("current_state_notes", ""),
        "constraints": context.user_data.get("constraints", []),
        "preferences": context.user_data.get("preferences", []),
        "coach_name": context.user_data.get("coach_name", "FitMAS"),
        "coach_preset": context.user_data.get("coach_preset", "direct"),
        "coach_style": context.user_data.get("coach_style", ""),
        "coach_relationship": context.user_data.get("coach_relationship", ""),
        "coach_do": context.user_data.get("coach_do", ""),
        "coach_dont": context.user_data.get("coach_dont", ""),
        "coach_soul": context.user_data.get("coach_soul", ""),
        "coach_adjustment_notes": context.user_data.get("coach_adjustment_notes", ""),
        "telegram_chat_id": update.effective_chat.id if update.effective_chat else None,
    }


def _coach_preset_from_text(raw_value: str | None) -> str:
    key = (raw_value or "").strip().lower()
    mapping = {
        "direct": "direct",
        "calme": "calm",
        "analytique": "analytical",
        "exigeant": "demanding",
        "protecteur": "protective",
    }
    return mapping.get(key, "direct")


def _append_adjustment_note(existing: str, addition: str) -> str:
    note = addition.strip()
    if not note:
        return existing.strip()
    base = existing.strip()
    return f"{base}\n{note}".strip() if base else note


def build_onboarding_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        states={
            ONBOARD_SPORTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboarding_sports)],
            ONBOARD_OBJECTIVE: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboarding_objective)],
            ONBOARD_GOAL_CONTEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboarding_goal_context)],
            ONBOARD_WEEK: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboarding_week)],
            ONBOARD_CURRENT_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboarding_current_state)],
            ONBOARD_PREFERENCES: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboarding_preferences)],
            ONBOARD_CONSTRAINTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboarding_constraints)],
            ONBOARD_COACH_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboarding_coach_name)],
            ONBOARD_COACH_PRESET: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboarding_coach_preset)],
            ONBOARD_COACH_DO: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboarding_coach_do)],
            ONBOARD_COACH_DONT: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboarding_coach_dont)],
            ONBOARD_PREVIEW: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboarding_preview)],
            ONBOARD_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboarding_confirm)],
        },
        fallbacks=[CommandHandler("cancel", onboarding_cancel)],
        name="onboarding",
        persistent=True,
    )
