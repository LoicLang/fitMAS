"""Adaptive plan system — deterministic triggers → targeted LLM analysis → mutations.

Architecture:
  1. Cheap Python detection (check_* functions) returns AdaptationTrigger or None
  2. Orchestrator assembles context and calls LLM with a specialized prompt
  3. LLM response is parsed into MutationDecision objects
  4. Decisions are applied by orchestrators through PlanMutationService
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy.orm import Session

from fitmas.legacy.core import orm as s
from fitmas.legacy.domain.execution import repository as execution_repo
from fitmas.legacy.domain.planning import repository as planning_repo
from fitmas.legacy.domain.planning.mutation_decision import MutationDecision
from fitmas.legacy.core.time_context import get_local_now
from fitmas.legacy.domain.athlete.training_load import compute_ctl_atl_tsb

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class AdaptationTrigger:
    trigger_type: str           # "health_fact" | "post_activity" | "tsb_alert" | "missed_cascade"
    urgency: str                # "immediate" | "next_session" | "end_of_week"
    affected_session_ids: list[int] = field(default_factory=list)
    context_data: dict = field(default_factory=dict)


@dataclass
class AdaptationResult:
    trigger_type: str
    decisions: list[MutationDecision] = field(default_factory=list)
    message: str = ""
    applied: bool = False


# ---------------------------------------------------------------------------
# Trigger detectors
# ---------------------------------------------------------------------------

_HIGH_URGENCY_KEYWORDS = (
    "douleur", "pain", "blessure", "blessé", "tendon", "tendinite",
    "entorse", "fracture", "déchirure", "rupture", "fatigue", "cramé",
    "crame", "malade", "maladie", "mal dormi", "sommeil", "gêne",
    "fragile", "chronique",
)

_BODY_ZONE_FR = {
    "shoulder": "epaule",
    "knee": "genou",
    "ankle": "cheville",
    "back": "dos",
}

_ACTIVITY_FR = {
    "swimming": "la natation",
    "running": "la course",
    "cycling": "le velo",
    "strength": "le renfo",
}


def check_health_fact_trigger(
    db: Session,
    user: s.User,
    new_facts: list[dict],
) -> AdaptationTrigger | None:
    """Fire when a health-related fact with high urgency is extracted."""
    health_facts = []
    for fact in new_facts:
        cat = fact.get("category", "")
        if cat not in ("health", "fatigue"):
            continue
        value = (fact.get("value", "") or "").lower()
        if any(kw in value for kw in _HIGH_URGENCY_KEYWORDS) or cat == "fatigue":
            health_facts.append(fact)

    if not health_facts:
        return None

    # Get upcoming sessions (next 7 days)
    local_now = get_local_now(user.timezone)
    upcoming = planning_repo.get_scheduled_sessions_between_dates(
        db, user.id,
        start_date=local_now.date(),
        end_date=local_now.date() + timedelta(days=7),
    )
    active_sessions = [
        s for s in upcoming
        if s.sport_type != "rest" and s.completion_status in {"planned", "adapted"}
    ]
    if not active_sessions:
        return None

    return AdaptationTrigger(
        trigger_type="health_fact",
        urgency="immediate",
        affected_session_ids=[s.id for s in active_sessions],
        context_data={
            "health_facts": health_facts,
            "sessions": [
                {
                    "id": s.id,
                    "day": s.day,
                    "date": s.scheduled_date.date().isoformat() if s.scheduled_date else None,
                    "sport_type": s.sport_type,
                    "session_type": s.session_type,
                    "title": s.session_title,
                    "intensity": s.intensity,
                    "duration_min": s.duration_min,
                }
                for s in active_sessions
            ],
        },
    )


def _build_conservative_health_fallback(trigger: AdaptationTrigger) -> tuple[list[MutationDecision], str]:
    facts = trigger.context_data.get("health_facts") or []
    sessions = trigger.context_data.get("sessions") or []

    body_zone, trigger_activity, has_fatigue_signal = _extract_health_signal_details(facts)

    if trigger_activity:
        matching_sessions = [session for session in sessions if session.get("sport_type") == trigger_activity]
        if matching_sessions:
            target = matching_sessions[0]
            duration = min(int(target.get("duration_min") or 25), 30)
            activity_label = _ACTIVITY_FR.get(trigger_activity, trigger_activity)
            title = f"Mobilite {body_zone} — remplace {activity_label}"
            message = (
                f"Je coupe {activity_label} telle quelle pour l'instant. "
                f"Je remplace la prochaine seance par {duration} min de mobilite douce {body_zone}. "
                "Si ca tire encore ou si la douleur monte, on stoppe net."
            )
            decision = MutationDecision(
                mutation_type="replace_session",
                target_session_id=int(target["id"]),
                new_title=title,
                new_goal=f"Preserver {body_zone} sans forcer",
                new_sport_type="strength",
                new_session_type="mobility",
                new_duration_min=duration,
                new_intensity="easy",
                new_description=f"Mobilite douce {body_zone}\\nActivation legere\\nZero intensite, zero douleur provoquee",
                rationale=f"Signal sante sur {body_zone} pendant {trigger_activity}: on coupe le geste pour l'instant.",
                fitmas_message=message,
            )
            return [decision], message

    if has_fatigue_signal and sessions:
        target = sessions[0]
        message = (
            "Je leve le pied tout de suite. "
            "La prochaine seance passe en version tres legere pour proteger la recup."
        )
        decision = MutationDecision(
            mutation_type="lighten_day",
            target_session_id=int(target["id"]),
            rationale="Signal de fatigue eleve: on protege la recuperation immediate.",
            fitmas_message=message,
        )
        return [decision], message

    return [], ""


def _extract_health_signal_details(facts: list[dict]) -> tuple[str, str | None, bool]:
    body_zone = "zone sensible"
    trigger_activity = None
    has_fatigue_signal = False

    for fact in facts:
        category = str(fact.get("category") or "").strip()
        key = str(fact.get("key") or "").strip()
        value = str(fact.get("value") or "").lower()
        if category == "fatigue" or "fatigue" in value or "rince" in value or "rinc" in value:
            has_fatigue_signal = True
        if key.startswith("reported_health_"):
            suffix = key.removeprefix("reported_health_")
            parts = suffix.split("_", 1)
            if parts:
                body_zone = _BODY_ZONE_FR.get(parts[0], parts[0])
            if len(parts) == 2 and parts[1]:
                trigger_activity = parts[1]
        if trigger_activity is None:
            if "swimming" in value or "nage" in value:
                trigger_activity = "swimming"
            elif "running" in value or "course" in value:
                trigger_activity = "running"

    return body_zone, trigger_activity, has_fatigue_signal


def _should_force_conservative_health_fallback(trigger: AdaptationTrigger) -> bool:
    facts = trigger.context_data.get("health_facts") or []
    body_zone, trigger_activity, _ = _extract_health_signal_details(facts)
    return body_zone == "epaule" and trigger_activity == "swimming"


def check_post_activity_trigger(
    db: Session,
    user: s.User,
    activity: s.Activity,
) -> AdaptationTrigger | None:
    """Fire after Strava import when activity diverges from plan."""
    # Need a matched session to compare against
    if activity.scheduled_session_id is None:
        return None

    session = planning_repo.get_scheduled_session(db, user.id, activity.scheduled_session_id)
    if session is None:
        return None

    triggers_fire = False
    reasons = []

    # Duration divergence
    if session.duration_min and activity.duration_min:
        ratio = activity.duration_min / session.duration_min
        if ratio > 1.3:
            triggers_fire = True
            reasons.append(f"duree reelle {activity.duration_min}min vs {session.duration_min}min prevus ({ratio:.0%})")
        elif ratio < 0.5:
            triggers_fire = True
            reasons.append(f"seance ecoutee: {activity.duration_min}min vs {session.duration_min}min prevus")

    # TSB check
    activities = execution_repo.get_activities(db, user.id, limit=90)
    tsb_data = compute_ctl_atl_tsb([a for a in activities])
    tsb = tsb_data.get("tsb", 0)
    if tsb < -20:
        triggers_fire = True
        reasons.append(f"TSB={tsb:.0f} (charge lourde)")

    if not triggers_fire:
        return None

    # Get next 48h sessions
    local_now = get_local_now(user.timezone)
    upcoming = planning_repo.get_scheduled_sessions_between_dates(
        db, user.id,
        start_date=local_now.date() + timedelta(days=1),
        end_date=local_now.date() + timedelta(days=3),
    )
    active_upcoming = [s for s in upcoming if s.sport_type != "rest" and s.completion_status == "planned"]
    if not active_upcoming:
        return None

    return AdaptationTrigger(
        trigger_type="post_activity",
        urgency="next_session",
        affected_session_ids=[s.id for s in active_upcoming],
        context_data={
            "activity": {
                "sport": activity.sport_type,
                "duration_min": activity.duration_min,
                "distance_m": activity.distance_m,
                "avg_hr": activity.avg_hr,
                "tss": activity.tss,
            },
            "matched_session": {
                "id": session.id,
                "sport_type": session.sport_type,
                "title": session.session_title,
                "duration_min": session.duration_min,
                "intensity": session.intensity,
            },
            "reasons": reasons,
            "tsb": tsb,
            "sessions_48h": [
                {
                    "id": s.id,
                    "day": s.day,
                    "date": s.scheduled_date.date().isoformat() if s.scheduled_date else None,
                    "sport_type": s.sport_type,
                    "session_type": s.session_type,
                    "title": s.session_title,
                    "intensity": s.intensity,
                    "duration_min": s.duration_min,
                }
                for s in active_upcoming
            ],
        },
    )


def check_tsb_trigger(
    db: Session,
    user: s.User,
) -> AdaptationTrigger | None:
    """Fire when TSB indicates overreaching or significant freshness."""
    activities = execution_repo.get_activities(db, user.id, limit=90)
    if len(activities) < 3:
        return None

    tsb_data = compute_ctl_atl_tsb([a for a in activities])
    tsb = tsb_data.get("tsb", 0)

    if -30 < tsb < 25:
        return None  # Normal range

    local_now = get_local_now(user.timezone)
    upcoming = planning_repo.get_scheduled_sessions_between_dates(
        db, user.id,
        start_date=local_now.date(),
        end_date=local_now.date() + timedelta(days=4),
    )
    active_upcoming = [s for s in upcoming if s.sport_type != "rest" and s.completion_status == "planned"]
    if not active_upcoming:
        return None

    alert_type = "overreached" if tsb <= -30 else "undertrained"

    return AdaptationTrigger(
        trigger_type="tsb_alert",
        urgency="next_session" if alert_type == "overreached" else "end_of_week",
        affected_session_ids=[s.id for s in active_upcoming],
        context_data={
            "alert_type": alert_type,
            "tsb": tsb,
            "ctl": tsb_data.get("ctl", 0),
            "atl": tsb_data.get("atl", 0),
            "sessions": [
                {
                    "id": s.id,
                    "day": s.day,
                    "date": s.scheduled_date.date().isoformat() if s.scheduled_date else None,
                    "sport_type": s.sport_type,
                    "session_type": s.session_type,
                    "title": s.session_title,
                    "intensity": s.intensity,
                    "duration_min": s.duration_min,
                }
                for s in active_upcoming
            ],
        },
    )


def check_missed_cascade_trigger(
    db: Session,
    user: s.User,
) -> AdaptationTrigger | None:
    """Fire when 2+ sessions missed in rolling 5 days."""
    local_now = get_local_now(user.timezone)
    recent = planning_repo.get_scheduled_sessions_between_dates(
        db, user.id,
        start_date=local_now.date() - timedelta(days=5),
        end_date=local_now.date(),
    )

    missed = [
        s for s in recent
        if s.sport_type != "rest"
        and s.completion_status in ("planned", "skipped")
        and s.scheduled_date and s.scheduled_date.date() < local_now.date()
    ]

    if len(missed) < 2:
        return None

    # Get remaining sessions this week
    upcoming = planning_repo.get_scheduled_sessions_between_dates(
        db, user.id,
        start_date=local_now.date(),
        end_date=local_now.date() + timedelta(days=4),
    )
    active_upcoming = [s for s in upcoming if s.sport_type != "rest" and s.completion_status == "planned"]
    if not active_upcoming:
        return None

    return AdaptationTrigger(
        trigger_type="missed_cascade",
        urgency="next_session",
        affected_session_ids=[s.id for s in active_upcoming],
        context_data={
            "missed_count": len(missed),
            "missed_sessions": [
                {"id": s.id, "day": s.day, "sport_type": s.sport_type, "title": s.session_title}
                for s in missed
            ],
            "remaining_sessions": [
                {
                    "id": s.id,
                    "day": s.day,
                    "date": s.scheduled_date.date().isoformat() if s.scheduled_date else None,
                    "sport_type": s.sport_type,
                    "session_type": s.session_type,
                    "title": s.session_title,
                    "intensity": s.intensity,
                    "duration_min": s.duration_min,
                }
                for s in active_upcoming
            ],
        },
    )


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

_ADAPTATION_SOUL = """\
Tu es le moteur d'adaptation de FitMAS, un coach IA multisport.
Tu analyses des signaux (sante, charge, activite) et decides comment adapter les seances a venir.
Tu reponds en JSON. Tes decisions doivent etre conservatrices : mieux vaut adapter que casser.\
"""


def _build_health_fact_prompt(trigger: AdaptationTrigger) -> str:
    facts = trigger.context_data["health_facts"]
    sessions = trigger.context_data["sessions"]
    facts_str = "\n".join(f"- {f.get('key', '')}: {f.get('value', '')}" for f in facts)
    sessions_str = json.dumps(sessions, ensure_ascii=False, indent=2)

    return f"""Signal sante detecte:
{facts_str}

Seances a venir (7 jours):
{sessions_str}

Pour chaque seance affectee par ce signal sante, decide:
- "keep": la seance n'est pas impactee
- "replace": transformer la seance (nouveau sport, type, duree, intensite, description)
- "lighten": convertir en repos

Regles:
- Si douleur articulaire/musculaire, remplace les seances qui sollicitent la zone touchee par mobilite/renfo adapte
- Si fatigue generale, allege les seances hard en easy ou remplace par recuperation active
- Ne touche pas les seances qui ne sont pas impactees
- Privilegia "replace" a "lighten" — adapter > supprimer

Reponds en JSON:
{{
  "adaptations": [
    {{
      "session_id": <int>,
      "action": "keep" | "replace" | "lighten",
      "new_sport_type": "<str ou null>",
      "new_session_type": "<str ou null>",
      "new_duration_min": <int ou null>,
      "new_intensity": "<easy|moderate|hard ou null>",
      "new_description": "<str ou null>",
      "new_title": "<str ou null>",
      "rationale": "<str>"
    }}
  ],
  "message": "<message coach empathique et concis pour l'utilisateur>"
}}"""


def _build_post_activity_prompt(trigger: AdaptationTrigger) -> str:
    ctx = trigger.context_data
    return f"""Activite realisee:
{json.dumps(ctx['activity'], ensure_ascii=False)}

Seance prevue:
{json.dumps(ctx['matched_session'], ensure_ascii=False)}

Raisons du trigger: {', '.join(ctx['reasons'])}
TSB actuel: {ctx['tsb']:.0f}

Seances des prochaines 48h:
{json.dumps(ctx['sessions_48h'], ensure_ascii=False, indent=2)}

Adapte les seances des 48h suivantes en consequence.
- Si grosse sortie (>130% duree) → allege ou remplace le lendemain
- Si TSB < -20 → allege les sessions hard
- Si seance avorte (<50% duree) → garde le plan sauf si signe de fatigue

Reponds en JSON (meme format que le trigger sante):
{{
  "adaptations": [...],
  "message": "<message coach>"
}}"""


def _build_tsb_prompt(trigger: AdaptationTrigger) -> str:
    ctx = trigger.context_data
    alert = ctx["alert_type"]
    sessions_str = json.dumps(ctx["sessions"], ensure_ascii=False, indent=2)

    if alert == "overreached":
        instruction = """L'athlete est en surcharge (TSB < -30). Allege les prochains jours:
- Remplace les sessions hard par du easy/mobilite
- Reduis les durees de 30-50%
- Garde au moins une session active par jour (pas tout en repos)"""
    else:
        instruction = """L'athlete est tres frais (TSB > +25). Signale-le mais ne force pas d'intensification.
- Garde le plan actuel
- Suggere dans le message que l'athlete peut pousser un peu plus s'il le sent"""

    return f"""Alerte charge: {alert}
TSB: {ctx['tsb']:.0f} | CTL: {ctx['ctl']:.0f} | ATL: {ctx['atl']:.0f}

Seances a venir:
{sessions_str}

{instruction}

Reponds en JSON:
{{
  "adaptations": [...],
  "message": "<message coach>"
}}"""


def _build_missed_cascade_prompt(trigger: AdaptationTrigger) -> str:
    ctx = trigger.context_data
    missed_str = json.dumps(ctx["missed_sessions"], ensure_ascii=False)
    remaining_str = json.dumps(ctx["remaining_sessions"], ensure_ascii=False, indent=2)

    return f"""{ctx['missed_count']} seances ratees sur les 5 derniers jours:
{missed_str}

Seances restantes cette semaine:
{remaining_str}

Regles:
- Pas de rattrapage (jamais empiler les seances ratees)
- Allege la charge restante pour eviter le surentrainement de compensation
- Garde les seances prioritaires, allege ou remplace les secondaires
- Ton empathique — pas de culpabilisation

Reponds en JSON:
{{
  "adaptations": [...],
  "message": "<message coach empathique>"
}}"""


def _build_prompt(trigger: AdaptationTrigger) -> str:
    builders = {
        "health_fact": _build_health_fact_prompt,
        "post_activity": _build_post_activity_prompt,
        "tsb_alert": _build_tsb_prompt,
        "missed_cascade": _build_missed_cascade_prompt,
    }
    builder = builders.get(trigger.trigger_type)
    if builder is None:
        raise ValueError(f"Unknown trigger type: {trigger.trigger_type}")
    return builder(trigger)


def _model_for_trigger(trigger_type: str) -> str:
    """Sonnet for complex multi-session analysis, Haiku for simpler triggers."""
    if trigger_type == "health_fact":
        return "claude-sonnet-4-6"
    return "claude-haiku-4-5-20251001"


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

def _parse_adaptation_response(data: dict | None) -> tuple[list[MutationDecision], str]:
    """Parse LLM JSON response into MutationDecision list + coach message."""
    if not data:
        return [], ""

    message = data.get("message", "")
    decisions: list[MutationDecision] = []

    for adaptation in data.get("adaptations", []):
        action = adaptation.get("action", "keep")
        if action == "keep":
            continue

        if action == "replace":
            mutation_type = "replace_session"
        elif action == "lighten":
            mutation_type = "lighten_day"
        else:
            continue

        decisions.append(MutationDecision(
            mutation_type=mutation_type,
            target_session_id=adaptation.get("session_id"),
            new_sport_type=adaptation.get("new_sport_type"),
            new_session_type=adaptation.get("new_session_type"),
            new_duration_min=adaptation.get("new_duration_min"),
            new_intensity=adaptation.get("new_intensity"),
            new_description=adaptation.get("new_description"),
            new_title=adaptation.get("new_title"),
            rationale=adaptation.get("rationale", "Adaptation automatique"),
            fitmas_message="",
        ))

    return decisions, message


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run_adaptation(
    db: Session,
    *,
    user: s.User,
    trigger: AdaptationTrigger,
) -> AdaptationResult | None:
    """Run the full adaptation pipeline: prompt -> LLM -> parse -> proposal."""
    import fitmas.legacy.llm.gateway as gw

    prompt = _build_prompt(trigger)
    model = _model_for_trigger(trigger.trigger_type)

    logger.info(
        "Running adaptation trigger=%s urgency=%s sessions=%s model=%s",
        trigger.trigger_type, trigger.urgency,
        trigger.affected_session_ids, model,
    )

    data = gw.request_json(system=_ADAPTATION_SOUL, prompt=prompt, model=model, max_tokens=1024)
    decisions, message = _parse_adaptation_response(data)
    if decisions and _should_force_conservative_health_fallback(trigger):
        decisions, message = _build_conservative_health_fallback(trigger)
    if not decisions and trigger.trigger_type == "health_fact":
        decisions, message = _build_conservative_health_fallback(trigger)

    if not decisions:
        logger.info("Adaptation %s: no changes needed", trigger.trigger_type)
        return AdaptationResult(trigger_type=trigger.trigger_type, message=message)

    logger.info(
        "Adaptation %s produced %d suggestion(s); apply is owned by orchestrators",
        trigger.trigger_type,
        len(decisions),
    )
    return AdaptationResult(
        trigger_type=trigger.trigger_type,
        decisions=decisions,
        message=message,
        applied=False,
    )


# ---------------------------------------------------------------------------
# Convenience wrappers (called from hooks)
# ---------------------------------------------------------------------------

def check_and_adapt_health_facts(
    db: Session,
    user: s.User,
    new_facts: list[dict],
) -> AdaptationResult | None:
    """Check health facts and run adaptation if triggered."""
    trigger = check_health_fact_trigger(db, user, new_facts)
    if trigger is None:
        return None
    return run_adaptation(db, user=user, trigger=trigger)


def check_and_adapt_post_activity(
    db: Session,
    user: s.User,
    activity: s.Activity,
) -> AdaptationResult | None:
    """Check post-activity signals and run adaptation if triggered."""
    trigger = check_post_activity_trigger(db, user, activity)
    if trigger is None:
        return None
    return run_adaptation(db, user=user, trigger=trigger)


def check_and_adapt_tsb(
    db: Session,
    user: s.User,
) -> AdaptationResult | None:
    """Check TSB and run adaptation if triggered."""
    trigger = check_tsb_trigger(db, user)
    if trigger is None:
        return None
    return run_adaptation(db, user=user, trigger=trigger)


def check_and_adapt_missed(
    db: Session,
    user: s.User,
) -> AdaptationResult | None:
    """Check missed cascade and run adaptation if triggered."""
    trigger = check_missed_cascade_trigger(db, user)
    if trigger is None:
        return None
    return run_adaptation(db, user=user, trigger=trigger)
