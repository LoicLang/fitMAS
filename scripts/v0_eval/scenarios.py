from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from fitmas.runtime_v0.db import connect, reset_db
from fitmas.runtime_v0.event import InputEvent


PARIS = ZoneInfo("Europe/Paris")


@dataclass(frozen=True)
class CommandSpec:
    command_type: str
    target_type: str
    target_id: str | None = None
    expected_status: Literal["applied", "blocked"] = "applied"


@dataclass(frozen=True)
class ScenarioOracle:
    name: str
    description: str
    initial_db_state: dict
    input_event: InputEvent
    expected_proposal_type: str
    expected_policy_action: str
    expected_commands: tuple[CommandSpec, ...]
    expected_reply_must_include: tuple[str, ...]
    expected_reply_must_not_contain: tuple[str, ...]
    expected_session_dates: tuple[tuple[str, str], ...] = ()
    followup: "ScenarioOracle | None" = None
    max_acceptable_latency_ms: int = 8000
    max_acceptable_tokens: int = 4000


def scenario_by_name(name: str) -> ScenarioOracle:
    scenarios = _scenarios()
    try:
        return scenarios[name]
    except KeyError as exc:
        raise LookupError(f"unknown_scenario:{name}") from exc


def seed_db(db_path: Path, state: dict) -> None:
    reset_db(db_path)
    with connect(db_path) as connection:
        for session in state.get("sessions", ()):
            connection.execute(
                """
                insert into v0_scheduled_sessions (
                    id, user_id, date, sport, title, duration_min,
                    intensity_label, priority, status
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session["id"],
                    1,
                    session["date"],
                    session["sport"],
                    session["title"],
                    session.get("duration_min", 45),
                    session.get("intensity_label", "easy"),
                    session.get("priority", "secondary"),
                    session.get("status", "planned"),
                ),
            )
        for event in state.get("command_events", ()):
            turn_id = event.get("turn_id", f"seed-turn-{event['id']}")
            connection.execute("insert or ignore into v0_turns (id) values (?)", (turn_id,))
            connection.execute(
                """
                insert into v0_command_events (
                    id, turn_id, command_type, target_type, target_id,
                    status, before_json, after_json, reason, created_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event["id"],
                    turn_id,
                    event["command_type"],
                    event.get("target_type", "session"),
                    event["target_id"],
                    event.get("status", "applied"),
                    "{}",
                    "{}",
                    event.get("reason", "seed"),
                    event.get("created_at", "2026-05-22T09:30:00+02:00"),
                ),
            )
        connection.commit()


def _event(event_id: str, text: str, hour: int, minute: int = 0) -> InputEvent:
    return InputEvent(
        id=event_id,
        user_id=1,
        source="test",
        type="user_message",
        text=text,
        payload={},
        occurred_at=datetime(2026, 5, 22, hour, minute, tzinfo=PARIS),
    )


def _base_sessions() -> list[dict]:
    return [
        {"id": 10, "date": "2026-05-07", "sport": "run", "title": "Ancien run"},
        {"id": 11, "date": "2026-05-14", "sport": "bike", "title": "Ancien bike"},
        {"id": 60, "date": "2026-05-22", "sport": "run", "title": "Footing recup"},
        {"id": 63, "date": "2026-05-23", "sport": "bike", "title": "Endurance facile"},
        {"id": 61, "date": "2026-05-24", "sport": "run", "title": "VMA courte"},
        {"id": 62, "date": "2026-05-26", "sport": "bike", "title": "Endurance"},
    ]


def _scenarios() -> dict[str, ScenarioOracle]:
    followup2 = ScenarioOracle(
        name="followup_planning_turn2",
        description="User precise la séance de récup; move secondary session.",
        initial_db_state={},
        input_event=InputEvent(
            id="evt-5b",
            user_id=1,
            source="test",
            type="user_message",
            text="Je parle de la séance de récup.",
            payload={},
            occurred_at=datetime(2026, 5, 22, 15, 1, tzinfo=PARIS),
        ),
        expected_proposal_type="plan_patch",
        expected_policy_action="allow_commit",
        expected_commands=(CommandSpec("ApplyPlanPatchCommand", "session", "60"),),
        expected_reply_must_include=("déplacé", "vendredi"),
        expected_reply_must_not_contain=("VMA",),
        expected_session_dates=(("60", "2026-05-29"),),
    )
    return {
        "current_plan": ScenarioOracle(
            name="current_plan",
            description="User demande son plan actuel sans vieux plan.",
            initial_db_state={"today": "2026-05-22", "sessions": _base_sessions()},
            input_event=_event("evt-1", "Redonne-moi le plan actuel simplement, jour par jour.", 14),
            expected_proposal_type="answer",
            expected_policy_action="answer_only",
            expected_commands=(),
            expected_reply_must_include=("22", "24", "26"),
            expected_reply_must_not_contain=("7 mai", "14 mai", "07/05", "14/05"),
        ),
        "tomorrow": ScenarioOracle(
            name="tomorrow",
            description="User demande demain uniquement.",
            initial_db_state={"today": "2026-05-22", "sessions": _base_sessions()},
            input_event=_event("evt-2", "J'ai quoi demain exactement ?", 18),
            expected_proposal_type="answer",
            expected_policy_action="answer_only",
            expected_commands=(),
            expected_reply_must_include=("23",),
            expected_reply_must_not_contain=("22",),
        ),
        "skipped_yesterday": ScenarioOracle(
            name="skipped_yesterday",
            description="User dit qu'il n'a pas fait hier.",
            initial_db_state={
                "today": "2026-05-22",
                "sessions": [
                    {
                        "id": 66,
                        "date": "2026-05-21",
                        "sport": "run",
                        "title": "Footing",
                        "status": "planned",
                    }
                ],
            },
            input_event=_event("evt-3", "J'ai pas fait hier.", 9),
            expected_proposal_type="execution_update",
            expected_policy_action="allow_commit",
            expected_commands=(CommandSpec("SetSessionStatusCommand", "session", "66"),),
            expected_reply_must_include=("hier", "noté"),
            expected_reply_must_not_contain=("déplacé", "modifié", "appliqué"),
        ),
        "execution_correction": ScenarioOracle(
            name="execution_correction",
            description="User corrige l'event skipped précédent.",
            initial_db_state={
                "today": "2026-05-22",
                "sessions": [
                    {
                        "id": 66,
                        "date": "2026-05-21",
                        "sport": "run",
                        "title": "Footing",
                        "status": "skipped",
                    }
                ],
                "command_events": [
                    {
                        "id": 17,
                        "command_type": "SetSessionStatusCommand",
                        "target_id": "66",
                        "status": "applied",
                    }
                ],
            },
            input_event=_event(
                "evt-4",
                "En fait j'ai fait la séance finalement, mais seulement 25 minutes tranquille.",
                10,
            ),
            expected_proposal_type="execution_correction",
            expected_policy_action="allow_commit",
            expected_commands=(CommandSpec("CorrectSessionStatusCommand", "session", "66"),),
            expected_reply_must_include=("corrigé", "25"),
            expected_reply_must_not_contain=("nouvelle séance", "ajouté"),
        ),
        "followup_planning_turn1": ScenarioOracle(
            name="followup_planning_turn1",
            description="User dit décale ça à vendredi sans source.",
            initial_db_state={
                "today": "2026-05-22",
                "sessions": [
                    {"id": 60, "date": "2026-05-22", "sport": "run", "title": "Footing récup"},
                    {"id": 61, "date": "2026-05-23", "sport": "bike", "title": "Endurance"},
                    {
                        "id": 62,
                        "date": "2026-05-26",
                        "sport": "run",
                        "title": "VMA",
                        "priority": "key",
                    },
                ],
            },
            input_event=_event("evt-5a", "Décale ça à vendredi.", 15),
            expected_proposal_type="ask_clarification",
            expected_policy_action="ask_clarification",
            expected_commands=(CommandSpec("UpdateConversationStateCommand", "state", "1"),),
            expected_reply_must_include=("quelle", "séance"),
            expected_reply_must_not_contain=("déplacé",),
            followup=followup2,
        ),
    }
