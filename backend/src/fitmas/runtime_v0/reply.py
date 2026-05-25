from __future__ import annotations

import json
from datetime import date, timedelta

from fitmas.runtime_v0.llm_clients.base import LLMClient
from fitmas.runtime_v0.result import RuntimeResult
from fitmas.runtime_v0.snapshot import WorldSnapshot

TECHNICAL_FALLBACK = "Je n'ai pas pu traiter ça proprement. Réessaie dans un instant."
WEEKDAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")

class ReplyComposer:
    def __init__(self, llm_client: LLMClient, system_prompt: str):
        self.llm_client = llm_client
        self.system_prompt = system_prompt

    def compose(self, result: RuntimeResult, snapshot: WorldSnapshot, repair: bool = False) -> str:
        if result.policy_action == "ask_clarification" and result.read_facts: return result.read_facts[0]
        if result.pending is not None:
            return _pending_confirmation(result)
        try:
            response = self.llm_client.chat_with_tools(
                self.system_prompt, [{"role": "user", "content": _payload(result, snapshot)}], [],
            )
        except Exception:
            return _fallback(result, snapshot)
        if response.text and response.text.strip():
            text = response.text.strip()
            if commit := _commit_summary(result, snapshot, text):
                return commit
            if _omits_plan_sessions(text, result, snapshot):
                return _plan_summary(result) if repair else ReplyComposer(self.llm_client, f"{self.system_prompt}\nRéponse rejetée: cite ces séances: {_plan_summary(result)}").compose(result, snapshot, True)
            return text
        return _fallback(result, snapshot)
def _payload(result: RuntimeResult, snapshot: WorldSnapshot) -> str:
    return json.dumps(
        {
            "today": snapshot.today.isoformat(),
            "committed_events": [
                {"type": event.command_type, "target_id": event.target_id, "reason": event.reason}
                for event in result.committed_events
            ],
            "read_facts": list(result.read_facts),
            "pending": result.pending.summary if result.pending else None,
            "blocked_reasons": list(result.blocked_reasons),
            "reply_contract": {
                "must_include": list(result.reply_contract.must_include),
                "must_not_claim": list(result.reply_contract.must_not_claim),
                "tone": result.reply_contract.tone,
                "max_sentences": result.reply_contract.max_sentences,
            },
        },
        ensure_ascii=False,
        sort_keys=True,
    )

def _fallback(result: RuntimeResult, snapshot: WorldSnapshot) -> str:
    if result.committed_events:
        return _commit_summary(result, snapshot, "") or TECHNICAL_FALLBACK
    if result.pending is not None:
        return _pending_confirmation(result)
    if result.policy_action == "answer_only" and result.read_facts:
        return _plan_summary(result) or " ".join(fact.split(".")[0].strip() for fact in result.read_facts[:3] if fact.strip())
    return TECHNICAL_FALLBACK

def _pending_confirmation(result: RuntimeResult) -> str:
    if result.pending is None:
        return TECHNICAL_FALLBACK
    return f"Je dois confirmer avant de faire ça: {result.pending.summary}."

def _commit_summary(result: RuntimeResult, snapshot: WorldSnapshot, reply: str) -> str:
    if not result.committed_events:
        return ""
    lower = reply.lower()
    event = result.committed_events[-1]
    if event.command_type == "CorrectSessionStatusCommand":
        minutes = str(event.after.get("duration_min"))
        return "" if "corrig" in lower and minutes in reply else f"Corrigé: {minutes} minutes."
    if event.command_type == "SetSessionStatusCommand":
        day = "hier" if event.after.get("date") == (snapshot.today - timedelta(days=1)).isoformat() else "la séance"
        return "" if "noté" in lower and day in lower else f"Noté pour {day}."
    if event.command_type == "ApplyPlanPatchCommand":
        target = next((item.get("date") for item in event.after.values() if isinstance(item, dict)), "")
        day = WEEKDAYS[date.fromisoformat(target).weekday()] if target else "la nouvelle date"
        return "" if "déplacé" in lower and day in lower else f"Déplacé à {day}."
    return ""

def _plan_summary(result: RuntimeResult) -> str:
    sessions = _read_sessions(result)
    return " ".join(f"{str(item.get('date'))[-2:]} {item.get('title', 'Séance')}." for item in sessions)

def _omits_plan_sessions(reply: str, result: RuntimeResult, snapshot: WorldSnapshot) -> bool:
    lower = reply.lower()
    return any((date_text := str(item.get("date", "")))[-2:] not in lower and not (date_text == snapshot.today.isoformat() and "aujourd" in lower) for item in _read_sessions(result))

def _read_sessions(result: RuntimeResult) -> list[dict]:
    sessions: list[dict] = []
    for fact in result.read_facts:
        try:
            payload = json.loads(fact)
        except Exception:
            continue
        sessions.extend(item for item in payload.get("sessions", ()) if isinstance(item, dict))
    return sessions
