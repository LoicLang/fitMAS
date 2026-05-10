from __future__ import annotations

import json
import logging
from typing import Any, Sequence

from pydantic import BaseModel, Field, ValidationError

from fitmas import llm_gateway as gw

logger = logging.getLogger(__name__)


_PRIMARY_INTENTS = {
    "close_turn",
    "trivial_ack",
    "casual_chat",
    "plan_lookup",
    "activity_review",
    "activity_highlights",
    "plan_mutation",
    "execution_report",
    "availability_constraint",
    "health_signal",
    "calibration_answer",
    "preference_signal",
    "needs_clarification",
    "generic_question",
}
_SECONDARY_INTENTS = {
    "non_completion_claim",
    "activity_claim",
    "activity_review",
    "activity_highlights",
    "execution_report",
    "availability_constraint",
    "health_signal",
    "plan_mutation",
    "preference_signal",
    "calibration_answer",
    "generic_question",
}


class ConversationTurnPlan(BaseModel):
    primary_intent: str
    secondary_intents: tuple[str, ...] = ()
    user_goal: str = ""
    mutation_signal: bool = False
    execution_claim: dict[str, Any] | None = None
    temporal_references: tuple[dict[str, Any], ...] = ()
    requires_truth_read: bool = False
    truth_scope: str | None = None
    needs_clarification: bool = False
    clarification_question: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @property
    def has_plan_mutation(self) -> bool:
        return (
            self.mutation_signal
            or self.primary_intent == "plan_mutation"
            or "plan_mutation" in self.secondary_intents
        )


def plan_conversation_turn(
    *,
    user_text: str,
    temporal_summary: str,
    execution_summary: str,
    activity_claim_summary: str,
    signal_summary: str,
    conversation_history: Sequence[dict[str, Any]] | None = None,
) -> ConversationTurnPlan | None:
    data = gw.request_json(
        system=_SYSTEM,
        prompt=_build_prompt(
            user_text=user_text,
            temporal_summary=temporal_summary,
            execution_summary=execution_summary,
            activity_claim_summary=activity_claim_summary,
            signal_summary=signal_summary,
            conversation_history=conversation_history,
        ),
        model="claude-haiku-4-5-20251001",
        max_tokens=500,
    )
    if not isinstance(data, dict):
        return None
    try:
        plan = ConversationTurnPlan(**data)
    except ValidationError:
        logger.exception("Invalid conversation turn plan payload: %s", data)
        return None
    if plan.primary_intent not in _PRIMARY_INTENTS:
        logger.warning("Unknown conversation primary intent: %s", plan.primary_intent)
        return None
    if any(intent not in _SECONDARY_INTENTS for intent in plan.secondary_intents):
        logger.warning("Unknown conversation secondary intent(s): %s", plan.secondary_intents)
        return None
    return plan


def _build_prompt(
    *,
    user_text: str,
    temporal_summary: str,
    execution_summary: str,
    activity_claim_summary: str,
    signal_summary: str,
    conversation_history: Sequence[dict[str, Any]] | None = None,
) -> str:
    capabilities = {
        "plan_lookup": "question sur le calendrier ou l'historique planning, sans changement",
        "activity_review": "question factuelle sur les activites recentes ou l'historique d'execution",
        "activity_highlights": "question sur un meilleur/pire record recent: plus longue sortie, plus grande distance, plus rapide",
        "plan_mutation": "deplacer, echanger, remplacer, alleger ou negocier une seance",
        "execution_report": "declaration de ce qui a ete fait ou pas fait",
        "health_signal": "douleur, fatigue, maladie, gene physique",
        "calibration_answer": "reponse courte a une question de calibration ouverte",
        "needs_clarification": "message ambigu dont la cible est risquee",
        "generic_question": "question coach hors mutation immediate: poids, objectif, doute, strategie generale",
        "close_turn": (
            "accuse reception ou cloture sociale sans nouvelle contrainte, sans choix "
            "de creneau, sans question plan, sans acceptation explicite d'un pending"
        ),
    }
    temporal_contract = {
        "kind": "relative_day|weekday|date",
        "value": "today|tomorrow|yesterday|monday..sunday|YYYY-MM-DD",
        "role": "source|target|context",
    }
    return "\n".join(
        [
            "Determine l'intention principale du tour FitMAS.",
            "Le message peut etre compose: garde une intention principale et des intentions secondaires.",
            "capabilities:",
            json.dumps(capabilities, ensure_ascii=False, sort_keys=True),
            "Temporal refs: si le user pointe un jour/date, extrais un artefact type, pas une phrase.",
            json.dumps(temporal_contract, ensure_ascii=False, sort_keys=True),
            "",
            "Contexte borne:",
            f"- temporel: {temporal_summary or 'aucun'}",
            f"- execution: {execution_summary or 'aucun'}",
            f"- claims: {activity_claim_summary or 'aucun'}",
            f"- signaux: {signal_summary or 'aucun'}",
            "",
            "Fil conversationnel recent:",
            _format_recent_conversation_for_prompt(conversation_history),
            "",
            "Message utilisateur:",
            user_text,
        ]
    )


def _format_recent_conversation_for_prompt(conversation_history: Sequence[dict[str, Any]] | None) -> str:
    if not conversation_history:
        return "aucun"
    lines: list[str] = []
    for message in tuple(conversation_history)[-4:]:
        role = str(message.get("role") or "unknown").strip() or "unknown"
        text = str(message.get("text") or "").strip()
        if len(text) > 240:
            text = f"{text[:237]}..."
        if not text:
            continue
        lines.append(f"- {role}: {text}")
    return "\n".join(lines) if lines else "aucun"


_SYSTEM = """\
Tu es le routeur d'intention conversationnelle de FitMAS.
Aucun write DB. Aucun side-effect. Aucune reponse finale utilisateur.
Tu classes seulement le tour pour proteger l'intention principale avant les orchestrateurs.

Regles:
- Si le message combine "je n'ai pas fait / impossible / oublie" avec une cible de reprogrammation, l'intention principale est plan_mutation et non_completion_claim est secondaire.
- Ne force pas une seule intention si le message est compose.
- Un wording comme "vendredi a la place ?" peut etre une mutation meme sans mot-cle swap/decale.
- Si le user conteste ou verifie une annonce planning du coach ("t'es sur ?", "redonne le plan actuel"), primary_intent=plan_lookup, requires_truth_read=true, truth_scope=plan_window.
- Si le user demande un fait sur les activites recentes ("ma plus longue sortie recente", "plus grosse distance", "meilleure sortie"), primary_intent=activity_highlights, requires_truth_read=true, truth_scope=execution.
- Si le user demande une lecture d'historique d'activite sans superlatif clair, primary_intent=activity_review, requires_truth_read=true, truth_scope=execution.
- Si la cible concrete manque, primary_intent=needs_clarification.
- Un jour/date seul ("samedi", "vendredi", "demain") n'est PAS une mutation sans fil actif. Si Fil conversationnel recent=aucun et qu'il n'y a ni action explicite ni question de choix planning ouverte, primary_intent=needs_clarification, mutation_signal=false, temporal_references role=context.
- Si le coach vient de poser une question de choix planning ("jeudi ou samedi ?", "quelle seance ?"), un jour/date seul peut repondre a ce fil et devenir plan_mutation ou calibration_answer selon le contexte.
- Si le user donne un poids/metric corporel et demande quoi faire ("je fais 100kg qu'est-ce qu'on fait ?"), primary_intent=generic_question, pas execution_report.
- Pour les messages courts ou elliptiques, utilise le fil recent. Si le message continue une question generale precedente sans nouvelle douleur/fatigue/plan, garde generic_question ou casual_chat; ne bascule pas vers health_signal.
- "Okay chef", "nickel merci", "parfait on garde ca", "carre" sans autre signal -> primary_intent=close_turn.
- "Ok decale a vendredi" -> plan_mutation, pas close_turn.
- "Ok mais j'ai mal au genou" -> health_signal, pas close_turn.
- Si une confirmation pending existe dans le contexte aval, elle sera resolue par le coach decisionnaire; ne force pas close_turn sur une acceptation transactionnelle claire.

Reponds uniquement avec un JSON valide:
{
  "primary_intent": "close_turn|plan_mutation|plan_lookup|activity_review|activity_highlights|execution_report|availability_constraint|health_signal|calibration_answer|preference_signal|casual_chat|trivial_ack|needs_clarification|generic_question",
  "secondary_intents": ["non_completion_claim|activity_claim|activity_review|activity_highlights|availability_constraint|health_signal|plan_mutation|preference_signal|calibration_answer|generic_question"],
  "user_goal": "phrase courte",
  "mutation_signal": true,
  "execution_claim": {"status": "done|not_done|unknown", "sport_type": "swimming|running|cycling|strength|climbing|unknown", "date": "YYYY-MM-DD|null"},
  "temporal_references": [{"kind":"relative_day|weekday|date","value":"today|tomorrow|yesterday|monday|tuesday|wednesday|thursday|friday|saturday|sunday|YYYY-MM-DD","role":"source|target|context"}],
  "requires_truth_read": false,
  "truth_scope": "plan_window|execution|memory|null",
  "needs_clarification": false,
  "clarification_question": null,
  "confidence": 0.0
}
"""
