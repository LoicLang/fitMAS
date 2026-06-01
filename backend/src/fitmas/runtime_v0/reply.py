from __future__ import annotations

import json
from datetime import date, timedelta

from fitmas.runtime_v0.executor import CommandEvent
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
        # No_send + move actif: payload vide (0 commit/pending/block) -> le LLM produit
        # un non-sequitur. Filet honnête qui garde la conversation de move vivante.
        floor = _no_send_move_floor(result, snapshot)
        if floor:
            return floor
        # Tous les cas passent par le LLM: la voix vit ici, le guard (hors composer)
        # garantit qu'elle ne ment pas. Les templates ne servent plus que de filet
        # de secours via _fallback quand le LLM echoue ou se tait.
        try:
            response = self.llm_client.chat_with_tools(
                self.system_prompt, [{"role": "user", "content": _payload(result, snapshot)}], [],
            )
        except Exception:
            return _fallback(result, snapshot)
        if response.text and response.text.strip():
            text = response.text.strip()
            if result.committed_events and _commit_omits_fact(result, snapshot, text):
                return _commit_summary(result, snapshot) if repair else ReplyComposer(self.llm_client, f"{self.system_prompt}\nRéponse rejetée: confirme clairement ce changement: {_commit_summary(result, snapshot)}").compose(result, snapshot, True)
            if result.policy_action == "answer_only" and _omits_plan_sessions(text, result, snapshot):
                return _plan_summary(result) if repair else ReplyComposer(self.llm_client, f"{self.system_prompt}\nRéponse rejetée: cite ces séances: {_plan_summary(result)}").compose(result, snapshot, True)
            return text
        return _fallback(result, snapshot)
def _payload(result: RuntimeResult, snapshot: WorldSnapshot) -> str:
    return json.dumps(
        {
            "today": snapshot.today.isoformat(),
            "committed_events": [
                {"type": event.command_type, "target_id": event.target_id, "reason": event.reason, "change": _committed_change(event, snapshot.today)}
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

def _no_send_move_floor(result: RuntimeResult, snapshot: WorldSnapshot) -> str:
    if result.proposal_type != "no_send":
        return ""
    intent = snapshot.conversation_state.last_unresolved_intent
    if not intent or intent.get("type") != "move_session":
        return ""
    raw = intent.get("target_date")
    try:
        target = date.fromisoformat(raw) if isinstance(raw, str) else None
    except ValueError:
        target = None
    day = _day_label(target.isoformat(), snapshot.today) if target else "la date prévue"
    return f"Je veux être sûr de viser la bonne séance avant de la décaler à {day}. C'est laquelle exactement ?"

def _fallback(result: RuntimeResult, snapshot: WorldSnapshot) -> str:
    # Le filet rend la meilleure vérité disponible, jamais le message technique
    # sec tant qu'on a mieux à dire. Une mutation réelle prime; sinon pending,
    # blocage, clarification, réponse plan. On ne court-circuite plus sur des
    # commandes de bookkeeping (état conversation, création de pending) qui
    # n'ont pas de résumé utilisateur.
    summary = _commit_summary(result, snapshot)
    if summary:
        return summary
    if result.pending is not None:
        return _pending_confirmation(result)
    if result.blocked_reasons:
        return _blocked_summary(result.blocked_reasons[-1])
    if result.policy_action == "ask_clarification" and result.read_facts:
        return result.read_facts[0]
    if result.policy_action == "answer_only" and result.read_facts:
        return _plan_summary(result) or " ".join(fact.split(".")[0].strip() for fact in result.read_facts[:3] if fact.strip())
    return TECHNICAL_FALLBACK

def _blocked_summary(reason: str) -> str:
    if reason == "health_fact_blocks_hard":
        return "Je bloque: trop risqué avec le signal santé actif."
    if reason == "hard_session_too_dense":
        return "Je bloque: trop de densité dure autour de cette date."
    if reason == "done_session_protected":
        return "Je bloque: cette séance est déjà faite."
    if reason == "plan_patch_has_no_effect":
        return "Je bloque: le changement proposé n'est pas assez précis."
    return "Je bloque: ce changement n'est pas assez sûr."

def _pending_confirmation(result: RuntimeResult) -> str:
    if result.pending is None:
        return TECHNICAL_FALLBACK
    return f"Je dois confirmer avant de faire ça: {result.pending.summary}."

def _committed_change(event: CommandEvent, today: date) -> str:
    # Le changement vérifié, en clair. Nourrit le LLM (payload) pour qu'il
    # phrase la vérité avec sa voix, ET sert de filet déterministe quand cette
    # voix ne porte pas le fait.
    if event.command_type == "CorrectSessionStatusCommand":
        return _correction_summary(event.after)
    if event.command_type == "SetSessionStatusCommand":
        day = "hier" if event.after.get("date") == (today - timedelta(days=1)).isoformat() else "la séance"
        return _status_summary(event.after, day)
    if event.command_type == "ApplyPlanPatchCommand":
        return _plan_patch_summary(event.before, event.after, today)
    return ""

def _commit_summary(result: RuntimeResult, snapshot: WorldSnapshot) -> str:
    event = _summarizable_event(result, snapshot.today)
    return _committed_change(event, snapshot.today) if event else ""

def _summarizable_event(result: RuntimeResult, today: date) -> CommandEvent | None:
    # La dernière mutation résumable: on saute les commandes de bookkeeping
    # (état conversation, création de pending) dont _committed_change renvoie "".
    for event in reversed(result.committed_events):
        if _committed_change(event, today):
            return event
    return None

def _commit_omits_fact(result: RuntimeResult, snapshot: WorldSnapshot, reply: str) -> bool:
    # On ne vérifie plus un verbe ("noté", "corrigé") mais le fait qui porte la
    # vérité du commit: durée, jour cible, sport. La voix est libre tant qu'elle
    # énonce ce fait. Aucun fait robuste à exiger → on fait confiance à la voix.
    event = _summarizable_event(result, snapshot.today)
    if event is None:
        return False
    lower = reply.lower()
    return any(token.lower() not in lower for token in _commit_fact_tokens(event, snapshot.today))

def _commit_fact_tokens(event: CommandEvent, today: date) -> tuple[str, ...]:
    after = event.after
    if event.command_type in ("SetSessionStatusCommand", "CorrectSessionStatusCommand"):
        duration = after.get("duration_min")
        return (str(duration),) if duration is not None else ()
    if event.command_type == "ApplyPlanPatchCommand":
        before_session, after_session = _first_patch_pair(event.before, after)
        if not after_session:
            return ()
        moved = (not before_session and after_session.get("date")) or (
            before_session is not None and before_session.get("date") != after_session.get("date")
        )
        if moved:
            target = after_session.get("date", "")
            return (WEEKDAYS[date.fromisoformat(target).weekday()],) if target else ()
        if before_session is not None and before_session.get("sport") != after_session.get("sport"):
            sport = _sport_label(after_session.get("sport"))
            return (sport,) if sport else ()
        if before_session is not None and (
            before_session.get("intensity_label") != after_session.get("intensity_label")
            or before_session.get("duration_min") != after_session.get("duration_min")
        ):
            duration = after_session.get("duration_min")
            if duration is not None:
                return (str(duration),)
            intensity = _intensity_label(after_session.get("intensity_label"))
            return (intensity,) if intensity else ()
    return ()

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

def _correction_summary(after: dict) -> str:
    status = after.get("status")
    duration = after.get("duration_min")
    if status == "done":
        suffix = f", {duration} minutes" if duration is not None else ""
        return f"Corrigé: séance faite{suffix}."
    if status == "partial":
        suffix = f", {duration} minutes" if duration is not None else ""
        return f"Corrigé: partiel{suffix}."
    if status == "skipped":
        return "Corrigé: séance notée non faite."
    if status == "planned":
        return "Corrigé: statut revenu à prévu."
    return "Corrigé."

def _status_summary(after: dict, day: str) -> str:
    status = after.get("status")
    duration = after.get("duration_min")
    if status == "partial":
        suffix = f", {duration} minutes" if duration is not None else ""
        return f"Noté pour {day}: partiel{suffix}."
    if status == "done":
        suffix = f", {duration} minutes" if duration is not None else ""
        return f"Noté pour {day}: fait{suffix}."
    if status == "skipped":
        return f"Noté pour {day}."
    return f"Noté pour {day}."

def _plan_patch_summary(before: dict, after: dict, today: date) -> str:
    before_session, after_session = _first_patch_pair(before, after)
    if not after_session:
        return "Modification appliquée."
    if not before_session and after_session.get("date"):
        target = after_session.get("date", "")
        day = WEEKDAYS[date.fromisoformat(target).weekday()] if target else "la nouvelle date"
        return f"Déplacé à {day}."
    if before_session and before_session.get("date") != after_session.get("date"):
        target = after_session.get("date", "")
        day = WEEKDAYS[date.fromisoformat(target).weekday()] if target else "la nouvelle date"
        return f"Déplacé à {day}."
    if before_session and before_session.get("sport") != after_session.get("sport"):
        day = _day_label(after_session.get("date"), today)
        sport = _sport_label(after_session.get("sport"))
        intensity = _intensity_label(after_session.get("intensity_label"))
        suffix = f" {intensity}" if intensity else ""
        return f"Remplacé {day} par {sport}{suffix}."
    if before_session and (
        before_session.get("intensity_label") != after_session.get("intensity_label")
        or before_session.get("duration_min") != after_session.get("duration_min")
    ):
        day = _day_label(after_session.get("date"), today)
        duration = after_session.get("duration_min")
        intensity = _intensity_label(after_session.get("intensity_label"))
        details = ", ".join(str(item) for item in (f"{duration} minutes" if duration else None, intensity) if item)
        return f"Allégé {day}: {details}." if details else f"Allégé {day}."
    return "Modification appliquée."

def _day_label(value: object, today: date) -> str:
    if not isinstance(value, str):
        return "la séance"
    try:
        target = date.fromisoformat(value)
    except ValueError:
        return "la séance"
    if target == today:
        return "aujourd'hui"
    if target == today + timedelta(days=1):
        return "demain"
    return WEEKDAYS[target.weekday()]

def _sport_label(value: object) -> str:
    labels = {
        "bike": "vélo",
        "cycling": "vélo",
        "run": "course",
        "running": "course",
        "swim": "natation",
        "swimming": "natation",
        "strength": "renfo",
        "mobility": "mobilité",
        "rest": "repos",
    }
    text = str(value or "")
    return labels.get(text, text)

def _intensity_label(value: object) -> str:
    labels = {"easy": "facile", "moderate": "modéré", "hard": "dur"}
    text = str(value or "")
    return labels.get(text, text)

def _first_patch_pair(before: dict, after: dict) -> tuple[dict | None, dict | None]:
    for key, after_item in after.items():
        if isinstance(after_item, dict):
            before_item = before.get(key)
            return before_item if isinstance(before_item, dict) else None, after_item
    return None, None
