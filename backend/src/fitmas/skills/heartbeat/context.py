"""Heartbeat context bundle — structured truth for proactive prompts.

Replaces the free-form `yesterday_context` string + raw `recent_reality`
counters in the briefing prompt. Splits the truth into three atomic blocks:

- YesterdayTruth — what was planned and what really happened in the last 24h
- TodayTruth     — what is planned today
- WeekDigest     — 7d aggregate, explicitly labelled so the LLM cannot project
                   weekly counts onto a specific day (incident 2026-04-29)

Also defines `HeartbeatCapabilityBudget`: the prefiguration of the upcoming
TurnScope primitive. Most heartbeat roles are read-only. Since 3B-B, the
signal-check path may emit a PlanPatch candidate for pending confirmation,
but it still never commits a planning mutation autonomously.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Literal, Sequence

from fitmas.activity_claims import ActivityClaim
from fitmas.recent_reality import RecentRealityWindow

REST_SPORTS = {"rest", "off"}

DAY_NAMES_FR = {
    0: "lundi", 1: "mardi", 2: "mercredi", 3: "jeudi",
    4: "vendredi", 5: "samedi", 6: "dimanche",
}
DAY_SHORT_FR = {0: "lun", 1: "mar", 2: "mer", 3: "jeu", 4: "ven", 5: "sam", 6: "dim"}


YesterdayStatus = Literal[
    "rest",
    "no_plan_no_activity",
    "planned_done",
    "planned_missed",
    "planned_partial",
    "offplan_done",
    "claimed_done",
    "mixed",
]

TodayStatus = Literal["rest", "no_plan", "planned"]


@dataclass(frozen=True, slots=True)
class HeartbeatCapabilityBudget:
    """Capability budget for a heartbeat role.

    Heartbeat is read-only by default. Action-capable proactive turns may
    carry a PlanPatch candidate into a pending confirmation, but the runtime
    cannot commit anything proactively.

    Prefigures the conversation TurnScope. Same primitive will gate the
    coach turn capabilities once the router lands.
    """
    read_only: bool = True
    can_emit_message: bool = True
    can_emit_plan_patch: bool = False
    can_emit_candidate: bool = False


@dataclass(frozen=True, slots=True)
class PlannedSessionFact:
    session_id: int | None
    sport: str
    title: str
    duration_min: int | None
    completion_status: str  # planned/done/skipped/adapted/rest


@dataclass(frozen=True, slots=True)
class ActivityFact:
    activity_id: int | None
    sport: str
    duration_min: int
    scheduled_session_id: int | None

    @property
    def linked_to_plan(self) -> bool:
        return self.scheduled_session_id is not None


@dataclass(frozen=True, slots=True)
class OffplanFact:
    occurred_on: date
    sport: str
    duration_min: int


@dataclass(frozen=True, slots=True)
class YesterdayTruth:
    occurred_on: date
    day_label: str
    planned_sessions: tuple[PlannedSessionFact, ...]
    activities: tuple[ActivityFact, ...]
    claim_count: int
    linked_activity_count: int
    offplan_activity_count: int
    status: YesterdayStatus

    @property
    def linked_to_plan(self) -> bool:
        return self.linked_activity_count > 0


@dataclass(frozen=True, slots=True)
class TodayTruth:
    occurred_on: date
    day_label: str
    planned_session: PlannedSessionFact | None
    status: TodayStatus


@dataclass(frozen=True, slots=True)
class WeekDigest:
    today: date
    window_days: int
    planned_count: int
    confirmed_count: int
    claimed_count: int
    offplan_count: int
    missed_streak_days: int
    offplan_sessions: tuple[OffplanFact, ...]


@dataclass(frozen=True, slots=True)
class HeartbeatContextBundle:
    yesterday: YesterdayTruth
    today: TodayTruth
    week: WeekDigest
    capability: HeartbeatCapabilityBudget


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def build_heartbeat_context_bundle(
    *,
    today: date,
    today_planned_session: Any | None,
    yesterday_planned_sessions: Sequence[Any],
    yesterday_activities: Sequence[Any],
    yesterday_claims: Sequence[ActivityClaim],
    week_recent_reality: RecentRealityWindow,
    week_activities: Sequence[Any],
    capability: HeartbeatCapabilityBudget = HeartbeatCapabilityBudget(),
) -> HeartbeatContextBundle:
    yesterday_date = today - timedelta(days=1)
    return HeartbeatContextBundle(
        yesterday=_build_yesterday_truth(
            yesterday_date=yesterday_date,
            planned_sessions=yesterday_planned_sessions,
            activities=yesterday_activities,
            claims=yesterday_claims,
        ),
        today=_build_today_truth(
            today=today,
            planned_session=today_planned_session,
        ),
        week=_build_week_digest(
            today=today,
            recent_reality=week_recent_reality,
            week_activities=week_activities,
        ),
        capability=capability,
    )


def _build_yesterday_truth(
    *,
    yesterday_date: date,
    planned_sessions: Sequence[Any],
    activities: Sequence[Any],
    claims: Sequence[ActivityClaim],
) -> YesterdayTruth:
    planned_facts = tuple(_planned_session_fact(session) for session in planned_sessions)
    activity_facts = tuple(_activity_fact(activity) for activity in activities)

    linked_count = sum(1 for activity in activity_facts if activity.linked_to_plan)
    offplan_count = sum(1 for activity in activity_facts if not activity.linked_to_plan)
    non_rest_planned = [s for s in planned_facts if s.sport.lower() not in REST_SPORTS]

    status = _resolve_yesterday_status(
        non_rest_planned=non_rest_planned,
        all_planned=planned_facts,
        linked_count=linked_count,
        offplan_count=offplan_count,
        claim_count=len(claims),
    )

    return YesterdayTruth(
        occurred_on=yesterday_date,
        day_label=DAY_NAMES_FR.get(yesterday_date.weekday(), yesterday_date.isoformat()),
        planned_sessions=planned_facts,
        activities=activity_facts,
        claim_count=len(claims),
        linked_activity_count=linked_count,
        offplan_activity_count=offplan_count,
        status=status,
    )


def _resolve_yesterday_status(
    *,
    non_rest_planned: Sequence[PlannedSessionFact],
    all_planned: Sequence[PlannedSessionFact],
    linked_count: int,
    offplan_count: int,
    claim_count: int,
) -> YesterdayStatus:
    has_activity = (linked_count + offplan_count) > 0
    only_rest_planned = bool(all_planned) and not non_rest_planned

    if not non_rest_planned and not has_activity and claim_count == 0:
        if only_rest_planned:
            return "rest"
        return "no_plan_no_activity"

    if not non_rest_planned and has_activity:
        return "offplan_done"
    if not non_rest_planned and claim_count > 0:
        return "claimed_done"

    # Has at least one non-rest planned session
    has_missed = linked_count < len(non_rest_planned)
    if linked_count > 0 and offplan_count > 0:
        return "mixed"
    if linked_count > 0 and not has_missed:
        return "planned_done"
    if linked_count > 0 and has_missed:
        return "planned_partial"
    if offplan_count > 0:
        return "mixed"
    if claim_count > 0:
        return "claimed_done"
    return "planned_missed"


def _build_today_truth(*, today: date, planned_session: Any | None) -> TodayTruth:
    if planned_session is None:
        return TodayTruth(
            occurred_on=today,
            day_label=DAY_NAMES_FR.get(today.weekday(), today.isoformat()),
            planned_session=None,
            status="no_plan",
        )
    fact = _planned_session_fact(planned_session)
    status: TodayStatus = "rest" if fact.sport.lower() in REST_SPORTS else "planned"
    return TodayTruth(
        occurred_on=today,
        day_label=DAY_NAMES_FR.get(today.weekday(), today.isoformat()),
        planned_session=fact,
        status=status,
    )


def _build_week_digest(
    *,
    today: date,
    recent_reality: RecentRealityWindow,
    week_activities: Sequence[Any],
) -> WeekDigest:
    window_start = today - timedelta(days=6)
    offplan_facts: list[OffplanFact] = []
    for activity in week_activities:
        activity_date = _as_date(_value(activity, "started_at") or _value(activity, "created_at"))
        if activity_date is None or not (window_start <= activity_date <= today):
            continue
        if _value(activity, "scheduled_session_id") is not None:
            continue
        sport = str(_value(activity, "sport_type") or "sport").strip().lower() or "sport"
        duration = int(_value(activity, "duration_min") or 0)
        offplan_facts.append(
            OffplanFact(occurred_on=activity_date, sport=sport, duration_min=duration)
        )
    offplan_facts.sort(key=lambda fact: (fact.occurred_on, fact.sport))

    return WeekDigest(
        today=today,
        window_days=7,
        planned_count=recent_reality.planned_sessions_7d,
        confirmed_count=recent_reality.confirmed_sessions_7d,
        claimed_count=recent_reality.claimed_sessions_7d,
        offplan_count=len(offplan_facts),
        missed_streak_days=recent_reality.missed_streak_days,
        offplan_sessions=tuple(offplan_facts),
    )


def _planned_session_fact(session: Any) -> PlannedSessionFact:
    return PlannedSessionFact(
        session_id=_int(_value(session, "id")),
        sport=str(_value(session, "sport_type") or "").strip().lower(),
        title=str(_value(session, "session_title") or "").strip(),
        duration_min=_int(_value(session, "duration_min")),
        completion_status=str(_value(session, "completion_status") or "planned").strip().lower(),
    )


def _activity_fact(activity: Any) -> ActivityFact:
    return ActivityFact(
        activity_id=_int(_value(activity, "id")),
        sport=str(_value(activity, "sport_type") or "").strip().lower(),
        duration_min=int(_value(activity, "duration_min") or 0),
        scheduled_session_id=_int(_value(activity, "scheduled_session_id")),
    )


# ---------------------------------------------------------------------------
# Prompt rendering
# ---------------------------------------------------------------------------

def render_heartbeat_context_bundle(bundle: HeartbeatContextBundle) -> str:
    """Render the bundle as a single prompt block with three Truth sections.

    The blocks are explicitly labelled so the LLM cannot mix yesterday-specific
    truth with the 7d aggregate — root cause of the 2026-04-29 incident where
    the briefing claimed "hier offplan" while yesterday's activity was linked.
    """
    parts: list[str] = []
    parts.append(_render_yesterday_truth(bundle.yesterday))
    parts.append(_render_today_truth(bundle.today))
    parts.append(_render_week_digest(bundle.week))
    return "\n\n".join(parts)


def _render_yesterday_truth(truth: YesterdayTruth) -> str:
    lines = [
        "[YesterdayTruth — verite des 24h ecoulees, source autoritaire]",
        f"date: {truth.occurred_on.isoformat()} ({truth.day_label})",
    ]
    if truth.planned_sessions:
        plan_chunks = [
            _format_planned_session_inline(session)
            for session in truth.planned_sessions
        ]
        lines.append(f"plan: {', '.join(plan_chunks)}")
    else:
        lines.append("plan: aucun")

    if truth.activities:
        activity_chunks = [
            _format_activity_inline(activity) for activity in truth.activities
        ]
        lines.append(f"activites reelles: {', '.join(activity_chunks)}")
    else:
        lines.append("activites reelles: aucune")

    if truth.claim_count:
        lines.append(f"activites declarees (sans trace): {truth.claim_count}")

    lines.append(
        f"linked_activity_count: {truth.linked_activity_count} | "
        f"offplan_activity_count: {truth.offplan_activity_count} | "
        f"linked_to_plan: {'oui' if truth.linked_to_plan else 'non'}"
    )
    lines.append(f"status: {truth.status}")
    return "\n".join(lines)


def _render_today_truth(truth: TodayTruth) -> str:
    lines = [
        "[TodayTruth — verite du jour]",
        f"date: {truth.occurred_on.isoformat()} ({truth.day_label})",
    ]
    if truth.planned_session is not None:
        lines.append(f"plan: {_format_planned_session_inline(truth.planned_session)}")
    else:
        lines.append("plan: aucun")
    lines.append(f"status: {truth.status}")
    return "\n".join(lines)


def _render_week_digest(digest: WeekDigest) -> str:
    lines = [
        f"[WeekDigest — {digest.window_days}j roulants, agregat hebdo, "
        "NE PAS appliquer a un jour specifique]",
        f"planned: {digest.planned_count} | confirmed: {digest.confirmed_count} | "
        f"claimed: {digest.claimed_count} | offplan: {digest.offplan_count}",
        f"missed_streak_days: {digest.missed_streak_days}",
    ]
    if digest.offplan_sessions:
        lines.append("offplan detail:")
        for fact in digest.offplan_sessions:
            day_short = DAY_SHORT_FR.get(fact.occurred_on.weekday(), "?")
            lines.append(
                f"  - {fact.occurred_on.isoformat()} ({day_short}): "
                f"{fact.sport} {fact.duration_min}min"
            )
    return "\n".join(lines)


def _format_planned_session_inline(session: PlannedSessionFact) -> str:
    pieces = [session.sport or "sport"]
    if session.title:
        pieces.append(f'"{session.title}"')
    if session.duration_min:
        pieces.append(f"{session.duration_min}min")
    pieces.append(f"[{session.completion_status}]")
    return " ".join(pieces)


def _format_activity_inline(activity: ActivityFact) -> str:
    link = "linked-to-plan" if activity.linked_to_plan else "offplan"
    return f"{activity.sport or 'sport'} {activity.duration_min}min ({link})"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            return None
    return None
