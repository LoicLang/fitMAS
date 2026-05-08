from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

from fitmas.recent_reality import RecentRealityWindow
from fitmas.skills.heartbeat.context import build_heartbeat_context_bundle
from fitmas.skills.heartbeat.roles import build_briefing_prompt


SNAPSHOT_DIR = Path(__file__).parent / "snapshots" / "prompts"


def _user() -> SimpleNamespace:
    return SimpleNamespace(
        coach_name="FitMAS",
        coach_style="direct",
        coach_soul="calme",
    )


def _today_session() -> SimpleNamespace:
    return SimpleNamespace(
        id=42,
        label="Vendredi",
        session_title="Footing endurance",
        sport_type="running",
        session_goal="40 min Z2, relance aerobie sans fatigue residuelle",
        priority="Reprise cadree",
        session_note="Garde l'allure conversationnelle.",
        duration_min=40,
        completion_status="planned",
    )


def _future_session() -> SimpleNamespace:
    return SimpleNamespace(
        id=43,
        scheduled_date=date(2026, 5, 9),
        date=date(2026, 5, 9),
        sport_type="rest",
        session_title="Repos",
        session_goal="Absorber la semaine",
        duration_min=None,
        completion_status="planned",
    )


def _time_context() -> dict[str, str]:
    return {
        "timezone": "Europe/Paris",
        "day_key": "friday",
        "day_label": "Vendredi",
        "day_label_fr": "vendredi",
        "date_iso": "2026-05-08",
        "date_fr": "8 mai 2026",
        "time_label": "07:30",
        "time_fr": "07:30",
        "now_iso": "2026-05-08T07:30:00+02:00",
        "part_of_day": "matin",
    }


def _recent_reality() -> RecentRealityWindow:
    return RecentRealityWindow(
        planned_sessions_7d=2,
        confirmed_sessions_7d=1,
        claimed_sessions_7d=0,
        key_sessions_salvaged_7d=0,
        planned_tss_7d=0.0,
        observed_tss_7d=0.0,
        missed_streak_days=0,
    )


def _heartbeat_briefing_snapshot() -> str:
    today_session = _today_session()
    bundle = build_heartbeat_context_bundle(
        today=date(2026, 5, 8),
        today_planned_session=today_session,
        yesterday_planned_sessions=(),
        yesterday_activities=(),
        yesterday_claims=(),
        week_recent_reality=_recent_reality(),
        week_activities=(),
        future_scheduled_sessions=(today_session, _future_session()),
    )
    system, prompt = build_briefing_prompt(
        user=_user(),
        today_session=today_session,
        day=None,
        time_context=_time_context(),
        bundle=bundle,
        clarification=None,
        calibration_need=None,
        signals_block="",
        facts_block=(
            "\n\nFaits actifs a prendre en compte:\n"
            "- [health] Tres legere tension aux tibias, pas de douleur a la palpation.\n"
            "- [health] Etirements doux des mollets apres chaque seance."
        ),
        sport_knowledge="Running Z2: respiration stable, conversation possible.",
    )
    return "\n".join(
        (
            "route: heartbeat_briefing",
            "contract: legacy_heartbeat_role",
            "capability: read_only",
            "",
            "## SYSTEM",
            system,
            "",
            "## USER",
            prompt,
            "",
        )
    )


def test_heartbeat_briefing_prompt_snapshot() -> None:
    snapshot_path = SNAPSHOT_DIR / "heartbeat_briefing.txt"
    expected = snapshot_path.read_text()

    assert _heartbeat_briefing_snapshot() == expected
