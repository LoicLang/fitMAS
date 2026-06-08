"""Couche-1 : preuve d'intégration du flux same-turn sous blessure.

Un pending semaine est ouvert. L'utilisateur répond "oui mais j'ai mal au genou".
Le coach (scripté ici par un fake) note le fait santé ET re-propose une semaine
sans intensité dans le MÊME tour. On vérifie l'état DB réel après le tour :
le fait santé est committé, l'ancien pending est superseded, un nouveau pending
adapté est ouvert, et RIEN n'est committé dans v0_planned_weeks (proposition seule).
La qualité de la VOIX et le déclenchement réel par le LLM se jugent en couche 2
(probe_live_simulation, persona blessure).
"""
from __future__ import annotations

from datetime import datetime, timezone

from fitmas.runtime_v0.db import connect, init_db
from fitmas.runtime_v0.event import InputEvent
from fitmas.runtime_v0.llm_clients.base import LLMResponse, ToolCall
from fitmas.runtime_v0.llm_clients.fake import FakeLLMClient
from fitmas.runtime_v0.runtime import RuntimeDeps, handle_event

NOW = datetime(2026, 6, 4, 9, 0, tzinfo=timezone.utc)  # jeudi -> lundi suivant 2026-06-08

_EASY_WEEK = [
    {"date": "2026-06-09", "type": "easy_run", "duration_min": 80, "intensity": "easy"},
    {"date": "2026-06-11", "type": "easy_run", "duration_min": 80, "intensity": "easy"},
    {"date": "2026-06-13", "type": "easy_run", "duration_min": 70, "intensity": "easy"},
    {"date": "2026-06-14", "type": "easy_run", "duration_min": 80, "intensity": "easy"},
]


def _seed_open_week_pending(db_path):
    with connect(db_path) as connection:
        connection.execute(
            "insert into v0_pending_confirmations "
            "(user_id, type, summary, payload_json, status, expires_at) "
            "values (?, ?, ?, ?, 'open', ?)",
            (1, "week_proposal", "semaine dure (seuil) proposée", "{}", "2026-12-31T00:00:00+00:00"),
        )
        connection.commit()


def test_oui_mais_blessure_notes_fact_and_reproposes_adapted_week_same_turn(tmp_path):
    db_path = tmp_path / "fitmas_v0.db"
    init_db(db_path)
    _seed_open_week_pending(db_path)

    event = InputEvent(
        id="evt-blessure", user_id=1, source="test", type="user_message",
        text="oui ça me va, mais j'ai mal au genou depuis hier", payload={}, occurred_at=NOW,
    )
    deps = RuntimeDeps(
        db_path=db_path,
        coach_llm=FakeLLMClient([
            LLMResponse(tool_calls=(
                ToolCall(name="propose_memory_update",
                         args={"kind": "health", "text": "douleur genou depuis hier", "confidence": 0.8}),
                ToolCall(name="propose_week",
                         args={"last_week_load": 300.0, "key_type": "threshold", "intensity_restricted": True}),
            )),
        ]),
        reply_llm=FakeLLMClient([
            LLMResponse(text="Le genou d'abord. Je te propose une version sans intensité, je cale ?")
        ]),
        generation_llm=FakeLLMClient([
            LLMResponse(tool_calls=(ToolCall(name="emit_week", args={"sessions": _EASY_WEEK}),))
        ]),
    )

    result = handle_event(event, deps=deps, turn_id="turn-blessure")

    with connect(db_path) as connection:
        facts = connection.execute(
            "select kind, text from v0_facts where user_id = 1"
        ).fetchall()
        pendings = connection.execute(
            "select status from v0_pending_confirmations order by id"
        ).fetchall()
        weeks = connection.execute("select count(*) as n from v0_planned_weeks").fetchone()["n"]

    # 1. la blessure est notée comme fait santé
    assert [f["kind"] for f in facts] == ["health"]
    # 2. l'ancienne semaine dure est superseded ; une seule semaine reste ouverte (l'adaptée)
    statuses = [p["status"] for p in pendings]
    assert "superseded" in statuses
    assert statuses.count("open") == 1
    # 3. rien n'est committé : la semaine adaptée est seulement proposée
    assert weeks == 0
    # 4. l'action du tour est bien une proposition de semaine
    assert result.runtime_result.proposal_type == "week_proposal"
