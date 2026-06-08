from __future__ import annotations

from dataclasses import dataclass
import re

from fitmas.legacy.domain.coaching import coach_voice
from fitmas.legacy.llm.reply_types import FinalReplyContext, RequestTextFn
from fitmas.legacy.llm.reply_validation import is_valid_final_reply
from fitmas.legacy.llm.gateway import request_text


@dataclass(frozen=True, slots=True)
class HeartbeatReplyFact:
    category: str
    value: str


@dataclass(frozen=True, slots=True)
class HeartbeatReplyContext:
    role: str
    capability: str
    temporal: tuple[str, ...] = ()
    today_truth: tuple[str, ...] = ()
    yesterday_truth: tuple[str, ...] = ()
    week_digest: tuple[str, ...] = ()
    plan_window: tuple[str, ...] = ()
    active_facts: tuple[HeartbeatReplyFact, ...] = ()
    angle: str | None = None
    draft: str | None = None
    forbidden_claims: tuple[str, ...] = ()


_HEARTBEAT_INTERNAL_VISIBLE_FRAGMENTS = (
    " health ",
    " constraint ",
    " execution ",
    " patch ",
    " runtime ",
    " fallback ",
)
_HEARTBEAT_CONTEXT_MARKER_RE = re.compile(
    r"\[(health|constraint|execution|patch|runtime|fallback)\]\s*",
    flags=re.IGNORECASE,
)


def build_heartbeat_reply_prompt(context: HeartbeatReplyContext) -> tuple[str, str]:
    """Build a terminal heartbeat composer prompt from structured facts."""
    system = (
        f"{coach_voice.COACH_VOICE_RULES}\n\n"
        "Ta responsabilite: compose le message heartbeat final visible au user.\n"
        "Le role heartbeat a prepare les faits; toi, tu transformes en texte naturel.\n"
        "Tu ne dois jamais recopier les categories internes ni les noms techniques.\n"
        "Tu ne dois jamais claim un changement planning sur un heartbeat read-only.\n"
        "Reponds uniquement avec le texte final, sans JSON ni markdown."
    )
    lines = [
        f"Role heartbeat: {context.role}",
        f"Capacite: {context.capability}",
    ]
    if context.temporal:
        lines.append("Temps:")
        lines.extend(f"- {item}" for item in context.temporal if str(item).strip())
    if context.today_truth:
        lines.append("Verite aujourd'hui:")
        lines.extend(f"- {item}" for item in context.today_truth if str(item).strip())
    if context.yesterday_truth:
        lines.append("Verite hier:")
        lines.extend(f"- {item}" for item in context.yesterday_truth if str(item).strip())
    if context.week_digest:
        lines.append("Digest semaine:")
        lines.extend(f"- {item}" for item in context.week_digest if str(item).strip())
    if context.plan_window:
        lines.append("Fenetre planning:")
        lines.extend(f"- {item}" for item in context.plan_window if str(item).strip())
    fact_values = _heartbeat_fact_values(context.active_facts)
    if fact_values:
        lines.append("Faits utiles:")
        lines.extend(f"- {item}" for item in fact_values)
    if context.angle:
        lines.append(f"Angle: {context.angle}")
    if context.draft:
        lines.append(f"Brouillon role heartbeat: {_heartbeat_prompt_value(context.draft)}")
    if context.forbidden_claims:
        lines.append("Claims interdits:")
        lines.extend(f"- {item}" for item in context.forbidden_claims if str(item).strip())
    lines.append("Ecris 1-3 phrases. Fond sportif concret, forme naturelle, pas de fiche interne.")
    return system, "\n".join(lines)


def compose_heartbeat_reply(
    context: HeartbeatReplyContext,
    *,
    request_text_fn: RequestTextFn = request_text,
) -> str | None:
    system, prompt = build_heartbeat_reply_prompt(context)
    reply = request_text_fn(system=system, prompt=prompt, max_tokens=320)
    if not is_valid_heartbeat_reply(reply):
        return None
    return str(reply).strip()


def is_valid_heartbeat_reply(reply: str | None) -> bool:
    if not reply:
        return False
    text = str(reply).strip()
    if len(text) < 5 or len(text) > 500:
        return False
    normalized = coach_voice.normalize_for_voice_guard(text)
    padded = f" {re.sub(r'[^a-z0-9]+', ' ', normalized)} "
    if any(fragment in padded for fragment in _HEARTBEAT_INTERNAL_VISIBLE_FRAGMENTS):
        return False
    context = FinalReplyContext(
        allowed_to_claim_mutation=False,
        pipeline="heartbeat",
        pipeline_capability="read_only",
    )
    return is_valid_final_reply(text, context)


def _heartbeat_fact_values(facts: tuple[HeartbeatReplyFact, ...]) -> tuple[str, ...]:
    values: list[str] = []
    for fact in facts:
        value = str(fact.value or "").strip()
        if value:
            values.append(value)
    return tuple(values)


def _heartbeat_prompt_value(value: str) -> str:
    return _HEARTBEAT_CONTEXT_MARKER_RE.sub("", str(value or "")).strip()
