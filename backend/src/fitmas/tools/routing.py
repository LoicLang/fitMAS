"""Intent-based tool budget routing.

Replaces regex pattern matching with a two-step approach:
1. Classify the user message into an IntentCategory
2. Map the category to a bounded tool budget

The classification remains deterministic (no LLM needed) but reasons about
conversational intent rather than keyword presence.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class IntentCategory(str, Enum):
    CASUAL_CHAT = "casual_chat"
    EXECUTION_REPORT = "execution_report"
    PLAN_NEGOTIATION = "plan_negotiation"
    PLAN_LOOKUP = "plan_lookup"
    ACTIVITY_REVIEW = "activity_review"
    ACTIVITY_HIGHLIGHTS = "activity_highlights"
    LOAD_REVIEW = "load_review"
    FACT_RECALL = "fact_recall"
    GENERIC_QUESTION = "generic_question"


@dataclass(frozen=True, slots=True)
class ToolRoutingDecision:
    pipeline: str
    tool_names: tuple[str, ...]
    reason: str
    intent: IntentCategory | None = None


# ---------------------------------------------------------------------------
# Tool budgets per intent — the core mapping
# ---------------------------------------------------------------------------

_TOOL_BUDGETS: dict[IntentCategory, tuple[str, ...]] = {
    IntentCategory.CASUAL_CHAT: (),
    IntentCategory.EXECUTION_REPORT: (
        "get_today_context",
        "get_recent_activities",
    ),
    IntentCategory.PLAN_NEGOTIATION: (
        "get_today_context",
        "get_plan_window",
        "get_load_context",
        "get_user_constraints",
        "get_relevant_facts",
    ),
    IntentCategory.PLAN_LOOKUP: (
        "get_today_context",
        "get_plan_window",
        "get_user_constraints",
    ),
    IntentCategory.ACTIVITY_REVIEW: (
        "get_recent_activities",
    ),
    IntentCategory.ACTIVITY_HIGHLIGHTS: (
        "get_activity_highlights",
        "get_recent_activities",
    ),
    IntentCategory.LOAD_REVIEW: (
        "get_load_context",
        "get_recent_reality_window",
    ),
    IntentCategory.FACT_RECALL: (
        "get_relevant_facts",
    ),
    IntentCategory.GENERIC_QUESTION: (
        "get_today_context",
        "get_plan_window",
        "get_recent_activities",
    ),
}


# ---------------------------------------------------------------------------
# Intent classification — deterministic heuristics
# ---------------------------------------------------------------------------

def classify_intent(user_text: str) -> IntentCategory:
    """Classify user text into an intent category using layered heuristics."""
    lowered = (user_text or "").strip().lower()
    if not lowered:
        return IntentCategory.CASUAL_CHAT

    # Plan dispute: what's on the app doesn't match (check early, very specific)
    if _matches_any(lowered, _PLAN_DISPUTE_SIGNALS):
        return IntentCategory.PLAN_LOOKUP

    # Plan negotiation: user wants to change their plan
    if _matches_any(lowered, _PLAN_NEGOTIATION_SIGNALS):
        return IntentCategory.PLAN_NEGOTIATION

    # Load review: training load questions (before activity review — "cette semaine" overlap)
    if _matches_any(lowered, _LOAD_REVIEW_SIGNALS):
        return IntentCategory.LOAD_REVIEW

    # Activity highlights: records, bests
    if _matches_any(lowered, _ACTIVITY_HIGHLIGHT_SIGNALS):
        return IntentCategory.ACTIVITY_HIGHLIGHTS

    # Activity review: recent history ("j'ai fait quoi" is a question, not a report)
    if _matches_any(lowered, _ACTIVITY_REVIEW_SIGNALS):
        return IntentCategory.ACTIVITY_REVIEW

    # Execution report: user is reporting what they did
    if _matches_any(lowered, _EXECUTION_REPORT_SIGNALS):
        return IntentCategory.EXECUTION_REPORT

    # Fact recall: user asks what the coach knows
    if _matches_any(lowered, _FACT_RECALL_SIGNALS):
        return IntentCategory.FACT_RECALL

    # Plan lookup: simple what's-next questions
    if _matches_any(lowered, _PLAN_LOOKUP_SIGNALS):
        return IntentCategory.PLAN_LOOKUP

    # Generic question with "?"
    if "?" in lowered and _matches_any(lowered, _GENERIC_QUESTION_SIGNALS):
        return IntentCategory.GENERIC_QUESTION

    return IntentCategory.CASUAL_CHAT


def route_tools_for_query(user_text: str, *, pipeline: str) -> ToolRoutingDecision:
    """Main entry point — classify intent then return tool budget."""
    if pipeline != "conversation":
        return ToolRoutingDecision(pipeline=pipeline, tool_names=(), reason="unsupported_pipeline")

    intent = classify_intent(user_text)
    tool_names = _TOOL_BUDGETS.get(intent, ())

    return ToolRoutingDecision(
        pipeline=pipeline,
        tool_names=tool_names,
        reason=intent.value,
        intent=intent,
    )


# ---------------------------------------------------------------------------
# Signal patterns grouped by intent
# ---------------------------------------------------------------------------

def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(pattern in text for pattern in patterns)


_EXECUTION_REPORT_SIGNALS = (
    "j'ai fait",
    "j ai fait",
    "j'ai couru",
    "j ai couru",
    "j'ai roule",
    "j ai roule",
    "j'ai nage",
    "j ai nage",
    "j'ai grimpe",
    "j ai grimpe",
    "seance faite",
    "c'est fait",
    "c est fait",
    "j'ai fini",
    "j ai fini",
    "session done",
    "je viens de",
    "j'ai enchaine",
    "j ai enchaine",
)

_PLAN_NEGOTIATION_SIGNALS = (
    "je bascule",
    "je decale",
    "je déplace",
    "je deplace",
    "echange",
    "swap",
    "je prefere faire",
    "je préfère faire",
    "trop charge",
    "trop chargé",
    "j'ai mal",
    "j ai mal",
    "je suis claque",
    "je suis claqué",
    "pas envie",
    "morte",
    "mort",
    "j'en peux plus",
    "j en peux plus",
    "allege",
    "allège",
    "remplace",
    "annule",
    "reporte",
)

_PLAN_DISPUTE_SIGNALS = (
    "c'est pas ce qui est sur mon planning",
    "c est pas ce qui est sur mon planning",
    "ce n'est pas ce qui est sur mon planning",
    "ce n est pas ce qui est sur mon planning",
    "pas ce qui est sur mon planning",
    "planning dans l'app",
    "planning dans l app",
    "planning de l'app",
    "planning de l app",
    "planning sur l'app",
    "planning sur l app",
    "l'app est bien",
    "l app est bien",
    "sur mon planning dans l'app",
    "sur mon planning dans l app",
)

_FACT_RECALL_SIGNALS = (
    "qu'est-ce que tu sais",
    "qu est ce que tu sais",
    "rappelle-moi mes contraintes",
    "rappelle moi mes contraintes",
    "mes contraintes",
    "mes preferences",
    "mes préférences",
    "tu te souviens",
)

_ACTIVITY_HIGHLIGHT_SIGNALS = (
    "plus longue",
    "plus long",
    "meilleur",
    "meilleure",
    "record",
    "pb",
    "pr ",
    "plus rapide",
)

_LOAD_REVIEW_SIGNALS = (
    "charge",
    "volume",
    "j'en fais trop",
    "j en fais trop",
    "trop charge",
    "trop chargé",
    "cette semaine je charge",
    "la semaine chargee",
    "la semaine chargée",
)

_ACTIVITY_REVIEW_SIGNALS = (
    "combien",
    "ce mois",
    "cette semaine",
    "dernieres activites",
    "dernières activités",
    "recemment",
    "récemment",
    "j'ai fait quoi",
    "j ai fait quoi",
)

_PLAN_LOOKUP_SIGNALS = (
    "il me reste quoi",
    "il reste quoi",
    "c'est quoi deja",
    "c est quoi deja",
    "ce soir c'est quoi",
    "ce soir c est quoi",
    "jeudi c'est quoi",
    "jeudi c est quoi",
    "demain c'est quoi",
    "demain c est quoi",
    "aujourd'hui c'est quoi",
    "aujourd hui c est quoi",
    "on fait quoi",
)

_GENERIC_QUESTION_SIGNALS = (
    "c'etait quoi",
    "c'était quoi",
    "quel etait",
    "quelle etait",
    "quoi",
    "comment",
    "pourquoi",
    "quand",
)
