from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Sequence

from fitmas.activity_claims import ActivityClaim
from fitmas.execution_evidence import classify_execution_evidence
from fitmas.fitness_snapshot import estimate_scheduled_session_tss
from fitmas.recent_reality import build_recent_reality_window

_QUESTIONABLE_STATUSES = {"planned_pending", "uncertain"}
_SPORT_LABELS = {
    "running": "ta course",
    "swimming": "ta natation",
    "cycling": "ta sortie velo",
    "strength": "ton renfo",
    "climbing": "ta seance d'escalade",
}


@dataclass(frozen=True, slots=True)
class ExecutionClarification:
    question: str
    reason: str
    impact_flags: tuple[str, ...]
    session_id: int | None


def build_execution_clarification(
    *,
    today: date,
    target_session: Any | None,
    target_date: date,
    scheduled_sessions: Sequence[Any],
    activities: Sequence[Any],
    claims: Sequence[ActivityClaim] = (),
) -> ExecutionClarification | None:
    if target_session is None:
        return None
    completion_status = str(_value(target_session, "completion_status") or "").strip().lower()
    if completion_status in {"skipped", "adapted", "rest"}:
        return None

    evidence = classify_execution_evidence(
        planned_session=target_session,
        activities=[activity for activity in activities if _same_local_date(_value(activity, "started_at") or _value(activity, "created_at"), target_date)],
        claims=[claim for claim in claims if claim.resolved_date_iso == target_date.isoformat()],
    )
    if evidence.display_status not in _QUESTIONABLE_STATUSES:
        return None

    current = build_recent_reality_window(
        today=today,
        scheduled_sessions=scheduled_sessions,
        activities=activities,
        claims=claims,
    )
    simulated = build_recent_reality_window(
        today=today,
        scheduled_sessions=scheduled_sessions,
        activities=[*activities, _synthetic_confirmation(target_session)],
        claims=claims,
    )
    impact_flags = _impact_flags(target_session=target_session, current=current, simulated=simulated)
    if not impact_flags:
        return None

    return ExecutionClarification(
        question=_build_question(target_session=target_session, evidence_state=evidence.evidence_state),
        reason=_build_reason(impact_flags),
        impact_flags=impact_flags,
        session_id=_int(_value(target_session, "id")),
    )


def _impact_flags(
    *,
    target_session: Any,
    current,
    simulated,
) -> tuple[str, ...]:
    flags: list[str] = []
    if _is_key_session(target_session) and simulated.key_sessions_salvaged_7d > current.key_sessions_salvaged_7d:
        flags.append("key_session_salvaged")
    if current.compliance_confirmed <= 0.5 < simulated.compliance_confirmed:
        flags.append("restart_completion_threshold")
    if current.load_ratio < 0.65 <= simulated.load_ratio:
        flags.append("restart_load_threshold")
    if current.compliance_confirmed_14d < 0.6 <= simulated.compliance_confirmed_14d:
        flags.append("consistency_14d_threshold")
    if current.missed_streak_days >= 2 and simulated.missed_streak_days < 2:
        flags.append("missed_streak_reset")
    return tuple(flags)


def _build_question(*, target_session: Any, evidence_state: str) -> str:
    sport = str(_value(target_session, "sport_type") or "").strip().lower()
    subject = _SPORT_LABELS.get(sport) or _fallback_subject(target_session)
    if evidence_state == "candidate":
        return f"Je vois une trace possible pour {subject} hier, mais pas assez nette. Tu l'as faite ou non ?"
    return f"Je ne vois pas de trace de {subject} hier. Tu l'as faite ou non ?"


def _build_reason(impact_flags: Sequence[str]) -> str:
    mapping = {
        "key_session_salvaged": "ça change la lecture des seances cle recentes",
        "restart_completion_threshold": "ça peut changer la relance de semaine basee sur la completion recente",
        "restart_load_threshold": "ça peut changer la lecture charge prevue vs observee",
        "consistency_14d_threshold": "ça change la lecture de regularite sur 14 jours",
        "missed_streak_reset": "ça peut casser la serie recente de jours manques",
    }
    return "; ".join(mapping[flag] for flag in impact_flags if flag in mapping)


def _synthetic_confirmation(session: Any) -> dict[str, Any]:
    return {
        "id": None,
        "sport_type": _value(session, "sport_type"),
        "scheduled_session_id": _value(session, "id"),
        "started_at": _value(session, "scheduled_date"),
        "duration_min": _value(session, "duration_min"),
        "tss": round(estimate_scheduled_session_tss(session), 1),
    }


def _is_key_session(session: Any) -> bool:
    priority = str(_value(session, "priority") or "").strip().lower()
    if priority in {"high", "key", "important"}:
        return True
    return (_int(_value(session, "load_score")) or 0) >= 3


def _fallback_subject(session: Any) -> str:
    title = str(_value(session, "session_title") or "").strip().lower()
    return title or "ta seance"


def _same_local_date(value: Any, target_date: date) -> bool:
    if value is None:
        return False
    if hasattr(value, "date"):
        try:
            return value.date() == target_date
        except TypeError:
            return value == target_date
    if isinstance(value, str):
        return value[:10] == target_date.isoformat()
    return False


def _value(obj: Any, key: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
