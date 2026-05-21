from __future__ import annotations

from dataclasses import dataclass

from fitmas import coach_voice

from .base import PromptRender


@dataclass(frozen=True, slots=True)
class ReplyPromptBlockedEvent:
    command: str
    reason: str | None = None
    suggested_fix: str | None = None
    warning: str | None = None


@dataclass(frozen=True, slots=True)
class ReplyPromptInput:
    pipeline: str
    capability: str
    user_text: str
    original_llm_reply: str
    committed_events: tuple[str, ...]
    blocked_events: tuple[ReplyPromptBlockedEvent, ...]
    pending_summary: str | None
    memory_actions_applied: tuple[str, ...]
    execution_actions_applied: tuple[str, ...]
    allowed_to_claim_mutation: bool
    extra_facts: tuple[str, ...]


def build_reply_prompt(context: ReplyPromptInput) -> PromptRender:
    system = (
        f"{coach_voice.COACH_VOICE_RULES}\n\n"
        "Tu composes la reponse finale visible au user a partir de faits backend.\n"
        "Le backend a deja valide, bloque, commit ou cree une confirmation.\n"
        "Tu ne dois jamais inventer un commit. Tu ne dois jamais exposer les noms techniques "
        "(reviewer, patch, runtime, fallback, commit, JSON, tool, offplan).\n"
        "Reponds uniquement avec le texte final, sans JSON ni markdown."
    )
    lines = [
        f"Pipeline: {context.pipeline}",
        f"Capacite pipeline: {context.capability}",
        f"Message user: {context.user_text or '(non fourni)'}",
    ]
    if context.original_llm_reply:
        lines.append(f"Brouillon LLM initial: {context.original_llm_reply}")
    if context.committed_events:
        lines.append("Evenements commits:")
        lines.extend(f"- {event}" for event in context.committed_events)
        lines.append("Contrainte: l'action est deja commit; ne demande pas confirmation.")
    else:
        lines.append("Aucun changement planning n'a ete commit.")
    if context.blocked_events:
        lines.append("Evenements bloques:")
        for event in context.blocked_events:
            bits = [event.command]
            if event.reason:
                bits.append(f"reason={event.reason}")
            if event.suggested_fix:
                bits.append(f"suggested_fix={event.suggested_fix}")
            if event.warning:
                bits.append(f"warning={event.warning}")
            lines.append("- " + " | ".join(bits))
    if context.pending_summary:
        lines.append(f"Confirmation en attente: {context.pending_summary}")
        lines.append(
            "Contrainte: la reponse doit presenter le changement comme une proposition et demander confirmation explicitement."
        )
    if context.execution_actions_applied:
        lines.append("Execution appliquee:")
        lines.extend(f"- {item}" for item in context.execution_actions_applied)
        lines.append(
            "Contrainte: ces lignes sont la source de verite pour la seance, le statut et la date d'execution."
        )
        lines.append(
            "Si une ligne contient une date, ne la transforme pas en aujourd'hui, demain ou hier et ne mentionne pas une autre date."
        )
    if context.memory_actions_applied:
        lines.append("Memoire appliquee:")
        lines.extend(f"- {item}" for item in context.memory_actions_applied)
    if context.extra_facts:
        lines.append("Faits utiles:")
        lines.extend(f"- {item}" for item in context.extra_facts)
    if not context.allowed_to_claim_mutation:
        lines.append("Contrainte: ne claim pas une action appliquee, deplacee, posee, calee ou enregistree.")
    lines.append("Ecris 1-2 phrases. Si c'est bloque, donne la raison concrete et une alternative simple.")
    return PromptRender(system=system, prompt="\n".join(lines), max_tokens=300)
