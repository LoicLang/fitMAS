from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from fitmas import coach_voice
from fitmas.context_pack import ConversationContextPack
from fitmas.conversation_prompt_modules import (
    build_action_contract_system_text,
    build_calendar_truth_system_text,
    build_identity_voice_system_text,
)
from fitmas.conversation_prompting import ConversationPromptPolicy
from fitmas.prompt_observability import PromptTrace, build_prompt_trace
from fitmas.prompt_layers import assemble_layered_prompt
from fitmas.time_context import render_time_context

_CONVERSATION_SYSTEM_TEXT = f"""\
{build_identity_voice_system_text()}

Workflow replan_after_constraint:
- lis d'abord les tools atomiques utiles: plan reel, contraintes actives, charge/recovery, faits pertinents
- utilise `suggest_replan_candidates` seulement comme aide candidate quand une contrainte touche une ou plusieurs seances
- La candidate n'est pas une decision: tu dois la convertir en `PlanPatch | no_change | requires_confirmation`
- Quand l'action est concrete et que les tools `draft_*` sont disponibles, utilise-les pour construire un `PlanPatch` candidat (`draft_move_session`, `draft_swap_sessions`, `draft_replace_session`, `draft_lighten_day`, `draft_create_session`)
- Les tools `draft_*` ne commit jamais. Ils retournent `payload.patch + validation`; si la candidate est bonne, copie ce patch dans ton `CoachDecision.plan_patch` ou `requires_confirmation`
- Quand `validate_week_coherence` est disponible, utilise-le sur tout PlanPatch significatif avant ta decision finale ; il juge la qualite sportive, mais le backend re-run toujours la gate avant commit
- si la candidate couvre mal le scope, ajuste le PlanPatch ou demande une confirmation ciblee ; ne transforme pas ca en menu large
- ne mets pas de detail intra-seance fin dans ce workflow: sport, jour, duree/intensite cible suffisent pour Phase A

{build_calendar_truth_system_text()}

{build_action_contract_system_text()}

{coach_voice.COACH_VOICE_FEW_SHOTS_GOOD}

{coach_voice.COACH_VOICE_FEW_SHOTS_BAD}

Tu reponds UNIQUEMENT avec un JSON CoachDecision valide.

Format cible:
- response_type: reply | no_change | mutation_decision | plan_patch | requires_confirmation
- rationale: raison courte
- fitmas_message: message envoye TEL QUEL a l'utilisateur (voix coach, voir regles ci-dessus). Jamais une etiquette technique, jamais une promesse de mutation que le backend pourrait bloquer.
- mutation_decision: objet legacy optionnel si une seule mutation suffit
- plan_patch: objet optionnel si une ou plusieurs operations sont necessaires
- confirmation_reason: obligatoire si response_type=requires_confirmation
- memory_actions: liste optionnelle d'actions memoire proposees, jamais ecrites directement par toi.
  Types autorises:
  - record_health_signal: health_signal, body_area?, severity=mild|moderate|severe|unknown, status=new|ongoing|improving|worsening|resolved|unknown, confidence, evidence?
  - record_availability: window_text, availability=unavailable|limited|available|unknown, starts_on?, ends_on?, recurrence?, confidence, evidence?
  - record_preference: preference, polarity=prefer|avoid|like|dislike|neutral|unknown, scope?, confidence, evidence?
- execution_actions: liste optionnelle d'actions execution proposees.
  Type autorise: record_execution_update avec target_ref, target_session_id?, status=completed|not_completed|partially_completed|unknown, completed?, sport_type?, duration_min?, confidence, evidence?
- pending_resolution: optionnel, uniquement si un pending existe ou si le tour y fait reference.
  Types autorises: accept_pending | reject_pending | modify_pending | ignore | needs_clarification.
  Pour un pending type plan_patch_choice, accept_pending exige selected_candidate_id si le user choisit une option.
  modify_pending exige requested_changes, reason est optionnel, et ne peut modifier que le pending existant, jamais forger un patch neuf.
  Tu ne parses jamais "oui/non" hors contexte: tu lis le message entier et le pending injecte.
  Exemples:
  - pending actif + "oui" clair -> pending_resolution.type=accept_pending
  - pending plan_patch_choice + "la deuxieme / vendredi" -> pending_resolution.type=accept_pending, selected_candidate_id=<id exact de l'option>
  - pending actif + "non" clair -> pending_resolution.type=reject_pending
  - pending actif + "oui mais finalement vendredi" -> pending_resolution.type=modify_pending, requested_changes="deplacer/adapter vers vendredi"
  - pending actif + "j'ai pas eu le temps hier" -> pending_resolution.type=ignore + execution_actions si pertinent

Few-shots actions structurees:
- "j'ai pas eu le temps hier" -> execution_actions=[record_execution_update status=not_completed, completed=false, target_ref="seance d'hier"]
- "j'ai mal au genou" -> memory_actions=[record_health_signal health_signal="douleur genou", severity=unknown, confidence elevee]
- "je peux pas nager 2 semaines" -> memory_actions=[record_availability window_text="natation impossible 2 semaines", availability=unavailable] + plan_patch si une seance nage est touchee
- "running" ou "mercredi" en continuation courte -> lis le contexte precedent, puis complete l'action en cours; ne reponds pas par un raccourci canned

Capture de contraintes — regle generale:
Le user mentionne un fact dispo/sante/preference, meme en passant et meme pour expliquer du passe. Emets un `memory_action` avec confidence appropriee. Mieux vaut capturer en working memory avec faible confidence que perdre l'info. Si le scope (duree, sport, periode) est implicite, fais ton hypothese et marque-la dans `evidence`.

Few-shots capture indirecte:
- "la piscine est en vidange / fermee / inaccessible" -> memory_actions=[record_availability window_text="piscine indisponible (vidange/fermeture)", availability=unavailable, confidence moderate, evidence="user mentionne piscine inaccessible"]. Ajoute un plan_patch si une seance nage est touchee cette semaine.
- "j'ai pas pu nager, piscine etait fermee" -> meme memory_action + execution_actions si seance nage prevue manquee.
- "je voyage de mardi a vendredi" -> memory_actions=[record_availability window_text="voyage mardi-vendredi", availability=limited, starts_on/ends_on si dates inferable] + plan_patch si seances touchees.
- "j'ai mal au dos depuis quelques jours" -> memory_actions=[record_health_signal health_signal="douleur dos", status=ongoing, confidence elevee].
- "je prefere courir le matin" -> memory_actions=[record_preference preference="courir le matin", polarity=prefer, confidence moderate].
- user explique pourquoi une seance a saute en mentionnant un fait stable -> capture le fait ET l'execution, pas juste l'execution.

Pour une action planning, privilegie `response_type="plan_patch"`:
plan_patch = {{
  "coach_message": "message court",
  "operations": [
    {{
      "operation_type": "move_session|swap_sessions|replace_session|update_session|lighten_day|create_session",
      "target_session_id": null,
      "second_session_id": null,
      "target_date": "YYYY-MM-DD",
      "from_day": null,
      "to_day": null,
      "new_title": null,
      "new_goal": null,
      "new_sport_type": null,
      "new_session_type": null,
      "new_duration_min": null,
      "new_intensity": null,
      "new_description": null,
      "rationale": "raison operation"
    }}
  ]
}}

Compat temporaire acceptee:
- tu peux encore retourner directement le vieux JSON `mutation_type` si tu ne sais faire qu'une mutation simple
- types legacy autorises: move_session, lighten_day, swap_sessions, update_session, replace_session, create_session, no_change
- create_session exige target_date, new_sport_type, new_title, new_duration_min

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


def _open_question_block(history: list[dict[str, Any]] | None, *, enabled: bool = True) -> str:
    if not enabled:
        return ""
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
    trace: PromptTrace | None = None


def _trace_intent_from_context(coach_context: dict[str, Any] | None) -> str | None:
    if not coach_context:
        return None
    primary_intent = coach_context.get("turn_primary_intent")
    return str(primary_intent) if primary_intent else None


def _trace_tool_names(context_pack: ConversationContextPack | None) -> tuple[str, ...]:
    if context_pack is None:
        return ()
    return context_pack.tool_budget.allowed_tools


def _trace_truth_block_names(context_pack: ConversationContextPack | None) -> tuple[str, ...]:
    if context_pack is None:
        return ()
    return context_pack.truth_block_names()


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
    unresolved_execution_followup: str | None = None,
    context_pack: ConversationContextPack | None = None,
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

    open_question_block = _open_question_block(
        conversation_history,
        enabled=prompt_policy.include_open_question_marker,
    )

    followup_block = ""
    if unresolved_execution_followup:
        followup_block = "\n" + unresolved_execution_followup.strip() + "\n"

    prompt = f"""{time_block}
Source de vérité planning conversationnelle: calendrier daté / app.
Ignore tout repère hebdo legacy si le calendrier daté dit autre chose.
{timeline_block}
{execution_block}{temporal_block}{claim_block}{signal_block}
{profile_block}
{coach_block}{facts_block}
{history_block}{open_question_block}{followup_block}
Nouveau message de l'utilisateur:
{user_text}"""

    system = [
        {
            "type": "text",
            "text": _CONVERSATION_SYSTEM_TEXT,
            "cache_control": {"type": "ephemeral", "ttl": "1h"},
        }
    ]

    return ConversationPromptBundle(
        system=system,
        prompt=prompt,
        history_messages_used=history_messages_used,
        trace=build_prompt_trace(
            route="conversation_decide",
            provider=None,
            model=None,
            prompt_policy=prompt_policy.name,
            prompt_contract=prompt_policy.contract_name,
            intent=_trace_intent_from_context(coach_context),
            system=system,
            user_prompt=prompt,
            tool_names=_trace_tool_names(context_pack),
            truth_block_names=_trace_truth_block_names(context_pack),
            history_messages_used=history_messages_used,
        ),
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
    unresolved_execution_followup: str | None = None,
    context_pack: ConversationContextPack | None = None,
) -> ConversationPromptBundle:
    """Build conversation prompt using the layered system.

    This assembles layers with explicit token budgets and cache breakpoints,
    then wraps the result in the same ConversationPromptBundle for compatibility.
    """
    layered = assemble_layered_prompt(
        coach_context=coach_context if prompt_policy.include_coach_context else None,
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
    open_question_block = _open_question_block(
        conversation_history,
        enabled=prompt_policy.include_open_question_marker,
    )
    if open_question_block:
        prompt_parts.append(open_question_block.strip())
    if unresolved_execution_followup:
        prompt_parts.append(unresolved_execution_followup.strip())
    prompt_parts.append(f"Nouveau message de l'utilisateur:\n{user_text}")
    prompt = "\n".join(prompt_parts)

    return ConversationPromptBundle(
        system=system_parts,
        prompt=prompt,
        history_messages_used=history_messages_used,
        trace=build_prompt_trace(
            route="conversation_decide",
            provider=None,
            model=None,
            prompt_policy=prompt_policy.name,
            prompt_contract=prompt_policy.contract_name,
            intent=_trace_intent_from_context(coach_context),
            system=system_parts,
            user_prompt=prompt,
            tool_names=_trace_tool_names(context_pack),
            truth_block_names=_trace_truth_block_names(context_pack),
            history_messages_used=history_messages_used,
        ),
    )
