#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
if "FITMAS_DB_PATH" not in os.environ:
    os.environ["FITMAS_DB_PATH"] = str(ROOT / f".tmp-smoke-real-{os.getpid()}.db")
sys.path.insert(0, str(ROOT / "backend" / "src"))

from fastapi.testclient import TestClient

import fitmas.heartbeat as heartbeat
from fitmas import repository as repo, schema as s
from fitmas.api import app
from fitmas.coach_messages import persist_draft
from fitmas.db import Base, SessionLocal, engine, init_db
from fitmas.time_context import DAY_KEYS, day_label_fr, get_local_now


ScenarioFn = Callable[[SessionLocal, TestClient, s.User], None]


@dataclass(slots=True)
class Scenario:
    name: str
    description: str
    run: ScenarioFn


def _reset_db() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    init_db()


def _create_user(
    db: SessionLocal,
    *,
    weekly_structure_notes: str,
    current_state_notes: str = "forme correcte, charge recente moderee",
) -> s.User:
    user = s.User(
        name="Loic",
        timezone="Europe/Paris",
        age=31,
        primary_objective="reprendre proprement et reconstruire l endurance",
        objective="reprendre proprement et reconstruire l endurance",
        weekly_structure_notes=weekly_structure_notes,
        coach_name="Aster",
        coach_style="direct",
        coach_relationship="lucide et stable",
        coach_do="proteger ce qui compte vraiment",
        coach_dont="parler pour rien",
        coach_soul="sobre, humain, precis",
        onboarding_status="completed",
    )
    db.add(user)
    db.flush()

    for rank, sport in enumerate(("running", "swimming", "strength")):
        db.add(s.UserSport(user_id=user.id, sport_type=sport, priority_rank=rank, active=True))

    db.add(s.UserPreference(user_id=user.id, text="matin > soir"))
    db.add(s.UserConstraint(user_id=user.id, text="semaine chargee en journee"))

    db.add(
        s.UserFact(
            user_id=user.id,
            category="training_state",
            key="current_state",
            value=current_state_notes,
            source="smoke",
            confidence=0.9,
            confirmed=True,
            active=True,
            urgency="medium",
            ttl="medium",
            affects_json='["planning","conversation","heartbeat"]',
        )
    )
    db.commit()
    db.refresh(user)
    return user


def _seed_today_plan(db: SessionLocal, user: s.User, *, title: str = "Footing facile", intensity: str = "easy") -> s.ScheduledSession:
    now = get_local_now(user.timezone)
    today_key = DAY_KEYS[now.weekday()]
    repo.replace_plan(
        db,
        user.id,
        intention="reprendre propre",
        summary="smoke",
        timezone_name=user.timezone,
        days=[
            {
                "day": today_key,
                "label": day_label_fr(today_key, capitalize=True),
                "sport_type": "running",
                "session_type": "easy",
                "session_title": title,
                "session_goal": "Socle",
                "session_note": "souple",
                "session_description": "40 min",
                "duration_min": 40,
                "intensity": intensity,
                "load_score": 3 if intensity != "easy" else 2,
                "priority": "Seance cle" if intensity != "easy" else "Normal",
                "nutrition_focus": "",
                "flexibility": "stable",
                "completion_status": "planned",
            }
        ],
    )
    session = repo.get_today_scheduled_session(db, user.id, timezone_name=user.timezone)
    assert session is not None
    return session


def _add_future_session(
    db: SessionLocal,
    user: s.User,
    *,
    day_offset: int,
    hour: int,
    sport_type: str,
    session_type: str,
    title: str,
    goal: str,
    duration_min: int,
    intensity: str,
    priority: str,
    flexibility: str = "stable",
) -> s.ScheduledSession:
    now = get_local_now(user.timezone)
    target = (now + timedelta(days=day_offset)).replace(hour=hour, minute=0, second=0, microsecond=0)
    day_key = DAY_KEYS[target.weekday()]
    session = s.ScheduledSession(
        user_id=user.id,
        day=day_key,
        label=day_label_fr(day_key, capitalize=True),
        scheduled_date=target,
        source_plan_created_at=now,
        sport_type=sport_type,
        session_type=session_type,
        session_title=title,
        session_goal=goal,
        session_note="",
        session_description=f"{duration_min} min",
        duration_min=duration_min,
        intensity=intensity,
        load_score=4 if intensity in {"moderate", "hard"} else 2,
        priority=priority,
        nutrition_focus="",
        flexibility=flexibility,
        completion_status="planned",
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def _seed_recent_activities(db: SessionLocal, user: s.User) -> None:
    now = get_local_now(user.timezone)
    samples = [
        ("running", "Sortie longue trail", 95, 7, 16800),
        ("cycling", "Endurance velo", 78, 4, 0),
        ("swimming", "Natation technique", 42, 2, 0),
    ]
    for sport_type, title, duration_min, days_ago, distance_m in samples:
        started_at = now - timedelta(days=days_ago)
        repo.add_activity(
            db,
            user_id=user.id,
            source="manual",
            scheduled_session_id=None,
            sport_type=sport_type,
            title=title,
            duration_min=duration_min,
            distance_m=distance_m,
            elevation_m=0,
            perceived_load=2,
            note="smoke",
            started_at=started_at,
            matched_day=None,
            match_reason="smoke",
            tss=float(max(15, duration_min // 2)),
        )


def _snapshot(db: SessionLocal, user_id: int) -> dict:
    memory = repo.get_active_memory_items(db, user_id, include_patterns=True, total_limit=48)
    sessions = repo.get_scheduled_sessions(db, user_id, limit=12)
    latest_adaptation = repo.get_latest_adaptation_event(db, user_id)
    return {
        "memory": {
            (getattr(item, "category", ""), getattr(item, "key", "")): str(getattr(item, "value", ""))
            for item in memory
        },
        "sessions": {
            int(session.id): (
                session.scheduled_date.isoformat() if session.scheduled_date else "",
                session.session_title,
                session.sport_type,
                session.session_type,
                session.completion_status,
            )
            for session in sessions
        },
        "adaptation": latest_adaptation.as_dict() if latest_adaptation else None,
    }


def _print_turn(label: str, response: dict, before: dict, after: dict) -> None:
    print(f"TURN: {label}")
    print(f"assistant: {response['assistant_message']['text']}")
    extraction = response.get("extraction") or {}
    if extraction:
        print(f"extraction_confidence: {extraction.get('confidence')}")

    new_memory = []
    for key, value in after["memory"].items():
        if before["memory"].get(key) != value:
            new_memory.append(f"{key[0]}:{key[1]}")
    print(f"memory_changes: {', '.join(new_memory) if new_memory else '-'}")

    changed_sessions = []
    for session_id, payload in after["sessions"].items():
        if before["sessions"].get(session_id) != payload:
            changed_sessions.append(f"{session_id}:{payload[1]} [{payload[4]}] {payload[0][:10]}")
    print(f"session_changes: {', '.join(changed_sessions) if changed_sessions else '-'}")

    adaptation = after["adaptation"]
    if adaptation and adaptation != before["adaptation"]:
        print(f"adaptation: {adaptation['reason_label']} | {adaptation['what_changed']} | {adaptation['impact_label']}")
    else:
        print("adaptation: -")
    print("")


def _post_message(client: TestClient, db: SessionLocal, user: s.User, text: str) -> None:
    before = _snapshot(db, user.id)
    response = client.post("/api/v0/messages", json={"text": text})
    payload = response.json()
    db.expire_all()
    after = _snapshot(db, user.id)
    _print_turn(text, payload, before, after)


def _setup_base(db: SessionLocal, *, vague_week: bool = False, strong_next_day_hint: bool = False) -> s.User:
    now = get_local_now("Europe/Paris")
    next_day_key = DAY_KEYS[(now.weekday() + 1) % 7]
    next_label = day_label_fr(next_day_key, capitalize=True)
    weekly_notes = "Semaine chargee, dimanche long protege."
    if vague_week:
        weekly_notes += " Rien de vraiment verrouille sur les prochains jours."
    elif strong_next_day_hint:
        weekly_notes += f" {next_label} matin dispo si besoin."
    else:
        weekly_notes += f" {next_label} plutot soir que matin."

    user = _create_user(db, weekly_structure_notes=weekly_notes)
    _seed_today_plan(db, user)
    _add_future_session(
        db, user, day_offset=1, hour=18,
        sport_type="running", session_type="tempo", title="Tempo demain",
        goal="Stimulus seuil", duration_min=50, intensity="moderate", priority="Seance cle",
    )
    _add_future_session(
        db, user, day_offset=2, hour=7,
        sport_type="swimming", session_type="endurance", title="Natation endurance",
        goal="Technique et aisance", duration_min=45, intensity="easy", priority="Normal", flexibility="movable",
    )
    _add_future_session(
        db, user, day_offset=3, hour=7,
        sport_type="strength", session_type="strength", title="Renfo support",
        goal="Support", duration_min=30, intensity="moderate", priority="Normal", flexibility="movable",
    )
    _seed_recent_activities(db, user)
    return user


def scenario_empty_ack(db: SessionLocal, client: TestClient, user: s.User) -> None:
    _post_message(client, db, user, "ok merci")


def scenario_greeting(db: SessionLocal, client: TestClient, user: s.User) -> None:
    _post_message(client, db, user, "salut")


def scenario_info_query(db: SessionLocal, client: TestClient, user: s.User) -> None:
    _post_message(client, db, user, "C'etait quoi ma plus longue sortie recente ?")


def scenario_execution_update(db: SessionLocal, client: TestClient, user: s.User) -> None:
    _post_message(client, db, user, "J'ai couru aujourd'hui 30 min")
    _post_message(client, db, user, "Non c'etait hier")


def scenario_today_unavailability(db: SessionLocal, client: TestClient, user: s.User) -> None:
    _post_message(client, db, user, "Merde imprevu je peux pas ce soir")


def scenario_future_unavailability(db: SessionLocal, client: TestClient, user: s.User) -> None:
    _post_message(client, db, user, "Je ne suis pas dispo demain soir")


def scenario_fatigue_today(db: SessionLocal, client: TestClient, user: s.User) -> None:
    _post_message(client, db, user, "Je suis rince aujourd'hui, jambes lourdes")


def scenario_health_signal(db: SessionLocal, client: TestClient, user: s.User) -> None:
    tomorrow = get_local_now(user.timezone) + timedelta(days=1)
    tomorrow_key = DAY_KEYS[tomorrow.weekday()]
    for session in repo.get_scheduled_sessions(db, user.id, limit=12):
        if session.day == tomorrow_key and session.sport_type == "running":
            session.active = False
    db.commit()
    _add_future_session(
        db, user, day_offset=1, hour=7,
        sport_type="swimming", session_type="endurance", title="Natation demain",
        goal="Technique", duration_min=45, intensity="easy", priority="Normal",
    )
    _post_message(client, db, user, "J'ai mal a l'epaule quand je nage, ca tire")


def scenario_preference_signal(db: SessionLocal, client: TestClient, user: s.User) -> None:
    _post_message(client, db, user, "Le mardi soir c'est souvent mort")


def scenario_week_scope_constraint(db: SessionLocal, client: TestClient, user: s.User) -> None:
    _post_message(client, db, user, "Cette semaine je voyage de mercredi a vendredi")


def scenario_motivation_signal(db: SessionLocal, client: TestClient, user: s.User) -> None:
    _post_message(client, db, user, "Je suis motive cette semaine")


def scenario_heartbeat_calibration(db: SessionLocal, client: TestClient, user: s.User) -> None:
    heartbeat._LAST_PROACTIVE_GUARD_AT.clear()
    before = _snapshot(db, user.id)
    draft = heartbeat.morning_briefing()
    if draft is None:
        print("TURN: heartbeat")
        print("assistant: NO_SEND")
        print("memory_changes: -")
        print("session_changes: -")
        print("adaptation: -")
        print("")
        return

    persist_draft(user.id, draft, db=db)
    db.expire_all()
    after = _snapshot(db, user.id)
    print("TURN: heartbeat")
    print(f"assistant: {draft.text}")
    new_memory = []
    for key, value in after["memory"].items():
        if before["memory"].get(key) != value:
            new_memory.append(f"{key[0]}:{key[1]}")
    print(f"memory_changes: {', '.join(new_memory) if new_memory else '-'}")
    print("session_changes: -")
    print("adaptation: -")
    print("")
    _post_message(client, db, user, "Plutot le soir")


SCENARIOS: list[Scenario] = [
    Scenario("empty_ack", "Petit ack sans info utile", scenario_empty_ack),
    Scenario("greeting", "Petit message social", scenario_greeting),
    Scenario("info_query", "Question factuelle sur l'historique", scenario_info_query),
    Scenario("execution_update", "Declaration d'activite puis correction temporelle", scenario_execution_update),
    Scenario("today_unavailability", "Imprevu ce soir", scenario_today_unavailability),
    Scenario("future_unavailability", "Indispo demain soir", scenario_future_unavailability),
    Scenario("fatigue_today", "Signal fatigue jour courant", scenario_fatigue_today),
    Scenario("health_signal", "Signal sante lie a la natation", scenario_health_signal),
    Scenario("preference_signal", "Preference potentiellement durable", scenario_preference_signal),
    Scenario("week_scope_constraint", "Contrainte large sur la semaine", scenario_week_scope_constraint),
    Scenario("motivation_signal", "Signal motivation vague", scenario_motivation_signal),
    Scenario("heartbeat_calibration", "Question naturelle de calibration puis reponse", scenario_heartbeat_calibration),
]


def _run_scenario(scenario: Scenario) -> None:
    _reset_db()
    db = SessionLocal()
    try:
        if scenario.name == "today_unavailability":
            user = _setup_base(db, strong_next_day_hint=True)
        elif scenario.name == "heartbeat_calibration":
            user = _setup_base(db, vague_week=True)
        else:
            user = _setup_base(db)

        print(f"=== {scenario.name} ===")
        print(scenario.description)
        with TestClient(app) as client:
            scenario.run(db, client, user)
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run real FitMAS conversation smokes against the Anthropic API.")
    parser.add_argument("--scenario", action="append", dest="scenarios", help="Run only the named scenario. Repeatable.")
    parser.add_argument("--keep-db", action="store_true", help="Keep the temporary smoke DB file.")
    args = parser.parse_args()

    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY missing. Load .env or export the key first.", file=sys.stderr)
        return 2

    selected = {name.strip() for name in (args.scenarios or []) if name.strip()}
    scenarios = [scenario for scenario in SCENARIOS if not selected or scenario.name in selected]
    if not scenarios:
        print("No matching scenarios.", file=sys.stderr)
        return 2

    print(f"FitMAS real smoke DB: {os.environ['FITMAS_DB_PATH']}")
    print(f"Run at: {datetime.now().isoformat(timespec='seconds')}")
    print("")

    for scenario in scenarios:
        _run_scenario(scenario)

    if not args.keep_db:
        db_path = Path(os.environ["FITMAS_DB_PATH"])
        if db_path.exists():
            db_path.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
