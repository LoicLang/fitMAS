#!/usr/bin/env python3
"""One-turn live driver for V0 multi-turn testing.

A live "tester" (human or subagent) drives a real conversation against the V0
runtime, one turn at a time, against a persisted shadow DB. Conversation state
(pending confirmations, last_unresolved_intent) carries across turns because the
shadow DB persists it and the SnapshotBuilder rereads it each turn.

The runtime's notion of "today" comes from the event timestamp (--date), not the
wall clock, so runs are reproducible regardless of when they execute.

Subcommands:
  seed  --scenario followup_planning_turn1 --db /tmp/shadow.db
        Reset a shadow DB and seed it from a scenario's initial_db_state. No LLM.

  seed  --from-real-db copy.db --user 1 [--as-of 2026-06-01T08:00:00+02:00]
        --db /tmp/shadow.db
        Reset a shadow DB and materialize it from a (read-only) copy of the real
        app DB for one user, as of an instant (default: now). A couche-2 sim then
        starts from the real world (plan / history / facts) instead of a synthetic
        seed. Source is the live `current_state` adapter, not a faithful past
        replay. No LLM.

  turn  --db /tmp/shadow.db --text "Décale ça à vendredi" --turn-id t1
        [--provider deepseek] [--date 2026-05-22] [--hour 15] [--minute 0]
        Run ONE real coach turn. Prints `RESULT <json>` (single line) with the
        visible reply plus structured outcome fields.

  state --db /tmp/shadow.db
        Dump sessions / pending / conversation state / command audit. No LLM.
        This is the mechanical outcome oracle's read surface.

Self-loads ./.env and wires sys.path so callers need no env/PYTHONPATH plumbing.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
BACKEND_SRC = ROOT / "backend" / "src"
for _path in (ROOT, BACKEND_SRC):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))


def _load_env(root: Path) -> None:
    """Load KEY=VALUE pairs from ./.env into os.environ (existing env wins)."""
    import os

    env_path = root / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_env(ROOT)

from fitmas.runtime_v0.adapters.current_db_snapshot import SnapshotSource, materialize_v0_db  # noqa: E402
from fitmas.runtime_v0.db import connect  # noqa: E402
from fitmas.runtime_v0.event import InputEvent  # noqa: E402
from fitmas.runtime_v0.runtime import RuntimeDeps, handle_event  # noqa: E402
from scripts.v0_eval.provider_clients import MeteredLLMClient, build_provider_client  # noqa: E402
from scripts.v0_eval.scenarios import scenario_by_name, seed_db  # noqa: E402

PARIS = ZoneInfo("Europe/Paris")


def _emit(payload: dict) -> None:
    print("RESULT " + json.dumps(payload, ensure_ascii=False))


def _seeded_sessions(db_path: Path) -> list[dict]:
    with connect(db_path) as conn:
        return [dict(row) for row in conn.execute(
            "select id, date, sport, title, status, priority from v0_scheduled_sessions order by date, id"
        )]


def _parse_as_of(value: str | None) -> datetime:
    """Reference instant for the snapshot. Defaults to now (UTC) when omitted."""
    if not value:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _seed_from_scenario(args: argparse.Namespace) -> int:
    scenario = scenario_by_name(args.scenario)
    db_path = Path(args.db)
    seed_db(db_path, scenario.initial_db_state)
    _emit({
        "seeded": str(db_path),
        "source": "scenario",
        "scenario": scenario.name,
        "today": scenario.initial_db_state.get("today"),
        "sessions": _seeded_sessions(db_path),
    })
    return 0


def _seed_from_real_db(args: argparse.Namespace) -> int:
    if args.user is None:
        _emit({"error": "missing_user:--user is required with --from-real-db"})
        return 1
    real_db = Path(args.from_real_db)
    if not real_db.exists():
        _emit({"error": f"real_db_not_found:{real_db}"})
        return 1
    as_of = _parse_as_of(args.as_of)
    db_path = Path(args.db)
    materialize_v0_db(real_db, args.user, as_of, db_path)
    _emit({
        "seeded": str(db_path),
        "source": SnapshotSource.CURRENT_STATE,
        "from_real_db": str(real_db),
        "user_id": args.user,
        "as_of": as_of.isoformat(),
        "sessions": _seeded_sessions(db_path),
    })
    return 0


def cmd_seed(args: argparse.Namespace) -> int:
    if args.from_real_db:
        return _seed_from_real_db(args)
    return _seed_from_scenario(args)


def cmd_turn(args: argparse.Namespace) -> int:
    db_path = Path(args.db)
    if not db_path.exists():
        _emit({"error": f"db_not_found:{db_path}"})
        return 1
    day = datetime.fromisoformat(args.date).date()
    occurred_at = datetime(day.year, day.month, day.day, args.hour, args.minute, tzinfo=PARIS)
    event = InputEvent(
        id=f"drive-evt-{args.turn_id}",
        user_id=1,
        source="test",
        type="user_message",
        text=args.text,
        payload={},
        occurred_at=occurred_at,
    )
    try:
        client = build_provider_client(args.provider)
        model = getattr(getattr(client, "profile", None), "model", "unknown")
        meter = MeteredLLMClient(client, provider=args.provider, model=model)
        deps = RuntimeDeps(db_path=db_path, coach_llm=meter, reply_llm=meter)
        result = handle_event(event, deps, turn_id=args.turn_id)
    except Exception as exc:  # noqa: BLE001
        _emit({"error": f"{type(exc).__name__}:{exc}", "turn_id": args.turn_id})
        return 1

    committed = [
        {"command_type": e.command_type, "target_id": e.target_id, "status": e.status}
        for e in result.runtime_result.committed_events
    ]
    pending = result.runtime_result.pending
    _emit({
        "turn_id": result.turn_id,
        "provider": args.provider,
        "reply": result.reply,
        "proposal_type": result.proposal.type,
        "policy_action": result.policy.action,
        "command_types": [e["command_type"] for e in committed],
        "committed": committed,
        "pending": (pending.summary if pending is not None else None),
        "guard_ok": result.guard.ok,
        "guard_reasons": list(result.guard.blocked_reasons),
        "tokens_in": meter.tokens_in,
        "tokens_out": meter.tokens_out,
        "calls": meter.calls,
    })
    return 0


def cmd_state(args: argparse.Namespace) -> int:
    db_path = Path(args.db)
    if not db_path.exists():
        _emit({"error": f"db_not_found:{db_path}"})
        return 1
    with connect(db_path) as conn:
        sessions = [dict(row) for row in conn.execute(
            "select id, date, sport, title, duration_min, intensity_label, priority, status "
            "from v0_scheduled_sessions order by date, id"
        )]
        pending = [dict(row) for row in conn.execute(
            "select id, type, summary, status, expires_at from v0_pending_confirmations order by id"
        )]
        state_row = conn.execute(
            "select last_unresolved_intent_json, last_pending_id, last_execution_event_id, last_user_turn_id "
            "from v0_conversation_state where user_id = 1"
        ).fetchone()
        commands = [dict(row) for row in conn.execute(
            "select turn_id, command_type, target_id, status from v0_command_events order by id"
        )]
    intent = None
    if state_row and state_row["last_unresolved_intent_json"]:
        try:
            intent = json.loads(state_row["last_unresolved_intent_json"])
        except json.JSONDecodeError:
            intent = state_row["last_unresolved_intent_json"]
    _emit({
        "db": str(db_path),
        "sessions": sessions,
        "pending": pending,
        "last_unresolved_intent": intent,
        "last_pending_id": (state_row["last_pending_id"] if state_row else None),
        "commands": commands,
    })
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="One-turn live driver for V0 multi-turn testing.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_seed = sub.add_parser("seed", help="Reset + seed a shadow DB from a scenario or a real-DB copy.")
    p_seed_src = p_seed.add_mutually_exclusive_group(required=True)
    p_seed_src.add_argument("--scenario", help="Seed from a named synthetic scenario.")
    p_seed_src.add_argument("--from-real-db", help="Materialize from a (read-only) copy of the real app DB.")
    p_seed.add_argument("--user", type=int, help="User id to snapshot (required with --from-real-db).")
    p_seed.add_argument("--as-of", help="Snapshot reference instant (ISO 8601). Default: now.")
    p_seed.add_argument("--db", required=True)
    p_seed.set_defaults(func=cmd_seed)

    p_turn = sub.add_parser("turn", help="Run one real coach turn.")
    p_turn.add_argument("--db", required=True)
    p_turn.add_argument("--text", required=True)
    p_turn.add_argument("--turn-id", required=True)
    p_turn.add_argument("--provider", default="deepseek")
    p_turn.add_argument("--date", default="2026-05-22")
    p_turn.add_argument("--hour", type=int, default=15)
    p_turn.add_argument("--minute", type=int, default=0)
    p_turn.set_defaults(func=cmd_turn)

    p_state = sub.add_parser("state", help="Dump shadow DB state (oracle read surface).")
    p_state.add_argument("--db", required=True)
    p_state.set_defaults(func=cmd_state)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
