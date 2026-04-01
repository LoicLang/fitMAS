from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ToolRoutingDecision:
    pipeline: str
    tool_names: tuple[str, ...]
    reason: str


def route_tools_for_query(user_text: str, *, pipeline: str) -> ToolRoutingDecision:
    lowered = (user_text or "").strip().lower()
    if pipeline != "conversation":
        return ToolRoutingDecision(pipeline=pipeline, tool_names=(), reason="unsupported_pipeline")
    if not lowered:
        return ToolRoutingDecision(pipeline=pipeline, tool_names=(), reason="empty_query")

    if _matches_any(lowered, _FACT_PATTERNS):
        return ToolRoutingDecision(
            pipeline=pipeline,
            tool_names=("get_relevant_facts",),
            reason="fact_recall",
        )
    if _matches_any(lowered, _ACTIVITY_HIGHLIGHT_PATTERNS):
        return ToolRoutingDecision(
            pipeline=pipeline,
            tool_names=("get_activity_highlights", "get_recent_activities"),
            reason="activity_highlights",
        )
    if _matches_any(lowered, _LOAD_CONTEXT_PATTERNS):
        return ToolRoutingDecision(
            pipeline=pipeline,
            tool_names=("get_load_context", "get_recent_reality_window"),
            reason="load_context",
        )
    if _matches_any(lowered, _PLAN_DISPUTE_PATTERNS):
        return ToolRoutingDecision(
            pipeline=pipeline,
            tool_names=("get_today_context", "get_plan_window"),
            reason="plan_dispute",
        )
    if _matches_any(lowered, _RECENT_ACTIVITY_PATTERNS):
        return ToolRoutingDecision(
            pipeline=pipeline,
            tool_names=("get_recent_activities",),
            reason="recent_activities",
        )
    if _matches_any(lowered, _PLAN_PATTERNS):
        return ToolRoutingDecision(
            pipeline=pipeline,
            tool_names=("get_today_context", "get_plan_window"),
            reason="plan_lookup",
        )
    if "?" in lowered and _matches_any(lowered, _GENERIC_LOOKUP_PATTERNS):
        return ToolRoutingDecision(
            pipeline=pipeline,
            tool_names=("get_today_context", "get_plan_window", "get_recent_activities"),
            reason="generic_lookup",
        )
    return ToolRoutingDecision(pipeline=pipeline, tool_names=(), reason="no_tool_needed")


def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(pattern in text for pattern in patterns)


_FACT_PATTERNS = (
    "qu'est-ce que tu sais",
    "qu est ce que tu sais",
    "rappelle-moi mes contraintes",
    "rappelle moi mes contraintes",
    "mes contraintes",
    "mes preferences",
    "mes préférences",
)

_ACTIVITY_HIGHLIGHT_PATTERNS = (
    "plus longue",
    "plus long",
    "meilleur",
    "meilleure",
    "record",
    "pb",
    "pr ",
    "plus rapide",
)

_RECENT_ACTIVITY_PATTERNS = (
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

_LOAD_CONTEXT_PATTERNS = (
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

_PLAN_PATTERNS = (
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

_PLAN_DISPUTE_PATTERNS = (
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

_GENERIC_LOOKUP_PATTERNS = (
    "c'etait quoi",
    "c'était quoi",
    "quel etait",
    "quelle etait",
    "quoi",
)
