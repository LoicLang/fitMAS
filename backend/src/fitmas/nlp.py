from __future__ import annotations

from fitmas.models import DayId, Extraction, Message, MessageReply, MessageRole


DAY_KEYWORDS = {
    DayId.MONDAY: ("lundi",),
    DayId.TUESDAY: ("mardi",),
    DayId.WEDNESDAY: ("mercredi",),
    DayId.THURSDAY: ("jeudi",),
    DayId.FRIDAY: ("vendredi",),
    DayId.SATURDAY: ("samedi",),
    DayId.SUNDAY: ("dimanche",),
}


def extract_reply(text: str) -> Extraction:
    lower = text.lower()
    availability: list[str] = []
    constraints: list[str] = []
    feeling: str | None = None
    confidence = 0.55
    needs_clarification = False

    for day, keywords in DAY_KEYWORDS.items():
        if any(keyword in lower for keyword in keywords):
            availability.append(day.value)

    if any(word in lower for word in ("pas bon", "mort", "charge", "diner", "bouge", "impossible")):
        constraints.append("schedule_constraint")
        confidence = 0.75

    if any(word in lower for word in ("lourd", "fatigue", "crame", "dur")):
        feeling = "fatigue"
        confidence = max(confidence, 0.75)

    if "cardio ok" in lower:
        feeling = "muscular_fatigue_more_than_cardio"
        confidence = max(confidence, 0.8)

    if "semaine prochaine" in lower or "je bouge beaucoup" in lower:
        constraints.append("next_week_uncertain")
        needs_clarification = True
        confidence = max(confidence, 0.7)

    if not constraints and not availability and not feeling:
        needs_clarification = True
        confidence = 0.35

    return Extraction(
        availability=availability,
        constraints=constraints,
        feeling=feeling,
        confidence=confidence,
        needs_clarification=needs_clarification,
    )


def generate_reply(user_text: str, extraction: Extraction) -> MessageReply:
    lower = user_text.lower()
    response = "Je garde ca en tete. Si ca change la semaine de maniere utile, je te le montre proprement."
    updated_day: DayId | None = None

    if "mardi" in lower and "jeudi" in lower:
        response = "Je vois le point. Je bouge la qualite a jeudi et je garde mercredi simple pour que le bloc reste propre."
        updated_day = DayId.THURSDAY
    elif "diner" in lower or "soir" in lower:
        response = "Ok, je lis ca comme une vraie contrainte de creneau. Je vais eviter de forcer la seance la-dessus."
    elif extraction.feeling == "fatigue":
        response = "Je note. Je vais rester un peu plus prudent sur la suite plutot que d'empiler de la charge."
    elif extraction.feeling == "muscular_fatigue_more_than_cardio":
        response = "Compris. Si le cardio est propre mais que les jambes sont lourdes, je protege surtout la recup musculaire."
    elif extraction.needs_clarification:
        response = "Je peux ajuster, mais j'ai besoin d'un point de plus. Tu sais deja quels jours sont les plus compliques ?"

    return MessageReply(
        user_message=Message(role=MessageRole.USER, text=user_text),
        extraction=extraction,
        assistant_message=Message(role=MessageRole.AGENT, text=response),
        day_updated=updated_day,
    )
