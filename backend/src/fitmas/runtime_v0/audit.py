from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from fitmas.runtime_v0.db import connect
from fitmas.runtime_v0.event import InputEvent
from fitmas.runtime_v0.guard import GuardResult
from fitmas.runtime_v0.policy import PolicyDecision
from fitmas.runtime_v0.proposals import ActionProposal, proposal_to_dict
from fitmas.runtime_v0.result import RuntimeResult
from fitmas.runtime_v0.snapshot import WorldSnapshot


def persist_input_event(db_path: Path, event: InputEvent) -> None:
    with connect(db_path) as connection:
        connection.execute(
            "insert or ignore into v0_input_events (id, user_id, source, type, text, payload_json, occurred_at) values (?, ?, ?, ?, ?, ?, ?)",
            (
                event.id,
                event.user_id,
                event.source,
                event.type,
                event.text,
                json.dumps(event.payload, ensure_ascii=False, sort_keys=True),
                event.occurred_at.isoformat(),
            ),
        )
        connection.commit()


def persist_turn(
    db_path: Path,
    turn_id: str,
    event: InputEvent,
    snapshot: WorldSnapshot,
    proposal: ActionProposal,
    policy: PolicyDecision,
    result: RuntimeResult,
    reply: str,
    guard: GuardResult,
    tool_trace: list[dict[str, Any]],
    reply_source: str,
) -> None:
    persist_input_event(db_path, event)
    proposal_payload = proposal_to_dict(proposal) | {"tool_trace": tool_trace}
    with connect(db_path) as connection:
        connection.execute(
            """
            insert or replace into v0_turns (id, event_id, snapshot_json, proposal_json, policy_json, result_json, reply,
            reply_source, provider, model, latency_ms, tokens_in, tokens_out, guard_ok, guard_reasons_json)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                turn_id,
                event.id,
                _snapshot_json(snapshot),
                json.dumps(proposal_payload, ensure_ascii=False, sort_keys=True),
                json.dumps(asdict(policy), ensure_ascii=False, sort_keys=True, default=str),
                _result_json(result),
                reply,
                reply_source,
                "fake",
                "fake",
                0,
                0,
                0,
                1 if guard.ok else 0,
                json.dumps(guard.blocked_reasons, ensure_ascii=False),
            ),
        )
        connection.commit()


def load_turn(db_path: Path, turn_id: str):
    with connect(db_path) as connection:
        return connection.execute("select * from v0_turns where id = ?", (turn_id,)).fetchone()


def _snapshot_json(snapshot: WorldSnapshot) -> str:
    return _json({"user_id": snapshot.user_id, "today": snapshot.today.isoformat(), "now": snapshot.now.isoformat(), "timezone": snapshot.timezone})


def _result_json(result: RuntimeResult) -> str:
    return _json({
        "event_id": result.event_id, "turn_id": result.turn_id,
        "proposal_type": result.proposal_type, "policy_action": result.policy_action,
        "committed_event_count": len(result.committed_events), "blocked_reasons": result.blocked_reasons,
        "pending_id": result.pending.id if result.pending else None, "read_facts": result.read_facts,
    })


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
