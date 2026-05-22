from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from fitmas.domain.coaching import coach_voice
from fitmas.grounding_contract import ReplyGroundingPacket, render_grounding_packet_for_prompt
from fitmas.llm.gateway import request_text

from .reply_types import FinalReplyContext, RequestTextFn
from .reply_validation import is_valid_final_reply


def build_factual_reply_verifier_prompt(
    *,
    outgoing_reply: str,
    grounding: ReplyGroundingPacket,
    pipeline_capability: str,
) -> tuple[str, str]:
    """Build a semantic verifier prompt from DB grounding and the reply only."""
    system = (
        f"{coach_voice.COACH_VOICE_RULES}\n\n"
        "Tu es le verificateur factualite FitMAS.\n"
        "Tu ne lis pas le message utilisateur et tu ne deduis aucune intention.\n"
        "Tu compares uniquement le grounding backend autoritaire avec la reponse sortante.\n"
        "Retourne uniquement un JSON strict: "
        '{"verdict":"allow|repair","reason":"court","repaired_reply":"texte si repair"}'
    )
    lines = [
        f"Capacite pipeline: {pipeline_capability}",
        "Grounding autoritaire:",
        *render_grounding_packet_for_prompt(grounding),
        "",
        "Reponse sortante a verifier:",
        outgoing_reply,
        "",
        "ALLOW seulement si chaque jour, date, statut, sport, duree, zone, seance ou trou planning mentionne est supporte par le grounding.",
        "REPAIR si la reponse contredit le grounding, ajoute un jour/date absent, ou dit qu'un creneau est vide alors qu'une session existe.",
        "REPAIR si elle transforme une question de verification planning en relance au user au lieu de donner la verite disponible.",
        "En repair, garde 1-2 phrases courtes, sans nom technique, sans inventer de nouvelle action.",
    ]
    if pipeline_capability == "plan_lookup":
        lines.append("Pour plan_lookup: ne pose pas de question au user; donne la reponse factuelle et ferme.")
    return system, "\n".join(lines)


def verify_factual_reply(
    reply: str | None,
    *,
    grounding: ReplyGroundingPacket,
    pipeline_capability: str,
    request_text_fn: RequestTextFn = request_text,
) -> str | None:
    """Verify or repair a reply against authoritative grounding facts."""
    if not reply:
        return None
    text = str(reply).strip()
    if pipeline_capability == "plan_lookup" and "?" in text:
        return None
    context = FinalReplyContext(
        allowed_to_claim_mutation=False,
        pipeline="conversation" if pipeline_capability == "plan_lookup" else pipeline_capability,
        pipeline_capability=pipeline_capability,
    )
    if not is_valid_final_reply(text, context):
        return None
    hard_guard_allows_text = True
    if pipeline_capability == "plan_lookup":
        hard_guard_allows_text = _plan_lookup_hard_guard_allows(text, grounding)

    system, prompt = build_factual_reply_verifier_prompt(
        outgoing_reply=text,
        grounding=grounding,
        pipeline_capability=pipeline_capability,
    )
    raw = request_text_fn(system=system, prompt=prompt, max_tokens=450)
    verdict = _parse_post_event_verdict(raw)
    if verdict is None:
        return None
    if verdict.get("verdict") == "allow":
        return text if hard_guard_allows_text else None
    repaired = str(verdict.get("repaired_reply") or "").strip()
    if pipeline_capability == "plan_lookup" and "?" in repaired:
        return None
    if repaired and is_valid_final_reply(repaired, context):
        if pipeline_capability == "plan_lookup" and not _plan_lookup_hard_guard_allows(repaired, grounding):
            return None
        return repaired
    return None


def _plan_lookup_hard_guard_allows(reply: str | None, grounding: ReplyGroundingPacket) -> bool:
    if not reply:
        return False
    text = _normalize_factual_text(reply)
    if not text:
        return False
    allowed_durations = {
        int(fact.duration_min)
        for fact in grounding.plan_window
        if fact.duration_min is not None
    }
    for raw_value in re.findall(r"\b(\d{1,3})\s*(?:min|minute|minutes)\b", text):
        value = int(raw_value)
        if allowed_durations and value not in allowed_durations:
            return False

    allowed_dates = _grounding_allowed_dates(grounding)
    for raw_date in re.findall(r"\b20\d{2}-\d{2}-\d{2}\b", text):
        if allowed_dates and raw_date not in allowed_dates:
            return False

    for fact in grounding.plan_window:
        if not _fact_is_referenced_in_reply(fact, text, grounding=grounding):
            continue
        if _reply_claims_empty_slot(text) and fact.slot_kind not in {"free_flexible", "closed"}:
            return False
        mentioned_sports = _mentioned_sports(text)
        non_negated_sports = {
            sport for sport, start in mentioned_sports if not _sport_mention_is_negated(text, start)
        }
        if non_negated_sports and fact.sport and fact.sport not in non_negated_sports:
            return False
        if _reply_claims_done(text) and fact.completion_status not in {"done", "completed"}:
            return False
        if _reply_claims_skipped(text) and fact.completion_status not in {"skipped", "cancelled", "canceled"}:
            return False
        if _reply_claims_adapted(text) and fact.completion_status != "adapted":
            return False
    return True


def _grounded_plan_lookup_fallback_reply(grounding: ReplyGroundingPacket) -> str | None:
    if not grounding.plan_window:
        return "Je ne vois aucune seance planifiee dans la fenetre lue."
    lines: list[str] = []
    for fact in grounding.plan_window[:6]:
        label = str(fact.day_label or fact.scheduled_date.isoformat()).strip().capitalize()
        title = str(fact.title or fact.sport or "Seance").strip()
        pieces = [f"{label}: {title}"]
        if fact.sport:
            pieces.append(fact.sport)
        if fact.duration_min is not None:
            pieces.append(f"{int(fact.duration_min)} min")
        if fact.completion_status:
            pieces.append(f"statut {fact.completion_status}")
        lines.append(", ".join(pieces) + ".")
    return " ".join(lines)


def _grounding_allowed_dates(grounding: ReplyGroundingPacket) -> set[str]:
    dates = {fact.scheduled_date.isoformat() for fact in grounding.plan_window}
    if grounding.local_date is not None:
        dates.add(grounding.local_date.isoformat())
    for refs in grounding.temporal_references.values():
        dates.update(ref.resolved_date.isoformat() for ref in refs)
    return dates


def _fact_is_referenced_in_reply(
    fact: Any,
    text: str,
    *,
    grounding: ReplyGroundingPacket,
) -> bool:
    if fact.scheduled_date.isoformat() in text:
        return True
    day_label = _normalize_factual_text(fact.day_label)
    if day_label and day_label in text:
        return True
    if grounding.local_date is not None:
        delta = (fact.scheduled_date - grounding.local_date).days
        if delta == 0 and "aujourd hui" in text:
            return True
        if delta == 1 and "demain" in text:
            return True
        if delta == -1 and "hier" in text:
            return True
    title = _normalize_factual_text(getattr(fact, "title", ""))
    return bool(title and title in text)


def _reply_claims_empty_slot(text: str) -> bool:
    return any(
        fragment in text
        for fragment in (
            "journee vide",
            "creneau vide",
            "aucune seance",
            "pas de seance",
            "pas d entrainement",
            "rien de prevu",
            "repos",
        )
    )


def _mentioned_sports(text: str) -> set[tuple[str, int]]:
    aliases = {
        "running": ("running", "run", "course", "footing", "fractionne"),
        "swimming": ("swimming", "natation", "nage", "nager", "piscine"),
        "cycling": ("cycling", "velo", "bike", "cyclisme"),
        "strength": ("strength", "renfo", "muscu", "musculation"),
        "climbing": ("climbing", "escalade"),
        "mobility": ("mobility", "mobilite"),
        "rest": ("rest", "repos"),
    }
    found: set[tuple[str, int]] = set()
    for sport, names in aliases.items():
        for name in names:
            pattern = rf"\b{re.escape(name)}\b"
            for match in re.finditer(pattern, text):
                found.add((sport, match.start()))
    return found


def _sport_mention_is_negated(text: str, start: int) -> bool:
    prefix = text[max(0, start - 24):start]
    return any(fragment in prefix for fragment in ("pas de", "pas d", "aucun", "aucune", "sans"))


def _reply_claims_done(text: str) -> bool:
    return _contains_any_word(text, ("faite", "fait", "realisee", "realise", "done"))


def _reply_claims_skipped(text: str) -> bool:
    return _contains_any_word(text, ("manquee", "manque", "skippee", "annulee", "annule"))


def _reply_claims_adapted(text: str) -> bool:
    return _contains_any_word(text, ("adaptee", "adapte", "adapted"))


def _contains_any_word(text: str, words: tuple[str, ...]) -> bool:
    return any(re.search(rf"\b{re.escape(word)}\b", text) for word in words)


def _normalize_factual_text(value: object) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9'-]+", " ", ascii_value).strip()


def _parse_post_event_verdict(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    text = str(raw).strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    verdict = str(payload.get("verdict") or "").strip().lower()
    if verdict not in {"allow", "repair"}:
        return None
    payload["verdict"] = verdict
    if verdict == "repair" and not str(payload.get("repaired_reply") or "").strip():
        return None
    return payload
