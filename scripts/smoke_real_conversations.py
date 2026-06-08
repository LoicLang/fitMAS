#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
if "FITMAS_DB_PATH" not in os.environ:
    os.environ["FITMAS_DB_PATH"] = str(ROOT / f".tmp-smoke-real-{os.getpid()}.db")
sys.path.insert(0, str(ROOT / "backend" / "src"))

from fastapi.testclient import TestClient

import fitmas.legacy.skills.heartbeat.heartbeat as heartbeat
from fitmas.legacy.core import orm as s
from fitmas.legacy.api import app
from fitmas.legacy.app.telegram.delivery import CoachDraft, persist_draft
from fitmas.legacy.core.db import Base, SessionLocal, engine, init_db
from fitmas.legacy.core.time_context import DAY_KEYS, day_label_fr, get_local_now
from fitmas.legacy.domain.coaching import repository as coaching_repo
from fitmas.legacy.domain.execution import repository as execution_repo
from fitmas.legacy.domain.memory import repository as memory_repo
from fitmas.legacy.domain.planning import repository as planning_repo
from fitmas.legacy.domain.planning import template_repository as template_repo


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
    template_repo.replace_plan(
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
    session = planning_repo.get_today_scheduled_session(db, user.id, timezone_name=user.timezone)
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
        execution_repo.add_activity(
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
    memory = memory_repo.get_active_memory_items(db, user_id, include_patterns=True, total_limit=48)
    sessions = planning_repo.get_scheduled_sessions(db, user_id, limit=12)
    latest_adaptation = coaching_repo.get_latest_adaptation_event(db, user_id)
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


def _post_message(client: TestClient, db: SessionLocal, user: s.User, text: str) -> dict:
    before = _snapshot(db, user.id)
    response = client.post("/api/v0/messages", json={"text": text})
    response.raise_for_status()
    payload = response.json()
    db.expire_all()
    after = _snapshot(db, user.id)
    _print_turn(text, payload, before, after)
    return payload


@contextmanager
def _override_now(iso_value: str | None):
    previous = os.environ.get("FITMAS_OVERRIDE_NOW_ISO")
    if iso_value is None:
        os.environ.pop("FITMAS_OVERRIDE_NOW_ISO", None)
    else:
        os.environ["FITMAS_OVERRIDE_NOW_ISO"] = iso_value
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("FITMAS_OVERRIDE_NOW_ISO", None)
        else:
            os.environ["FITMAS_OVERRIDE_NOW_ISO"] = previous


def _setup_base(db: SessionLocal, *, vague_week: bool = False, strong_next_day_hint: bool = False) -> s.User:
    now = datetime.fromisoformat("2026-04-19T20:00:00+02:00")
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


def scenario_close_turn_open_question(db: SessionLocal, client: TestClient, user: s.User) -> None:
    persist_draft(
        user.id,
        CoachDraft(text="Tu dis Okay chef - t'attends quoi de moi ? Un point sur la semaine ?"),
        db=db,
    )
    payload = _post_message(client, db, user, "Okay chef")
    turn = (
        db.query(s.ConversationTurnRecord)
        .filter(s.ConversationTurnRecord.user_id == user.id)
        .order_by(s.ConversationTurnRecord.id.desc())
        .first()
    )
    if turn is None:
        raise AssertionError("Expected a persisted close-turn conversation record")
    context = json.loads(turn.context_json or "{}")
    reply_text = str((payload.get("assistant_message") or {}).get("text") or "")
    normalized_reply = reply_text.lower()
    if turn.response_mode != "close_turn_composed":
        raise AssertionError(f"Expected close_turn_composed, got {turn.response_mode}")
    if "?" in reply_text or "attends quoi" in normalized_reply:
        raise AssertionError(f"Expected terminal close without relance, got: {reply_text}")
    if context.get("terminal_close") is not True:
        raise AssertionError(f"Expected terminal_close context, got: {context}")
    if context.get("tools_offered") != 0:
        raise AssertionError(f"Expected zero tools offered, got: {context}")
    if context.get("open_question_marker") != "suppressed":
        raise AssertionError(f"Expected suppressed open-question marker, got: {context}")


def scenario_greeting(db: SessionLocal, client: TestClient, user: s.User) -> None:
    _post_message(client, db, user, "salut")


def scenario_info_query(db: SessionLocal, client: TestClient, user: s.User) -> None:
    _post_message(client, db, user, "C'etait quoi ma plus longue sortie recente ?")


def scenario_general_weight_lens(db: SessionLocal, client: TestClient, user: s.User) -> None:
    before = _snapshot(db, user.id)
    payload = _post_message(client, db, user, "Putain enft je fais 100kg qu'est ce qu'on fait ?")
    db.expire_all()
    after = _snapshot(db, user.id)
    reply = str((payload.get("assistant_message") or {}).get("text") or "").lower()
    if after["sessions"] != before["sessions"]:
        raise AssertionError("Expected generic weight concern to leave the plan unchanged")
    if after["adaptation"] != before["adaptation"]:
        raise AssertionError("Expected generic weight concern to avoid planning adaptation")
    forbidden = (
        "tu confirmes",
        "quelle option",
        "je deplace",
        "je modifie",
        "j'ai deplace",
        "plan modifie",
        "dans 15 jours",
        "en 2 semaines",
        "en deux semaines",
        "ca va partir",
        "ça va partir",
    )
    if any(token in reply for token in forbidden):
        raise AssertionError(f"Expected natural general answer without planning menu/mutation claim, got: {reply}")

    before_followup = _snapshot(db, user.id)
    payload_followup = _post_message(client, db, user, "Rien de grave quoi")
    db.expire_all()
    after_followup = _snapshot(db, user.id)
    followup_reply = str((payload_followup.get("assistant_message") or {}).get("text") or "").lower()
    if after_followup["sessions"] != before_followup["sessions"]:
        raise AssertionError("Expected generic reassurance follow-up to leave the plan unchanged")
    if after_followup["adaptation"] != before_followup["adaptation"]:
        raise AssertionError("Expected generic reassurance follow-up to avoid planning adaptation")
    if any(token in followup_reply for token in forbidden):
        raise AssertionError(f"Expected natural follow-up without planning menu/mutation claim, got: {followup_reply}")


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
    for session in planning_repo.get_scheduled_sessions(db, user.id, limit=12):
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


def _setup_compound_swap(db: SessionLocal) -> s.User:
    """Seeds piscine today + flexible recovery Friday to exercise the
    original compound-intent bug: a message that combines a non-completion
    claim ('j'ai oublie la piscine') with a swap request ('swap avec
    vendredi') must reach the LLM decide() and be treated as a mutation,
    not as a mere non-completion report."""
    now = datetime.fromisoformat("2026-04-19T20:00:00+02:00")
    weekly_notes = "Semaine chargee, dimanche long protege. Vendredi recuperation flexible."
    user = _create_user(db, weekly_structure_notes=weekly_notes)
    today_key = DAY_KEYS[now.weekday()]
    friday_offset = (4 - now.weekday()) % 7 or 7  # ensure a future Friday
    friday = (now + timedelta(days=friday_offset)).replace(hour=7, minute=0, second=0, microsecond=0)
    friday_key = DAY_KEYS[friday.weekday()]
    template_repo.replace_plan(
        db,
        user.id,
        intention="reprise propre",
        summary="smoke",
        timezone_name=user.timezone,
        days=[
            {
                "day": today_key,
                "label": day_label_fr(today_key, capitalize=True),
                "sport_type": "swimming",
                "session_type": "css",
                "session_title": "Natation CSS",
                "session_goal": "Seuil technique",
                "session_note": "cle",
                "session_description": "6x100m allure CSS",
                "duration_min": 40,
                "intensity": "moderate",
                "load_score": 3,
                "priority": "Seance cle",
                "nutrition_focus": "",
                "flexibility": "stable",
                "completion_status": "planned",
            },
            {
                "day": friday_key,
                "label": day_label_fr(friday_key, capitalize=True),
                "sport_type": "rest",
                "session_type": "rest",
                "session_title": "Recuperation flexible",
                "session_goal": "Absorber",
                "session_note": "",
                "session_description": "Repos",
                "duration_min": 0,
                "intensity": "easy",
                "load_score": 0,
                "priority": "Recovery",
                "nutrition_focus": "",
                "flexibility": "flexible",
                "completion_status": "planned",
            },
        ],
    )
    _seed_recent_activities(db, user)
    return user


def scenario_compound_non_completion_swap(db: SessionLocal, client: TestClient, user: s.User) -> None:
    _post_message(
        client,
        db,
        user,
        "Mince j'ai completement oublie que j'avais piscine, on peut swap la piscine de aujourd'hui avec la seance de vendredi ?",
    )


def _setup_golden_case_autonomy(db: SessionLocal) -> s.User:
    """Reproduit l'etat ayant produit la conversation Telegram du 19-20 avril
    2026 (golden case du refactor COACH-AUTONOMY-REFACTOR.md) :

    - Loic, multisport (running > swimming > strength)
    - Semaine ecoulee (J-6 a J-0) : 2 nages planifiees skipped (J-6 et J-4) +
      1 strength done (J-3) + 1 nage offplan done vendredi-equivalent (J-2)
    - Semaine a venir (J+1 a J+7) : VIDE (aucune session)

    Cet etat declenche les 5 pathologies cibles :
      - briefing dimanche affirme "zero natation" alors qu'une nage offplan
        existe (pre-digestion agregee en weekly_review)
      - sur "piscine fermee 2 semaines" le coach hallucine "natation prevue
        lundi 20 et mercredi 22" alors que J+1 a J+7 sont vides
      - sur "imprevus" / reponses courtes ("Running", "Mercredi") :
        court-circuits deterministes qui empechent l'appel du LLM principal
      - sur "Mercredi" : phantom action (le coach affirme "je libere ce
        creneau" sans appliquer de mutation reelle)
    """
    now = datetime.fromisoformat("2026-04-19T20:00:00+02:00")
    weekly_notes = (
        "Semaine triple : running socle, natation 2x technique + endurance, "
        "renfo support. Dimanche soir bilan."
    )
    user = _create_user(
        db,
        weekly_structure_notes=weekly_notes,
        current_state_notes="reprise propre, charge moderee, focus natation technique",
    )

    # Plan semaine ecoulee : 2 nages planifiees + 1 renfo
    past_swim_mon = (now - timedelta(days=6)).replace(hour=7, minute=0, second=0, microsecond=0)
    past_swim_wed = (now - timedelta(days=4)).replace(hour=7, minute=0, second=0, microsecond=0)
    past_strength = (now - timedelta(days=3)).replace(hour=18, minute=0, second=0, microsecond=0)

    for scheduled_date, sport, title, duration, status in [
        (past_swim_mon, "swimming", "Natation technique", 36, "skipped"),
        (past_swim_wed, "swimming", "Natation CSS", 40, "skipped"),
        (past_strength, "strength", "Renfo support", 30, "done"),
    ]:
        day_key = DAY_KEYS[scheduled_date.weekday()]
        db.add(s.ScheduledSession(
            user_id=user.id,
            day=day_key,
            label=day_label_fr(day_key, capitalize=True),
            scheduled_date=scheduled_date,
            source_plan_created_at=now - timedelta(days=10),
            sport_type=sport,
            session_type="endurance" if sport == "swimming" else "strength",
            session_title=title,
            session_goal="Technique" if sport == "swimming" else "Support",
            session_note="cle" if sport == "swimming" else "support",
            session_description=f"{duration} min",
            duration_min=duration,
            intensity="moderate",
            load_score=3,
            priority="Seance cle" if sport == "swimming" else "Normal",
            nutrition_focus="",
            flexibility="stable",
            completion_status=status,
        ))
    db.commit()

    # Activite reelle : nage offplan vendredi-equivalent (J-2), 22 min
    offplan_swim_started = (now - timedelta(days=2)).replace(hour=14, minute=0, second=0, microsecond=0)
    execution_repo.add_activity(
        db,
        user_id=user.id,
        source="strava",
        scheduled_session_id=None,
        sport_type="swimming",
        title="Afternoon Swim",
        duration_min=22,
        distance_m=1100,
        elevation_m=0,
        perceived_load=2,
        note="offplan",
        started_at=offplan_swim_started,
        matched_day=None,
        match_reason="offplan",
        tss=15.0,
    )
    # Activite reelle : renfo done (J-3), 58 min
    strength_started = (now - timedelta(days=3)).replace(hour=18, minute=0, second=0, microsecond=0)
    execution_repo.add_activity(
        db,
        user_id=user.id,
        source="manual",
        scheduled_session_id=None,
        sport_type="strength",
        title="Renfo adapte",
        duration_min=58,
        distance_m=0,
        elevation_m=0,
        perceived_load=3,
        note="done",
        started_at=strength_started,
        matched_day=None,
        match_reason="manual",
        tss=30.0,
    )
    return user


def scenario_golden_case_autonomy(db: SessionLocal, client: TestClient, user: s.User) -> None:
    """Joue les 7 tours du golden case de COACH-AUTONOMY-REFACTOR.md.

    Bugs attendus avant le refactor (a verifier visuellement) :
      Tour 1 (heartbeat weekly_review) : "zero natation" leak
      Tour 3 ("J'ai eut des imprevu") : token interne `this_week` dans la sortie
      Tour 4 (piscine fermee 2 semaines) : hallucination natation J+1/J+3
      Tour 6 ("Running") : "Je peux ajuster, mais j'ai besoin d'un point de plus"
      Tour 7 ("Mercredi") : "OK. Je libere ce creneau" SANS mutation appliquee

    Le refactor (Chantiers 1 a 5) doit faire disparaitre chacun de ces bugs.
    """
    # Tour 1 : briefing Sunday evening (heartbeat weekly_review)
    import fitmas.legacy.skills.heartbeat.heartbeat as heartbeat
    from fitmas.legacy.app.telegram.delivery import persist_draft

    sunday_review = "2026-04-19T20:00:00+02:00"
    monday_followup = "2026-04-20T08:05:00+02:00"

    with _override_now(sunday_review):
        heartbeat._LAST_PROACTIVE_GUARD_AT.clear()
        before = _snapshot(db, user.id)
        draft = heartbeat.weekly_review()
        if draft is not None:
            persist_draft(user.id, draft, db=db)
            db.expire_all()
            after = _snapshot(db, user.id)
            print("TURN: heartbeat:weekly_review (Tour 1)")
            print(f"assistant: {draft.text}")
            new_memory = []
            for key, value in after["memory"].items():
                if before["memory"].get(key) != value:
                    new_memory.append(f"{key[0]}:{key[1]}")
            print(f"memory_changes: {', '.join(new_memory) if new_memory else '-'}")
            print("session_changes: -")
            print("adaptation: -")
            print("BUG_EXPECTED: regarde si le coach dit 'zero natation' alors qu'une nage offplan J-2 existe")
            print("")
        else:
            print("TURN: heartbeat:weekly_review (Tour 1)")
            print("assistant: NO_SEND")
            print("")

    # Tour 2 : correction utilisateur (nage offplan)
    with _override_now(sunday_review):
        _post_message(client, db, user, "J'ai nage vendredi regarde mes seances reel")
    print("BUG_EXPECTED: peut halluciner un session id different de la vraie nage offplan J-2")
    print("")

    # Tour 3 : aveu utilisateur
    with _override_now(sunday_review):
        _post_message(client, db, user, "J'ai eut des imprevu")
    print("BUG_EXPECTED: token interne 'this_week' recopie brut dans la sortie (court-circuit _week_scope_reply)")
    print("")

    # Tour 4 : contrainte forte
    with _override_now(sunday_review):
        _post_message(client, db, user, "je ne peux pas nager les deux prochaines semaine ma piscine est fermee")
    print("BUG_EXPECTED: hallucination 'natation prevue lundi/mercredi' alors que J+1 a J+7 sont vides")
    print("")

    # Tour 5 : acquiescement
    with _override_now(monday_followup):
        _post_message(client, db, user, "Oui")
    print("BUG_EXPECTED: posture passive (re-demande des options au lieu de decider)")
    print("")

    # Tour 6 : reponse courte
    with _override_now(monday_followup):
        _post_message(client, db, user, "Running")
    print("BUG_EXPECTED: fallback nlp.py:60 'Je peux ajuster, mais j'ai besoin d'un point de plus' (LLM jamais appele)")
    print("")

    # Tour 7 : phantom action
    with _override_now(monday_followup):
        _post_message(client, db, user, "Mercredi")
    print("BUG_EXPECTED: 'OK. Je libere ce creneau' sans mutation reelle - aucun session_changes attendu")
    print("")


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


def _setup_heartbeat_non_completion(db: SessionLocal) -> s.User:
    now = datetime.fromisoformat("2026-04-30T08:02:00+02:00")
    user = _create_user(
        db,
        weekly_structure_notes="Semaine simple : renfo support hier, footing facile ce matin.",
        current_state_notes="charge basse, semaine a tenir proprement",
    )

    yesterday = (now - timedelta(days=1)).replace(hour=7, minute=0, second=0, microsecond=0)
    today = now.replace(hour=8, minute=30, second=0, microsecond=0)
    for scheduled_date, sport_type, session_type, title, duration, intensity in [
        (yesterday, "strength", "strength", "Renfo support", 34, "moderate"),
        (today, "running", "easy", "Footing Z2", 28, "easy"),
    ]:
        day_key = DAY_KEYS[scheduled_date.weekday()]
        db.add(
            s.ScheduledSession(
                user_id=user.id,
                day=day_key,
                label=day_label_fr(day_key, capitalize=True),
                scheduled_date=scheduled_date,
                source_plan_created_at=now - timedelta(days=3),
                sport_type=sport_type,
                session_type=session_type,
                session_title=title,
                session_goal="Support" if sport_type == "strength" else "Aerobie",
                session_note="",
                session_description=f"{duration} min",
                duration_min=duration,
                intensity=intensity,
                load_score=3 if intensity != "easy" else 2,
                priority="Normal",
                nutrition_focus="",
                flexibility="stable",
                completion_status="planned",
            )
        )
    db.commit()
    db.refresh(user)
    return user


def scenario_heartbeat_non_completion(db: SessionLocal, client: TestClient, user: s.User) -> None:
    with _override_now("2026-04-30T08:03:00+02:00"):
        persist_draft(
            user.id,
            CoachDraft(
                text="Hier, renfo 34min : tu l'as faite ou pas ? Ce matin, c'est footing Z2 28min.",
                proactive=True,
            ),
            db=db,
        )
        _post_message(client, db, user, "J'ai pas eu le temps hier malheureusement, petit imprevu au travail")

    yesterday = datetime.fromisoformat("2026-04-29T07:00:00+02:00").date()
    sessions = planning_repo.get_scheduled_sessions_for_date(db, user.id, target_date=yesterday)
    strength = [session for session in sessions if session.sport_type == "strength"]
    if len(strength) != 1 or strength[0].completion_status != "skipped":
        status = strength[0].completion_status if strength else "missing"
        raise AssertionError(f"Expected yesterday strength to be skipped via execution_actions, got {status}")


SCENARIOS: list[Scenario] = [
    Scenario("empty_ack", "Petit ack sans info utile", scenario_empty_ack),
    Scenario(
        "close_turn_open_question",
        "Cloture sociale apres question ouverte: pas de relance, pas de tools",
        scenario_close_turn_open_question,
    ),
    Scenario("greeting", "Petit message social", scenario_greeting),
    Scenario("info_query", "Question factuelle sur l'historique", scenario_info_query),
    Scenario(
        "general_weight_lens",
        "Inquietude poids: contexte coach compact sans mutation ni menu planning",
        scenario_general_weight_lens,
    ),
    Scenario("execution_update", "Declaration d'activite puis correction temporelle", scenario_execution_update),
    Scenario("today_unavailability", "Imprevu ce soir", scenario_today_unavailability),
    Scenario("future_unavailability", "Indispo demain soir", scenario_future_unavailability),
    Scenario("fatigue_today", "Signal fatigue jour courant", scenario_fatigue_today),
    Scenario("health_signal", "Signal sante lie a la natation", scenario_health_signal),
    Scenario("preference_signal", "Preference potentiellement durable", scenario_preference_signal),
    Scenario("week_scope_constraint", "Contrainte large sur la semaine", scenario_week_scope_constraint),
    Scenario("motivation_signal", "Signal motivation vague", scenario_motivation_signal),
    Scenario("heartbeat_calibration", "Question naturelle de calibration puis reponse", scenario_heartbeat_calibration),
    Scenario(
        "heartbeat_non_completion",
        "Reponse naturelle a une question heartbeat: pas fait hier -> execution_actions -> skipped",
        scenario_heartbeat_non_completion,
    ),
    Scenario(
        "compound_non_completion_swap",
        "Bug originel: non-completion implicite + swap dans le meme message",
        scenario_compound_non_completion_swap,
    ),
    Scenario(
        "golden_case_autonomy",
        "Golden case du refactor coach autonomy (7 tours, conversation 19-20 avril)",
        scenario_golden_case_autonomy,
    ),
]


def _run_scenario(scenario: Scenario) -> None:
    _reset_db()
    db = SessionLocal()
    try:
        if scenario.name == "today_unavailability":
            user = _setup_base(db, strong_next_day_hint=True)
        elif scenario.name == "heartbeat_calibration":
            user = _setup_base(db, vague_week=True)
        elif scenario.name == "heartbeat_non_completion":
            user = _setup_heartbeat_non_completion(db)
        elif scenario.name == "compound_non_completion_swap":
            user = _setup_compound_swap(db)
        elif scenario.name == "golden_case_autonomy":
            user = _setup_golden_case_autonomy(db)
        else:
            user = _setup_base(db)

        print(f"=== {scenario.name} ===")
        print(scenario.description)
        with TestClient(app) as client:
            scenario.run(db, client, user)
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run real FitMAS conversation smokes against the configured LLM provider.")
    parser.add_argument("--scenario", action="append", dest="scenarios", help="Run only the named scenario. Repeatable.")
    parser.add_argument("--keep-db", action="store_true", help="Keep the temporary smoke DB file.")
    args = parser.parse_args()

    if not (os.getenv("DEEPSEEK_API_KEY") or os.getenv("ANTHROPIC_API_KEY")):
        print("DEEPSEEK_API_KEY or ANTHROPIC_API_KEY missing. Load .env or export a key first.", file=sys.stderr)
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
