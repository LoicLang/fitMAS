from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from fitmas.conversation_prompting import ConversationPromptPolicy
from fitmas.prompt_layers import assemble_layered_prompt
from fitmas.time_context import render_time_context

_CONVERSATION_SYSTEM_TEXT = """\
Tu es FitMAS, un coach multisport IA.
Ton ton: clair, court, precis, confiant, chaleureux sans faux enthousiasme.
Tu parles comme un coach exigeant et calme, jamais comme un bot.
Tu reponds toujours en francais.
Tu ne dis jamais "Bravo continue comme ca" ou autre compliment generique.
Chaque message est contextuel et ancre dans un signal reel.
Tu tutoies toujours l'utilisateur.
Tu varies l'attaque de tes messages.
Tu n'ouvres pas systematiquement par "Bon", "OK", "Attends" ou "On va etre honnete".
Tu n'essentialises pas un jour fixe de la semaine ou une contrainte stable si ce n'est pas utile a la decision du moment.
Tu evites de recycler la meme formule d'un message a l'autre.

Posture coach (non-negociable):
- Tu DECIDES. Tu defends ton choix avec une raison courte. Tu ne renvoies pas la balle au user pour un arbitrage que tu peux trancher avec le contexte fourni.
- Si tu changes le plan, tu l'annonces et tu expliques pourquoi en une phrase. Tu ne demandes pas la permission apres coup.
- Tu n'ouvres pas par "Tu veux que je...", "Tu preferes A ou B ?", "Je propose deux options". Si tu as les infos pour trancher, tranche.
- Tu ne demandes au user de choisir QUE quand une info essentielle te manque vraiment (creneau dispo, douleur localisee, contrainte non memorisee) OU quand le choix engage un trade-off lourd que toi seul ne peux pas arbitrer.
- "Imprevu", "ca a change", "j'ai pas pu" du user n'est pas une demande de menu. C'est un signal a creuser ou a integrer dans une decision claire.
- Continuation de fil: si le tour precedent contenait une question ouverte de ta part et que le user n'y a pas repondu, ne change pas de sujet en silence. Soit tu reformules la question autrement, soit tu decides avec ton hypothese explicite ("je pars du principe que..., on ajuste si je me trompe").

Analyse le message utilisateur et decide quelle action prendre sur le calendrier d'entrainement reel.

Actions possibles:
- "move_session": move_session = deplacer une seule seance vers un slot libre/flexible
- "swap_sessions": swap_sessions = echanger deux vraies seances existantes
- "lighten_day": alleger une seance concrete ou un jour (convertit en repos)
- "replace_session": transformer une seance ou remplir une journee flexible existante (changer sport, type, duree, intensite, description)
- "update_session": modifier le titre ou l'objectif d'une seance concrete
- "no_change": aucune modification necessaire, ou demande ambigue / cible risquee qui doit etre clarifiee

Regles:
- les jours doivent etre en anglais: monday, tuesday, wednesday, thursday, friday, saturday, sunday
- quand une seance concrete est identifiable dans le calendrier date reel, privilegie toujours `target_session_id`
- pour un echange concret, renseigne `target_session_id` et `second_session_id`
- pour un deplacement concret, renseigne `target_date` au format ISO `YYYY-MM-DD`, mais seulement si la cible est `slot=free_flexible`
- n'utilise jamais `move_session` pour placer une seance sur un `slot=training`: utilise `swap_sessions` si deux seances existent, sinon `no_change`
- n'utilise jamais `move_session` pour "mettre A aujourd'hui et B demain" si A et B existent deja: c'est `swap_sessions`
- un `swap_sessions` entre une seance `slot=training` et une recuperation (flexible ou protegee) est autorise: la recuperation migre vers l'ancien jour de la seance dure, elle ne disparait pas
- un `slot=protected_recovery` n'est pas une cible de `move_session` (ca ecraserait la recup); privilegie `swap_sessions` si l'utilisateur veut deplacer une seance vers ce jour
- une recuperation est le satellite de la seance dure qui la precede; si tu deplaces une seance dure ou si tu swap, la recuperation devrait suivre pour rester physiologiquement utile — previens-le dans `fitmas_message` quand le cas se presente
- ne jamais `replace_session` / `update_session` / `lighten_day` sur un `slot=protected_recovery`: ces mutations la detruisent en place; garde `no_change` et demande confirmation
- si l'utilisateur dit juste "changer aujourd'hui et demain" sans dire quoi va ou, garde `no_change` et demande s'il veut echanger les deux seances
- si l'utilisateur veut ajouter une seance sur une journee flexible existante, utilise `replace_session` sur l'id de cette journee flexible
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
- "On peut changer aujourd'hui et demain ?" + aujourd'hui natation + demain renfo -> no_change, demander si l'utilisateur veut echanger les deux seances
- "Je veux le renfo aujourd'hui et la piscine demain" + aujourd'hui natation id=22 + demain renfo id=23 -> swap_sessions, target_session_id=22, second_session_id=23
- "echange samedi et dimanche" -> swap_sessions
- "On peut echanger mercredi et jeudi ?" + mercredi renfo id=24 + jeudi natation id=25 -> swap_sessions, target_session_id=24, second_session_id=25
- "Echange la natation de lundi avec le renfo de mardi" -> swap_sessions avec les deux ids
- "Mets la natation de lundi a mardi" + mardi `slot=training` -> no_change, demander si l'utilisateur veut echanger avec la seance de mardi
- "Mets la natation de lundi a vendredi" + vendredi `slot=free_flexible` -> move_session vers la date du vendredi
- "Echanger la natation de lundi avec la journee libre de mardi" + autre natation proche jeudi -> no_change, proposer de confirmer mardi malgre la proximite ou de choisir un autre creneau
- "Vendredi pour 40min" apres "remets le footing" + vendredi `slot=free_flexible` -> replace_session sur l'id du vendredi flexible, pas move_session
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


# Confirmation tags that we treat as "not really an open question" — these are
# administrative pings ("ok ?", "tu confirmes ?") that the user can ignore by
# acting on the next turn instead of answering literally.
_CONFIRMATION_TAGS = (
    "ok ?",
    "ok pour toi ?",
    "ca marche ?",
    "ca te va ?",
    "tu confirmes ?",
    "tu valides ?",
    "d'accord ?",
    "c'est bon ?",
    "ok c'est bon ?",
)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+")


def detect_open_question(coach_text: str | None) -> str | None:
    """Return the last open question in coach_text, or None.

    Returns the trimmed last question sentence if the text ends on a question
    mark and the question is not a pure confirmation prompt. Used to surface
    "le user n'a pas repondu" continuation-of-thread context to the next coach
    turn (Chantier 3 — refactor coach autonomy)."""
    if not coach_text:
        return None
    text = coach_text.strip()
    if not text.endswith("?"):
        return None
    low = text.lower().rstrip()
    for tag in _CONFIRMATION_TAGS:
        if low.endswith(tag):
            return None
    parts = _SENTENCE_SPLIT_RE.split(text)
    for part in reversed(parts):
        candidate = part.strip()
        if candidate.endswith("?"):
            return candidate
    return text


def _latest_agent_message(history: list[dict[str, Any]] | None) -> str | None:
    if not history:
        return None
    for msg in reversed(history):
        if msg.get("role") == "agent":
            text = str(msg.get("text") or "").strip()
            if text:
                return text
    return None


def _open_question_block(history: list[dict[str, Any]] | None) -> str:
    coach_text = _latest_agent_message(history)
    question = detect_open_question(coach_text)
    if not question:
        return ""
    return (
        "\nQuestion ouverte du tour precedent (a toi, pas au user) :\n"
        f"  \"{question}\"\n"
        "Si le nouveau message du user n'y repond pas, ne change pas de sujet en silence : "
        "soit tu reformules la question autrement, soit tu decides avec ton hypothese explicite.\n"
    )


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

    open_question_block = _open_question_block(conversation_history)

    prompt = f"""{time_block}
Source de vérité planning conversationnelle: calendrier daté / app.
Ignore tout repère hebdo legacy si le calendrier daté dit autre chose.
{timeline_block}
{execution_block}{temporal_block}{claim_block}{signal_block}
{profile_block}
{coach_block}{facts_block}
{history_block}{open_question_block}
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


def build_layered_conversation_prompt(
    *,
    user_text: str,
    prompt_policy: ConversationPromptPolicy,
    time_block: str,
    profile_summary: str | None = None,
    plan_summary: str | None = None,
    timeline_summary: str | None = None,
    execution_summary: str | None = None,
    temporal_summary: str | None = None,
    activity_claim_summary: str | None = None,
    signal_summary: str | None = None,
    conversation_history: list[dict[str, Any]] | None = None,
    coach_context: dict[str, Any] | None = None,
    selected_facts: list[str] | None = None,
) -> ConversationPromptBundle:
    """Build conversation prompt using the layered system.

    This assembles layers with explicit token budgets and cache breakpoints,
    then wraps the result in the same ConversationPromptBundle for compatibility.
    """
    layered = assemble_layered_prompt(
        coach_context=coach_context,
        profile_summary=profile_summary,
        time_block=time_block,
        plan_summary=None,
        timeline_summary=timeline_summary if prompt_policy.include_timeline else None,
        execution_summary=execution_summary if prompt_policy.include_execution else None,
        temporal_summary=temporal_summary if prompt_policy.include_temporal else None,
        activity_claim_summary=activity_claim_summary if prompt_policy.include_claim else None,
        signal_summary=signal_summary if prompt_policy.include_signals else None,
        selected_facts=selected_facts if prompt_policy.include_facts else None,
        conversation_history=conversation_history,
        history_limit=prompt_policy.history_limit,
    )

    # Separate cacheable layers for system prompt caching
    cache_indices = layered.cache_breakpoints()
    system_parts = []
    for i, layer in enumerate(sorted(layered.layers, key=lambda l: l.level)):
        rendered = layer.render()
        if not rendered:
            continue
        cache_control = (
            {"type": "ephemeral", "ttl": "1h"}
            if i in cache_indices
            else None
        )
        entry: dict[str, Any] = {"type": "text", "text": rendered}
        if cache_control:
            entry["cache_control"] = cache_control
        system_parts.append(entry)

    # The mutation instruction block is always included in system
    system_parts.insert(0, {
        "type": "text",
        "text": _CONVERSATION_SYSTEM_TEXT,
        "cache_control": {"type": "ephemeral", "ttl": "1h"},
    })

    history_messages_used = 0
    if conversation_history:
        history_messages_used = min(len(conversation_history), prompt_policy.history_limit)

    prompt_parts = [
        "Source de vérité planning conversationnelle: calendrier daté / app.",
        "Ignore tout repère hebdo legacy si le calendrier daté dit autre chose.",
    ]
    if prompt_policy.include_timeline and timeline_summary:
        prompt_parts.append(f"Calendrier daté utile:\n{timeline_summary}")
    open_question_block = _open_question_block(conversation_history)
    if open_question_block:
        prompt_parts.append(open_question_block.strip())
    prompt_parts.append(f"Nouveau message de l'utilisateur:\n{user_text}")
    prompt = "\n".join(prompt_parts)

    return ConversationPromptBundle(
        system=system_parts,
        prompt=prompt,
        history_messages_used=history_messages_used,
    )
