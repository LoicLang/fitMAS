"""Structured prompt layer system for FitMAS conversation pipeline.

Organizes prompt context into explicit layers with independent
token budgets and compaction strategies:

- Layer 0: Coach identity (stable, cacheable)
- Layer 1: Athlete profile (stable per session, cacheable)
- Layer 2: Plan state (changes weekly)
- Layer 3: Immediate context (changes every turn)
- Layer 4: Episodic memory (filtered per turn)

Each layer is a dataclass with a render() method that produces
the text block and a budget that caps its size.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class PromptLayer:
    """A single layer of the prompt context."""
    level: int
    name: str
    content: str
    token_budget: int
    cacheable: bool = False

    def render(self) -> str:
        """Render the layer, compacting if over budget."""
        if not self.content:
            return ""
        estimated_tokens = len(self.content) // 4
        if estimated_tokens <= self.token_budget:
            return self.content
        # Simple compaction: truncate to budget
        char_budget = self.token_budget * 4
        return self.content[:char_budget] + "\n[...]"


@dataclass(slots=True)
class LayeredPrompt:
    """Assembled prompt from multiple layers."""
    layers: list[PromptLayer] = field(default_factory=list)

    def add(self, layer: PromptLayer) -> None:
        self.layers.append(layer)

    def render(self) -> str:
        """Render all layers in order, skipping empty ones."""
        parts = []
        for layer in sorted(self.layers, key=lambda l: l.level):
            rendered = layer.render()
            if rendered:
                parts.append(rendered)
        return "\n\n".join(parts)

    def cache_breakpoints(self) -> list[int]:
        """Return indices of cacheable layers (for Anthropic prompt caching)."""
        return [i for i, layer in enumerate(self.layers) if layer.cacheable and layer.content]


# ---------------------------------------------------------------------------
# Layer builders
# ---------------------------------------------------------------------------

def build_identity_layer(
    *,
    coach_name: str = "FitMAS",
    coach_style: str = "direct",
    coach_soul: str = "",
    coach_do: str = "",
    coach_dont: str = "",
    coach_relationship: str = "",
) -> PromptLayer:
    """Layer 0: Coach identity — stable across conversations."""
    parts = [
        f"Tu es {coach_name}, un coach multisport IA.",
        f"Style: {coach_style}.",
        "Ton ton: clair, court, precis, confiant, chaleureux sans faux enthousiasme.",
        "Tu parles comme un coach exigeant et calme, jamais comme un bot.",
        "Tu reponds toujours en francais. Tu tutoies toujours l'utilisateur.",
        "Varie l'attaque de tes messages et evite les ouvertures recyclees.",
        "N'ouvre pas systematiquement par 'Bon', 'OK', 'Attends' ou 'On va etre honnete'.",
        "N'essentialise pas un jour fixe de la semaine ou une contrainte stable si elle n'explique pas la decision du moment.",
    ]
    if coach_soul:
        parts.append(f"Ame du coach: {coach_soul}")
    if coach_do:
        parts.append(f"Fait bien: {coach_do}")
    if coach_dont:
        parts.append(f"Ne fait jamais: {coach_dont}")
    if coach_relationship:
        parts.append(f"Relation: {coach_relationship}")

    return PromptLayer(
        level=0,
        name="identity",
        content="\n".join(parts),
        token_budget=300,
        cacheable=True,
    )


def build_profile_layer(
    *,
    profile_summary: str | None = None,
) -> PromptLayer:
    """Layer 1: Athlete profile — stable per session."""
    content = ""
    if profile_summary:
        content = f"Profil resume:\n{profile_summary}"
    return PromptLayer(
        level=1,
        name="profile",
        content=content,
        token_budget=400,
        cacheable=True,
    )


def build_plan_layer(
    *,
    timeline_summary: str | None = None,
    plan_summary: str | None = None,
) -> PromptLayer:
    """Layer 2: Plan state — changes weekly."""
    parts = []
    if timeline_summary:
        parts.append(f"Calendrier date reel:\n{timeline_summary}")
    return PromptLayer(
        level=2,
        name="plan",
        content="\n\n".join(parts),
        token_budget=800,
        cacheable=False,
    )


def build_immediate_layer(
    *,
    time_block: str,
    execution_summary: str | None = None,
    temporal_summary: str | None = None,
    activity_claim_summary: str | None = None,
    signal_summary: str | None = None,
    coach_reading_text: str | None = None,
) -> PromptLayer:
    """Layer 3: Immediate context — changes every turn."""
    parts = [
        time_block,
        "Source de verite planning conversationnelle: calendrier date / app.",
        "Ignore tout repere hebdo legacy si le calendrier date dit autre chose.",
    ]
    if execution_summary:
        parts.append(execution_summary)
    if temporal_summary:
        parts.append(temporal_summary)
    if activity_claim_summary:
        parts.append(activity_claim_summary)
    if signal_summary:
        parts.append(signal_summary)
    if coach_reading_text:
        parts.append(coach_reading_text)

    return PromptLayer(
        level=3,
        name="immediate",
        content="\n\n".join(parts),
        token_budget=600,
        cacheable=False,
    )


def build_memory_layer(
    *,
    selected_facts: list[str] | None = None,
    conversation_history: list[dict[str, Any]] | None = None,
    history_limit: int = 8,
) -> PromptLayer:
    """Layer 4: Episodic memory — filtered per turn."""
    parts = []

    if selected_facts:
        facts_block = (
            "Memoire utile (elements high/medium a prendre en compte dans tes decisions):\n"
            + "\n".join(f"- {fact}" for fact in selected_facts)
        )
        parts.append(facts_block)

    if conversation_history:
        recent = conversation_history[-history_limit:]
        lines = []
        for msg in recent:
            prefix = "Utilisateur" if msg["role"] == "user" else "FitMAS"
            lines.append(f"{prefix}: {msg['text']}")
        if lines:
            parts.append("Historique recent:\n" + "\n".join(lines))

    return PromptLayer(
        level=4,
        name="memory",
        content="\n\n".join(parts),
        token_budget=500,
        cacheable=False,
    )


# ---------------------------------------------------------------------------
# Assembler
# ---------------------------------------------------------------------------

def assemble_layered_prompt(
    *,
    coach_context: dict[str, Any] | None = None,
    profile_summary: str | None = None,
    time_block: str,
    plan_summary: str | None = None,
    timeline_summary: str | None = None,
    execution_summary: str | None = None,
    temporal_summary: str | None = None,
    activity_claim_summary: str | None = None,
    signal_summary: str | None = None,
    selected_facts: list[str] | None = None,
    conversation_history: list[dict[str, Any]] | None = None,
    history_limit: int = 8,
) -> LayeredPrompt:
    """Assemble all layers into a LayeredPrompt."""
    ctx = coach_context or {}
    prompt = LayeredPrompt()

    prompt.add(build_identity_layer(
        coach_name=ctx.get("coach_name", "FitMAS"),
        coach_style=ctx.get("coach_style", "direct"),
        coach_soul=ctx.get("coach_soul", ""),
        coach_do=ctx.get("coach_do", ""),
        coach_dont=ctx.get("coach_dont", ""),
        coach_relationship=ctx.get("coach_relationship", ""),
    ))
    prompt.add(build_profile_layer(profile_summary=profile_summary))
    prompt.add(build_plan_layer(timeline_summary=timeline_summary, plan_summary=plan_summary))
    prompt.add(build_immediate_layer(
        time_block=time_block,
        execution_summary=execution_summary,
        temporal_summary=temporal_summary,
        activity_claim_summary=activity_claim_summary,
        signal_summary=signal_summary,
        coach_reading_text=ctx.get("coach_reading_digest_text"),
    ))
    prompt.add(build_memory_layer(
        selected_facts=selected_facts,
        conversation_history=conversation_history,
        history_limit=history_limit,
    ))

    return prompt
