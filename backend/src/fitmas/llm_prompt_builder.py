from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fitmas.conversation_prompting import ConversationPromptPolicy
from fitmas.time_context import render_time_context

_CONVERSATION_SYSTEM_TEXT = """\
Tu es FitMAS, un coach multisport IA.
Ton ton: clair, court, precis, confiant, chaleureux sans faux enthousiasme.
Tu parles comme un coach exigeant et calme, jamais comme un bot.
Tu reponds toujours en francais.
Tu ne dis jamais "Bravo continue comme ca" ou autre compliment generique.
Chaque message est contextuel et ancre dans un signal reel.
Tu tutoies toujours l'utilisateur.

Analyse le message utilisateur et decide quelle action prendre sur le calendrier d'entrainement reel.

Actions possibles:
- "move_session": deplacer une seance concrete a une date cible
- "swap_sessions": echanger deux seances concretes
- "lighten_day": alleger une seance concrete ou un jour (convertit en repos)
- "replace_session": transformer une seance (changer sport, type, duree, intensite, description)
- "update_session": modifier le titre ou l'objectif d'une seance concrete
- "no_change": aucune modification necessaire

Regles:
- les jours doivent etre en anglais: monday, tuesday, wednesday, thursday, friday, saturday, sunday
- quand une seance concrete est identifiable dans le calendrier date reel, privilegie toujours `target_session_id`
- pour un echange concret, renseigne `target_session_id` et `second_session_id`
- pour un deplacement concret, renseigne `target_date` au format ISO `YYYY-MM-DD`
- si l'utilisateur parle de aujourd'hui, demain, hier, ce soir, demain matin ou demande la date/l'heure/jour exact, raisonne a partir du contexte temporel fourni
- respecte cette hierarchie de verite:
  1. activite reelle persistée
  2. claim activite recent utilisateur
  3. correction utilisateur recente dans l'historique
  4. seance planifiee
  5. inference faible
- n'affirme jamais une duree ou un sport comme un fait si cela vient seulement du plan et qu'un claim utilisateur plus recent dit autre chose
- si une activite reelle existe aujourd'hui mais sur un autre sport que le plan, ne dis jamais "tu n'as rien fait"
- si la bonne reponse est purement temporelle ou explicative, garde `mutation_type = "no_change"` et reponds clairement dans `fitmas_message`
- avec `no_change`, tu ne promets jamais une modification non appliquee
- si l'utilisateur pose une question factuelle sur l'historique, le planning, la date, ou une seance, reponds en 1-2 phrases max, sans jugement, sans recadrage non demande

Exemples:
- "mardi c'est mort, je bascule sur jeudi" -> move_session
- "mercredi j'ai une grosse journee" -> lighten_day
- "echange samedi et dimanche" -> swap_sessions
- "jeudi je prefere faire du fractionne" -> update_session
- "j'ai mal a l'epaule droite" -> replace_session
- "je suis claque, pas envie de fractionne" -> replace_session
- "ok ca me va" -> no_change
- "on est quel jour exactement ?" -> no_change
- "c'est pas ce qui est sur mon planning dans l'app" -> no_change

Tu reponds UNIQUEMENT avec un JSON valide contenant exactement ces champs:
- mutation_type
- target_session_id
- second_session_id
- target_date
- from_day
- to_day
- new_title
- new_goal
- new_sport_type
- new_session_type
- new_duration_min
- new_intensity
- new_description
- rationale
- fitmas_message

Pas de markdown. Pas de texte autour du JSON.\
"""


@dataclass(frozen=True, slots=True)
class ConversationPromptBundle:
    system: list[dict[str, Any]]
    prompt: str
    history_messages_used: int


def build_conversation_prompt_bundle(
    *,
    user_text: str,
    prompt_policy: ConversationPromptPolicy,
    time_block: str,
    profile_summary: str | None = None,
    plan_summary: str,
    timeline_summary: str | None,
    execution_summary: str | None,
    temporal_summary: str | None,
    activity_claim_summary: str | None,
    signal_summary: str | None,
    conversation_history: list[dict[str, Any]] | None,
    coach_context: dict[str, Any] | None,
    selected_facts: list[str],
) -> ConversationPromptBundle:
    profile_block = ""
    if profile_summary:
        profile_block = f"\nProfil resume:\n{profile_summary}\n"

    history_block = ""
    history_messages_used = 0
    if conversation_history:
        recent = conversation_history[-prompt_policy.history_limit :]
        history_messages_used = len(recent)
        lines = []
        for msg in recent:
            prefix = "Utilisateur" if msg["role"] == "user" else "FitMAS"
            lines.append(f"{prefix}: {msg['text']}")
        if lines:
            history_block = "\nHistorique recent:\n" + "\n".join(lines) + "\n"

    coach_block = ""
    if coach_context and prompt_policy.include_coach_context:
        coach_block = (
            "\nContexte coach:\n"
            f"- nom: {coach_context.get('coach_name', 'FitMAS')}\n"
            f"- style: {coach_context.get('coach_style', 'direct')}\n"
            f"- relation: {coach_context.get('coach_relationship', '')}\n"
            f"- fait bien: {coach_context.get('coach_do', '')}\n"
            f"- ne fait jamais: {coach_context.get('coach_dont', '')}\n"
            f"- ame: {coach_context.get('coach_soul', '')}\n"
            f"- session du jour id: {coach_context.get('today_session_id')}\n"
        )

    facts_block = ""
    if selected_facts and prompt_policy.include_facts:
        facts_block = (
            "\nMemoire utile (elements high/medium a prendre en compte dans tes decisions):\n"
            + "\n".join(f"- {fact}" for fact in selected_facts)
            + "\n"
        )

    timeline_block = ""
    if timeline_summary and prompt_policy.include_timeline:
        timeline_block = f"\nCalendrier date reel:\n{timeline_summary}\n"

    execution_block = ""
    if execution_summary and prompt_policy.include_execution:
        execution_block = f"\n{execution_summary}\n"

    temporal_block = ""
    if temporal_summary and prompt_policy.include_temporal:
        temporal_block = f"\n{temporal_summary}\n"

    claim_block = ""
    if activity_claim_summary and prompt_policy.include_claim:
        claim_block = f"\n{activity_claim_summary}\n"

    signal_block = ""
    if signal_summary and prompt_policy.include_signals:
        signal_block = f"\n{signal_summary}\n"

    plan_anchor = ""
    if prompt_policy.include_plan_summary:
        plan_anchor = f"Repere legacy semaine courante:\n{plan_summary}\n"

    prompt = f"""{time_block}
Source de vérité planning conversationnelle: calendrier daté / app.
Ignore tout repère hebdo legacy si le calendrier daté dit autre chose.
{plan_anchor}
{timeline_block}
{execution_block}{temporal_block}{claim_block}{signal_block}
{profile_block}
{coach_block}{facts_block}
{history_block}
Nouveau message de l'utilisateur:
{user_text}"""

    return ConversationPromptBundle(
        system=[
            {
                "type": "text",
                "text": _CONVERSATION_SYSTEM_TEXT,
                "cache_control": {"type": "ephemeral", "ttl": "1h"},
            }
        ],
        prompt=prompt,
        history_messages_used=history_messages_used,
    )


def render_conversation_time_block(time_context: dict[str, str]) -> str:
    return render_time_context(time_context)
