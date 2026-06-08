from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Sequence

from fitmas.legacy.domain.execution.claims import ActivityClaim
from fitmas.legacy.domain.execution.evidence import classify_execution_evidence
from fitmas.legacy.domain.athlete.fitness_snapshot import estimate_scheduled_session_tss

KEY_PRIORITIES = {"high", "key", "important"}
REST_SPORTS = {"rest", "off"}


@dataclass(frozen=True, slots=True)
class RecentRealityWindow:
    planned_sessions_7d: int
    confirmed_sessions_7d: int
    claimed_sessions_7d: int
    key_sessions_salvaged_7d: int
    planned_tss_7d: float
    observed_tss_7d: float
    planned_sessions_14d: int = 0
    confirmed_sessions_14d: int = 0
    claimed_sessions_14d: int = 0
    key_sessions_salvaged_14d: int = 0
    planned_tss_14d: float = 0.0
    observed_tss_14d: float = 0.0
    compliance_confirmed: float = 1.0
    load_ratio: float = 1.0
    compliance_confirmed_14d: float = 1.0
    load_ratio_14d: float = 1.0
    missed_streak_days: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "planned_sessions_7d": self.planned_sessions_7d,
            "confirmed_sessions_7d": self.confirmed_sessions_7d,
            "claimed_sessions_7d": self.claimed_sessions_7d,
            "key_sessions_salvaged_7d": self.key_sessions_salvaged_7d,
            "planned_tss_7d": self.planned_tss_7d,
            "observed_tss_7d": self.observed_tss_7d,
            "planned_sessions_14d": self.planned_sessions_14d,
            "confirmed_sessions_14d": self.confirmed_sessions_14d,
            "claimed_sessions_14d": self.claimed_sessions_14d,
            "key_sessions_salvaged_14d": self.key_sessions_salvaged_14d,
            "planned_tss_14d": self.planned_tss_14d,
            "observed_tss_14d": self.observed_tss_14d,
            "compliance_confirmed": self.compliance_confirmed,
            "load_ratio": self.load_ratio,
            "compliance_confirmed_14d": self.compliance_confirmed_14d,
            "load_ratio_14d": self.load_ratio_14d,
            "missed_streak_days": self.missed_streak_days,
            "periods": {
                "7d": self._period_dict(
                    planned_sessions=self.planned_sessions_7d,
                    confirmed_sessions=self.confirmed_sessions_7d,
                    claimed_sessions=self.claimed_sessions_7d,
                    key_sessions_salvaged=self.key_sessions_salvaged_7d,
                    planned_load=self.planned_tss_7d,
                    observed_load=self.observed_tss_7d,
                    confirmed_completion=self.compliance_confirmed,
                    load_ratio=self.load_ratio,
                ),
                "14d": self._period_dict(
                    planned_sessions=self.planned_sessions_14d,
                    confirmed_sessions=self.confirmed_sessions_14d,
                    claimed_sessions=self.claimed_sessions_14d,
                    key_sessions_salvaged=self.key_sessions_salvaged_14d,
                    planned_load=self.planned_tss_14d,
                    observed_load=self.observed_tss_14d,
                    confirmed_completion=self.compliance_confirmed_14d,
                    load_ratio=self.load_ratio_14d,
                ),
            },
        }

    @staticmethod
    def _period_dict(
        *,
        planned_sessions: int,
        confirmed_sessions: int,
        claimed_sessions: int,
        key_sessions_salvaged: int,
        planned_load: float,
        observed_load: float,
        confirmed_completion: float,
        load_ratio: float,
    ) -> dict[str, float | int]:
        return {
            "planned_sessions": planned_sessions,
            "confirmed_sessions": confirmed_sessions,
            "claimed_sessions": claimed_sessions,
            "key_sessions_salvaged": key_sessions_salvaged,
            "planned_load": planned_load,
            "observed_load": observed_load,
            "confirmed_completion": confirmed_completion,
            "load_ratio": load_ratio,
        }


def build_recent_reality_window(
    *,
    today: date,
    scheduled_sessions: Sequence[Any],
    activities: Sequence[Any],
    claims: Sequence[ActivityClaim] = (),
) -> RecentRealityWindow:
    metrics_7d = _build_window_metrics(
        today=today,
        scheduled_sessions=scheduled_sessions,
        activities=activities,
        claims=claims,
        window_days=7,
    )
    metrics_14d = _build_window_metrics(
        today=today,
        scheduled_sessions=scheduled_sessions,
        activities=activities,
        claims=claims,
        window_days=14,
    )

    return RecentRealityWindow(
        planned_sessions_7d=metrics_7d["planned_sessions"],
        confirmed_sessions_7d=metrics_7d["confirmed_sessions"],
        claimed_sessions_7d=metrics_7d["claimed_sessions"],
        key_sessions_salvaged_7d=metrics_7d["key_sessions_salvaged"],
        planned_tss_7d=metrics_7d["planned_tss"],
        observed_tss_7d=metrics_7d["observed_tss"],
        planned_sessions_14d=metrics_14d["planned_sessions"],
        confirmed_sessions_14d=metrics_14d["confirmed_sessions"],
        claimed_sessions_14d=metrics_14d["claimed_sessions"],
        key_sessions_salvaged_14d=metrics_14d["key_sessions_salvaged"],
        planned_tss_14d=metrics_14d["planned_tss"],
        observed_tss_14d=metrics_14d["observed_tss"],
        compliance_confirmed=_compliance_confirmed(
            planned_sessions=metrics_7d["planned_sessions"],
            confirmed_sessions=metrics_7d["confirmed_sessions"],
        ),
        load_ratio=_load_ratio(planned_tss=metrics_7d["planned_tss"], observed_tss=metrics_7d["observed_tss"]),
        compliance_confirmed_14d=_compliance_confirmed(
            planned_sessions=metrics_14d["planned_sessions"],
            confirmed_sessions=metrics_14d["confirmed_sessions"],
        ),
        load_ratio_14d=_load_ratio(planned_tss=metrics_14d["planned_tss"], observed_tss=metrics_14d["observed_tss"]),
        missed_streak_days=_missed_streak_days(
            today=today,
            sessions=metrics_7d["filtered_sessions"],
            activities=metrics_7d["relevant_activities"],
        ),
    )


def _build_window_metrics(
    *,
    today: date,
    scheduled_sessions: Sequence[Any],
    activities: Sequence[Any],
    claims: Sequence[ActivityClaim],
    window_days: int,
) -> dict[str, Any]:
    start = today - timedelta(days=max(window_days - 1, 0))
    relevant_sessions = [
        session
        for session in scheduled_sessions
        if (scheduled_date := _as_date(_value(session, "scheduled_date"))) is not None
        and start <= scheduled_date <= today
        and str(_value(session, "sport_type") or "").lower() not in REST_SPORTS
    ]
    relevant_activities = [
        activity
        for activity in activities
        if (activity_date := _as_date(_value(activity, "started_at") or _value(activity, "created_at"))) is not None
        and start <= activity_date <= today
    ]
    relevant_claims = [
        claim
        for claim in claims
        if claim.resolved_date_iso is not None
        and (claim_date := _as_date(claim.resolved_date_iso)) is not None
        and start <= claim_date <= today
    ]

    evaluated_sessions: list[tuple[Any, Any]] = []
    for session in relevant_sessions:
        session_date = _as_date(_value(session, "scheduled_date"))
        evidence = classify_execution_evidence(
            planned_session=session,
            activities=[activity for activity in relevant_activities if _activity_on_date(activity, target_date=session_date)],
            claims=[claim for claim in relevant_claims if _claim_on_date(claim, target_date=session_date)],
        )
        if session_date == today and evidence.display_status != "confirmed_done":
            continue
        evaluated_sessions.append((session, evidence))

    confirmed_sessions = 0
    claimed_sessions = 0
    key_sessions_salvaged = 0
    for session, evidence in evaluated_sessions:
        if evidence.display_status == "confirmed_done":
            confirmed_sessions += 1
            if _is_key_session(session):
                key_sessions_salvaged += 1
        elif evidence.display_status == "claimed_done":
            claimed_sessions += 1

    filtered_sessions = [session for session, _ in evaluated_sessions]
    return {
        "planned_sessions": len(filtered_sessions),
        "confirmed_sessions": confirmed_sessions,
        "claimed_sessions": claimed_sessions,
        "key_sessions_salvaged": key_sessions_salvaged,
        "planned_tss": round(sum(estimate_scheduled_session_tss(session) for session in filtered_sessions), 1),
        "observed_tss": round(sum(float(_value(activity, "tss") or 0.0) for activity in relevant_activities), 1),
        "filtered_sessions": filtered_sessions,
        "relevant_activities": relevant_activities,
    }


def _compliance_confirmed(*, planned_sessions: int, confirmed_sessions: int) -> float:
    if planned_sessions <= 0:
        return 1.0
    return round(confirmed_sessions / planned_sessions, 2)


def _load_ratio(*, planned_tss: float, observed_tss: float) -> float:
    if planned_tss <= 0:
        return 1.0
    return round(observed_tss / planned_tss, 2)


def _missed_streak_days(*, today: date, sessions: Sequence[Any], activities: Sequence[Any]) -> int:
    streak = 0
    cursor = today - timedelta(days=1)
    window_start = today - timedelta(days=6)

    while cursor >= window_start:
        day_sessions = [
            session
            for session in sessions
            if _as_date(_value(session, "scheduled_date")) == cursor
            and str(_value(session, "sport_type") or "").lower() not in REST_SPORTS
        ]
        if not day_sessions:
            cursor -= timedelta(days=1)
            continue
        if any(
            classify_execution_evidence(planned_session=session, activities=activities).display_status == "confirmed_done"
            for session in day_sessions
        ):
            break
        streak += 1
        cursor -= timedelta(days=1)

    return streak


def _activity_on_date(activity: Any, *, target_date: date | None) -> bool:
    if target_date is None:
        return False
    return _as_date(_value(activity, "started_at") or _value(activity, "created_at")) == target_date


def _claim_on_date(claim: ActivityClaim, *, target_date: date | None) -> bool:
    if target_date is None:
        return False
    return _as_date(claim.resolved_date_iso) == target_date


def _is_key_session(session: Any) -> bool:
    priority = str(_value(session, "priority") or "").strip().lower()
    if priority in KEY_PRIORITIES:
        return True
    load_score = _int(_value(session, "load_score")) or 0
    return load_score >= 3


def _value(obj: Any, key: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _int(value: Any) -> int | None:
    if value is None:
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
