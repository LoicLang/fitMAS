"""Coach reading digest — pre-digested coach context for proactive messages.

Replaces raw dashboard counters (compliance %, TSS, load ratio) with what a
coach actually needs before speaking: what really happened, what was planned,
what the user said, what the user tends to do, and a short pre-pass lens
(sens_du_jour / angle / ne_pas_faire) produced by an LLM that "reads" the
facts before the final message is composed.

The lens is cheap (Haiku, JSON, ~200 tokens) but gated: if it fails, we inject
just the facts — the final briefing LLM still has enough ground-truth to speak
coherently.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from time import perf_counter
from typing import Any, Sequence

from sqlalchemy.orm import Session

from fitmas.core import orm as s
from fitmas.domain.execution.helpers import (
    activities_last_days as _activities_last_days,
    claimed_activities_last_days as _claimed_activities_last_days,
)
from fitmas.domain.coaching import repo_conversation
from fitmas.domain.memory import repository as memory_repo
from fitmas.llm.gateway import request_json
from fitmas.domain.execution.recent_reality import RecentRealityWindow
from fitmas.domain.planning import repository as planning_repo

logger = logging.getLogger(__name__)

REST_SPORTS = {"rest", "off"}
DAY_LABEL_SHORT = {0: "lun", 1: "mar", 2: "mer", 3: "jeu", 4: "ven", 5: "sam", 6: "dim"}


@dataclass(frozen=True, slots=True)
class RealEntry:
    day_label: str       # "lun", "sam"
    sport: str           # "running", "velo"
    duration_min: int
    linked_to_plan: bool  # True if scheduled_session_id != null


@dataclass(frozen=True, slots=True)
class ExchangeEntry:
    when_label: str      # "mar 14h"
    speaker: str         # "user" | "coach"
    text: str


@dataclass(frozen=True, slots=True)
class CoachReadingFacts:
    real_entries: tuple[RealEntry, ...]
    planned_total_7d: int
    confirmed_total_7d: int       # matches plan
    offplan_total_7d: int         # activity without scheduled_session_id
    missed_streak_days: int
    silence_days: int             # days since last user message
    exchanges_7d: tuple[ExchangeEntry, ...]
    patterns: tuple[str, ...]
    day_context: str              # "lundi matin, semaine neuve"


@dataclass(frozen=True, slots=True)
class CoachReadingLens:
    sens_du_jour: str
    angle: str
    ne_pas_faire: str


@dataclass(frozen=True, slots=True)
class CoachReadingDigest:
    facts: CoachReadingFacts
    lens: CoachReadingLens | None


# ---------------------------------------------------------------------------
# Facts builder — deterministic
# ---------------------------------------------------------------------------

def build_coach_reading_facts(
    db: Session,
    user: s.User,
    *,
    today: date,
    recent_reality: RecentRealityWindow | None = None,
) -> CoachReadingFacts:
    window_start = today - timedelta(days=6)

    real_entries = _build_real_entries(db, user, today=today, window_start=window_start)
    planned, confirmed = _count_plan_vs_confirmed(db, user, today=today, window_start=window_start)
    offplan = sum(1 for entry in real_entries if not entry.linked_to_plan)

    silence_days = _compute_silence_days(db, user, today=today)
    exchanges = _build_recent_exchanges(db, user, today=today)
    patterns = _format_patterns(memory_repo.get_active_patterns(db, user.id, limit=4))
    day_context = _render_day_context(today)

    missed_streak = recent_reality.missed_streak_days if recent_reality is not None else 0

    return CoachReadingFacts(
        real_entries=tuple(real_entries),
        planned_total_7d=planned,
        confirmed_total_7d=confirmed,
        offplan_total_7d=offplan,
        missed_streak_days=missed_streak,
        silence_days=silence_days,
        exchanges_7d=tuple(exchanges),
        patterns=tuple(patterns),
        day_context=day_context,
    )


def _build_real_entries(
    db: Session,
    user: s.User,
    *,
    today: date,
    window_start: date,
) -> list[RealEntry]:
    activities = _activities_last_days(db, user, days=7)
    entries: list[RealEntry] = []
    for activity in activities:
        started = getattr(activity, "started_at", None) or getattr(activity, "created_at", None)
        activity_date = _as_date(started)
        if activity_date is None or not (window_start <= activity_date <= today):
            continue
        weekday = activity_date.weekday()
        entries.append(
            RealEntry(
                day_label=DAY_LABEL_SHORT.get(weekday, "?"),
                sport=str(getattr(activity, "sport_type", "") or "sport").strip().lower(),
                duration_min=int(getattr(activity, "duration_min", 0) or 0),
                linked_to_plan=getattr(activity, "scheduled_session_id", None) is not None,
            )
        )
    entries.sort(key=lambda e: (e.day_label, e.sport))
    return entries


def _count_plan_vs_confirmed(
    db: Session,
    user: s.User,
    *,
    today: date,
    window_start: date,
) -> tuple[int, int]:
    sessions = planning_repo.get_scheduled_sessions_between_dates(
        db, user.id,
        start_date=window_start,
        end_date=today,
        limit=42,
    )
    planned = 0
    confirmed = 0
    for session in sessions:
        sport = str(getattr(session, "sport_type", "") or "").lower()
        if sport in REST_SPORTS:
            continue
        planned += 1
        if str(getattr(session, "completion_status", "") or "").lower() == "done":
            confirmed += 1
    return planned, confirmed


def _compute_silence_days(db: Session, user: s.User, *, today: date) -> int:
    turns = repo_conversation.get_recent_conversation_turns(db, user.id, limit=10)
    last_user_at: datetime | None = None
    for turn in turns:
        if not str(getattr(turn, "user_message", "") or "").strip():
            continue
        created = getattr(turn, "created_at", None)
        if created is None:
            continue
        if last_user_at is None or created > last_user_at:
            last_user_at = created
    if last_user_at is None:
        return 0
    delta = today - last_user_at.date()
    return max(delta.days, 0)


def _build_recent_exchanges(
    db: Session,
    user: s.User,
    *,
    today: date,
    limit: int = 12,
) -> list[ExchangeEntry]:
    """Last 7 days of exchanges, with a guarantee that at least the last turn is
    included even if it's older than 7 days (avoids amnesia on long silence)."""
    turns = repo_conversation.get_recent_conversation_turns(db, user.id, limit=limit)
    if not turns:
        return []

    window_start = today - timedelta(days=6)
    entries: list[ExchangeEntry] = []
    for turn in turns:
        created = getattr(turn, "created_at", None)
        if created is None:
            continue
        turn_date = created.date()
        if turn_date < window_start and entries:
            # outside 7d and we already have something — stop
            break
        label = _format_exchange_time(created)
        user_text = str(getattr(turn, "user_message", "") or "").strip()
        assistant_text = str(getattr(turn, "assistant_message", "") or "").strip()
        if user_text:
            entries.append(ExchangeEntry(when_label=label, speaker="user", text=_truncate(user_text, 140)))
        if assistant_text:
            entries.append(ExchangeEntry(when_label=label, speaker="coach", text=_truncate(assistant_text, 140)))
        if turn_date < window_start:
            # last-turn fallback already included — stop here
            break

    entries.reverse()  # chronological
    return entries[-10:]


def _format_patterns(patterns: Sequence[s.UserPattern]) -> list[str]:
    rendered: list[str] = []
    for pattern in patterns:
        value = str(getattr(pattern, "value", "") or "").strip()
        if not value:
            continue
        rendered.append(_truncate(value, 120))
    return rendered[:4]


def _render_day_context(today: date) -> str:
    weekday = today.weekday()
    day_name = {0: "lundi", 1: "mardi", 2: "mercredi", 3: "jeudi", 4: "vendredi", 5: "samedi", 6: "dimanche"}[weekday]
    if weekday == 0:
        phase = "semaine neuve"
    elif weekday in (1, 2):
        phase = "debut de semaine"
    elif weekday == 3:
        phase = "milieu de semaine"
    elif weekday == 4:
        phase = "fin de semaine en approche"
    else:
        phase = "week-end"
    return f"{day_name}, {phase}"


def _format_exchange_time(moment: datetime) -> str:
    weekday = moment.weekday()
    return f"{DAY_LABEL_SHORT.get(weekday, '?')} {moment.strftime('%Hh')}"


def _truncate(text: str, length: int) -> str:
    text = text.strip()
    if len(text) <= length:
        return text
    return text[: length - 1].rstrip() + "…"


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return None


# ---------------------------------------------------------------------------
# Lens builder — LLM pre-pass (Haiku, JSON)
# ---------------------------------------------------------------------------

_LENS_SYSTEM = """Tu es un coach sportif IA qui lit les faits d'une semaine AVANT de parler a l'athlete.
Tu ne redige PAS de message pour l'athlete. Tu produis une lecture interne en JSON.

Regles :
- reponds UNIQUEMENT avec un JSON valide aux cles "sens_du_jour", "angle", "ne_pas_faire"
- chaque valeur = une phrase courte, factuelle, operationnelle
- "sens_du_jour" : ta lecture de ce qui se passe (1 phrase)
- "angle" : l'angle par lequel aborder l'athlete (1 phrase)
- "ne_pas_faire" : ce qu'il faut eviter explicitement dans le message final (1 phrase, liste separee par virgules ok)
- ne moralise pas, ne felicite pas vide, n'invente pas de chiffres
- si l'athlete a fait des sorties offplan, reconnais-le; ne dis jamais "zero realisees" quand il y a des offplan
- si la strength (ou tout type) saute depuis plusieurs semaines, note-le comme question pas comme jugement

Exemples de sortie valide :

Faits : 2 sorties offplan, 3 plan rate, strength saute 3e fois, silence 4j, dernier msg "trop de taf"
{"sens_du_jour": "Il a bouge mais pas execute le plan. Le trou c'est strength, 3e semaine.", "angle": "Reconnaitre les 2 sorties, questionner la strength sans juger.", "ne_pas_faire": "dire zero realisees, parler sommeil/assiette, moraliser, re-demander jeudi qui a deja ete ignore"}

Faits : 0 sortie, 4 plan rate, silence 6j, pas de blessure declaree
{"sens_du_jour": "Rupture de rythme anormale, pas juste un manque d'envie.", "angle": "Ouvrir, comprendre avant de proposer quoi que ce soit.", "ne_pas_faire": "proposer une seance, remotiver, lister la charge"}

Faits : 4 sorties conformes, dernier msg "bien senti le seuil"
{"sens_du_jour": "Execution propre, pas de drama.", "angle": "Saluer sans flatter, teaser la suite.", "ne_pas_faire": "lister les 4 seances, parler TSS/CTL, reciter la meteo"}"""


def build_coach_reading_lens(
    facts: CoachReadingFacts,
    *,
    model: str = "claude-haiku-4-5-20251001",
) -> CoachReadingLens | None:
    prompt = _render_facts_for_lens(facts)
    started_at = perf_counter()
    try:
        payload = request_json(
            system=_LENS_SYSTEM,
            prompt=prompt,
            model=model,
            max_tokens=400,
        )
    except Exception:
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        logger.warning(
            "coach_reading_lens.failed reason=exception model=%s elapsed_ms=%d",
            model, elapsed_ms,
            exc_info=True,
        )
        return None
    elapsed_ms = int((perf_counter() - started_at) * 1000)
    if not isinstance(payload, dict):
        logger.info(
            "coach_reading_lens.dropped reason=non_dict model=%s elapsed_ms=%d",
            model, elapsed_ms,
        )
        return None
    sens = _clean_lens_field(payload.get("sens_du_jour"))
    angle = _clean_lens_field(payload.get("angle"))
    avoid = _clean_lens_field(payload.get("ne_pas_faire"))
    missing = [
        field for field, value in (
            ("sens_du_jour", sens), ("angle", angle), ("ne_pas_faire", avoid),
        ) if not value
    ]
    if missing:
        logger.info(
            "coach_reading_lens.dropped reason=missing_fields fields=%s model=%s elapsed_ms=%d",
            ",".join(missing), model, elapsed_ms,
        )
        return None
    logger.info(
        "coach_reading_lens.ok model=%s elapsed_ms=%d sens=%r angle=%r avoid=%r",
        model, elapsed_ms,
        sens[:140], angle[:140], avoid[:140],
    )
    return CoachReadingLens(sens_du_jour=sens, angle=angle, ne_pas_faire=avoid)


def _clean_lens_field(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def _render_facts_for_lens(facts: CoachReadingFacts) -> str:
    lines = ["Lis ces faits puis produis ton JSON.", "", "Faits :"]
    lines.append(_render_real_line(facts))
    lines.append(
        f"- Plan 7j : {facts.planned_total_7d} prevues, {facts.confirmed_total_7d} executees conformes"
        + (f", {facts.missed_streak_days}j consecutifs sans seance realisee" if facts.missed_streak_days > 0 else "")
    )
    lines.append(f"- Silence user : {facts.silence_days}j depuis le dernier message")
    if facts.exchanges_7d:
        lines.append("- Derniers echanges :")
        for entry in facts.exchanges_7d:
            lines.append(f'    {entry.when_label}  {entry.speaker}  : "{entry.text}"')
    if facts.patterns:
        lines.append("- Patterns connus :")
        for pattern in facts.patterns:
            lines.append(f"    - {pattern}")
    lines.append(f"- Contexte : {facts.day_context}")
    return "\n".join(lines)


def _render_real_line(facts: CoachReadingFacts) -> str:
    if not facts.real_entries:
        return "- Reel 7j : 0 sortie"
    chunks = [
        f"{entry.sport} {entry.duration_min}' {entry.day_label}"
        + (" (offplan)" if not entry.linked_to_plan else "")
        for entry in facts.real_entries
    ]
    return f"- Reel 7j : {', '.join(chunks)}"


# ---------------------------------------------------------------------------
# Full digest
# ---------------------------------------------------------------------------

def build_coach_reading_digest(
    db: Session,
    user: s.User,
    *,
    today: date,
    recent_reality: RecentRealityWindow | None = None,
) -> CoachReadingDigest:
    facts = build_coach_reading_facts(db, user, today=today, recent_reality=recent_reality)
    lens = build_coach_reading_lens(facts)
    return CoachReadingDigest(facts=facts, lens=lens)


# ---------------------------------------------------------------------------
# Prompt rendering
# ---------------------------------------------------------------------------

def render_digest_for_prompt(digest: CoachReadingDigest) -> str:
    """Render the digest as a single block injectable into a briefing prompt."""
    facts = digest.facts
    lines: list[str] = ["Lecture de la semaine (verite terrain, utilise ces chiffres tels quels) :"]
    lines.append(_render_real_line(facts))
    plan_line = f"- Plan 7j : {facts.planned_total_7d} prevues, {facts.confirmed_total_7d} executees conformes"
    if facts.offplan_total_7d > 0:
        plan_line += f", {facts.offplan_total_7d} sortie(s) hors plan"
    if facts.missed_streak_days > 0:
        plan_line += f", {facts.missed_streak_days}j consecutifs sans seance realisee"
    lines.append(plan_line)
    lines.append(f"- Silence user : {facts.silence_days}j depuis le dernier message")
    if facts.exchanges_7d:
        lines.append("- Derniers echanges (a ne pas recycler ni repeter) :")
        for entry in facts.exchanges_7d:
            lines.append(f'    {entry.when_label}  {entry.speaker}  : "{entry.text}"')
    if facts.patterns:
        lines.append("- Patterns connus :")
        for pattern in facts.patterns:
            lines.append(f"    - {pattern}")
    lines.append(f"- Contexte : {facts.day_context}")

    if digest.lens is not None:
        lines.append("")
        lines.append("Lecture du coach (suis ces trois lignes pour composer le message) :")
        lines.append(f"- Sens du jour : {digest.lens.sens_du_jour}")
        lines.append(f"- Angle : {digest.lens.angle}")
        lines.append(f"- Ne pas faire : {digest.lens.ne_pas_faire}")

    return "\n".join(lines)
