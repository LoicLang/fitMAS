from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import json
import re

from fitmas.runtime_v0.reply import TECHNICAL_FALLBACK
from fitmas.runtime_v0.result import RuntimeResult

CLAIM_PATTERN = re.compile(r"\b(j'ai|j'ai bien|c'est)\s+(déplacé|noté|enregistré|fait|modifié|appliqué)\b", re.IGNORECASE)
PENDING_ACTION_PATTERN = re.compile(r"\b(c'est fait|appliqué)\b", re.IGNORECASE)
JARGON_PATTERN = re.compile(r"\b(policy|backend|candidate|mutation|runtime|tool_call|proposal|snapshot)\b", re.IGNORECASE)
TOOL_LEAK_PATTERN = re.compile(r"\b(get_\w+|propose_\w+|resolve_date_reference|runtime_contract|ask_clarification|plan_patch|swap_sessions)\b", re.IGNORECASE)
ENGLISH_LEAK_PATTERN = re.compile(r"\b(i'?ll|i'?ve|i will|let me|here'?s|please confirm|do you want|your (?:session|plan|workout)|the (?:session|plan|workout))\b", re.IGNORECASE)
META_PATTERN = re.compile(r"\b(l'utilisateur|the user|option valide)\b", re.IGNORECASE)
DATE_PATTERN = re.compile(r"\b20\d{2}-\d{2}-\d{2}\b")
RAW_JSON_PATTERN = re.compile(r"[{}]|\b(sessions|duration_min|target_session_id)\b", re.IGNORECASE)
TECHNICAL_ID_PATTERN = re.compile(r"\b(session_id|source_ref|target_session_id|ID\s*\d+)\b", re.IGNORECASE)
TRUNCATED_END_PATTERN = re.compile(r"\b(avec|et|pour|:)\s*$", re.IGNORECASE)

@dataclass(frozen=True)
class GuardResult:
    ok: bool
    blocked_reasons: tuple[str, ...]
    sanitized_reply: str

class OutputGuard:
    def __init__(self, today: date):
        self.today = today

    def verify(self, reply: str, result: RuntimeResult) -> GuardResult:
        reasons: list[str] = []
        if not result.committed_events and CLAIM_PATTERN.search(reply):
            reasons.append("claim_without_event")
        if result.pending is not None and PENDING_ACTION_PATTERN.search(reply):
            reasons.append("pending_action_claim")
        if JARGON_PATTERN.search(reply) or TOOL_LEAK_PATTERN.search(reply):
            reasons.append("internal_jargon")
        if META_PATTERN.search(reply):
            reasons.append("meta_opening")
        if ENGLISH_LEAK_PATTERN.search(reply):
            reasons.append("english_leak")
        if RAW_JSON_PATTERN.search(reply):
            reasons.append("raw_json_visible")
        if TECHNICAL_ID_PATTERN.search(reply):
            reasons.append("technical_id_visible")
        if TRUNCATED_END_PATTERN.search(reply):
            reasons.append("truncated_reply")
        for date_text in DATE_PATTERN.findall(reply):
            if result.policy_action == "answer_only" and not _in_read_facts(date_text, result):
                reasons.append("unsupported_date")
                break
        for date_text in DATE_PATTERN.findall(reply):
            parsed = date.fromisoformat(date_text)
            if parsed < self.today - timedelta(days=7) and not _in_read_facts(date_text, result):
                reasons.append("old_plan_date")
                break
        if reasons:
            return GuardResult(False, tuple(reasons), _safe_reply(result, self.today))
        return GuardResult(True, (), reply)

def _in_read_facts(value: str, result: RuntimeResult) -> bool:
    return any(value in fact for fact in result.read_facts)

def _safe_reply(result: RuntimeResult, today: date) -> str:
    if result.pending is not None:
        return f"Je dois confirmer avant de faire ça: {result.pending.summary}."
    if result.blocked_reasons:
        return "Je ne peux pas valider ça proprement pour l'instant."
    if result.policy_action == "ask_clarification" and result.read_facts:
        return result.read_facts[0]
    if result.policy_action == "answer_only" and result.read_facts:
        return _answer_from_read_facts(result) or TECHNICAL_FALLBACK
    if result.committed_events:
        event = result.committed_events[-1]
        if event.command_type == "CorrectSessionStatusCommand":
            return f"Corrigé: {event.after.get('duration_min')} minutes."
        if event.command_type == "SetSessionStatusCommand":
            return f"Noté pour {'hier' if event.after.get('date') == (today - timedelta(days=1)).isoformat() else 'la séance'}."
    return TECHNICAL_FALLBACK

def _answer_from_read_facts(result: RuntimeResult) -> str:
    sessions: list[dict] = []
    for fact in result.read_facts:
        try:
            payload = json.loads(fact)
        except Exception:
            continue
        if isinstance(payload, dict):
            sessions.extend(item for item in payload.get("sessions", ()) if isinstance(item, dict))
    if sessions:
        return " ".join(f"{str(item.get('date', ''))[-2:]} {item.get('title', 'Séance')}." for item in sessions)
    return " ".join(fact.split(".")[0].strip() for fact in result.read_facts[:3] if fact.strip())
