"""Spike: replay a real conversation turn through Runtime V0 and compare to the app.

Reads one (or more) real `conversation_turns` from a snapshot of the production
FitMAS DB, materializes an isolated V0 world as-of the turn, runs V0 on the real
`user_message` with a real provider, and prints V0's decision (proposal / policy
/ committed commands / reply) side-by-side with what the app actually did
(`assistant_message` + `mutation_applied` / `pending_confirmation` flags).

This is a feasibility spike for the app-vs-V0 comparison, NOT the full harness.

Fidelity caveat: the world is snapshotted from the *current* mutable
`scheduled_sessions` table with `as_of = turn.created_at`; sessions created or
re-mutated after the turn are not un-applied, so the plan V0 sees approximates
(does not exactly reproduce) the plan at turn time. Faithful as-of reconstruction
is the next step if the spike looks promising.

Doctrine: this harness never branches on the free `user_message` text. It passes
the message verbatim to V0 and reads only V0's *structured* output to summarize
behavior. The user text is data, not control flow.

Run (real provider; the provider key must be in the environment):
    set -a && . ./.env && set +a
    .venv/bin/python scripts/v0_eval/spike_real_turn.py \\
        --real-db .tmp-prod-fitmas.db --turn-ids 151,129 --provider deepseek
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _path in (ROOT, ROOT / "backend" / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from fitmas.runtime_v0.event import InputEvent  # noqa: E402
from fitmas.runtime_v0.runtime import HandleEventResult, RuntimeDeps, handle_event  # noqa: E402
from fitmas.runtime_v0.snapshot import SnapshotBuilder  # noqa: E402

from scripts.v0_eval.provider_clients import (  # noqa: E402
    MeteredLLMClient,
    ProviderConfigError,
    build_provider_client,
)
from scripts.v0_eval.real_snapshot import materialize_v0_db  # noqa: E402


def _parse_dt(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    if "T" not in normalized and " " in normalized:
        normalized = normalized.replace(" ", "T", 1)
    parsed = datetime.fromisoformat(normalized)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _load_turn(real_db: Path, turn_id: int) -> dict:
    connection = sqlite3.connect(real_db)
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute(
            """
            select id, user_id, user_message, assistant_message,
                   mutation_applied, pending_confirmation, created_at
            from conversation_turns where id = ?
            """,
            (turn_id,),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        raise SystemExit(f"conversation_turn {turn_id} not found in {real_db}")
    return dict(row)


def _safety_read(result: HandleEventResult) -> str:
    """Summarize whether V0 gated the action, from STRUCTURED output only.

    The app's real pattern is propose -> confirm (it asks before applying). The
    safety question is whether V0 also avoids an unconfirmed irreversible write.
    """
    runtime = result.runtime_result
    if runtime.pending is not None or runtime.policy_action in {"create_pending", "ask_clarification"}:
        return f"GATED ({runtime.policy_action}) — no unconfirmed write, matches app propose/confirm"
    if runtime.committed_events:
        kinds = ",".join(event.command_type for event in runtime.committed_events)
        return f"COMMITTED [{kinds}] — auto-applied without confirmation"
    return f"NO-OP ({runtime.policy_action}) — nothing committed"


def _run_one(real_db: Path, turn_id: int, provider: str, client, model: str, out_dir: Path) -> None:
    turn = _load_turn(real_db, turn_id)
    message = turn["user_message"]
    if not message:
        print(f"\nTURN #{turn_id}: no user_message (proactive/system turn) — skipped")
        return
    as_of = _parse_dt(turn["created_at"])
    user_id = int(turn["user_id"])

    shadow_db = out_dir / f"spike-turn-{turn_id}.db"
    materialize_v0_db(real_db, user_id, as_of, shadow_db)

    # Show the world V0 actually sees, so fidelity is auditable.
    snapshot = SnapshotBuilder(shadow_db).build(user_id, as_of)
    plan_preview = " | ".join(
        f"{s.date.isoformat()} {s.sport} {s.title} {s.duration_min}min {s.priority}/{s.status}"
        for s in snapshot.current_plan[:6]
    )

    meter = MeteredLLMClient(client, provider=provider, model=model)
    deps = RuntimeDeps(db_path=shadow_db, coach_llm=meter, reply_llm=meter)
    event = InputEvent(
        id=f"spike-{turn_id}",
        user_id=user_id,
        source="telegram",
        type="user_message",
        text=message,
        payload={},
        occurred_at=as_of,
    )
    started = time.perf_counter()
    result = handle_event(event, deps, turn_id=f"spike-{turn_id}")
    latency_ms = round(max(time.perf_counter() - started - meter.retry_wait_s, 0.0) * 1000)
    runtime = result.runtime_result

    print("\n" + "=" * 80)
    print(f"TURN #{turn_id}  |  {as_of.isoformat()}  |  user {user_id}  |  {provider}/{model}")
    print("=" * 80)
    print(f"USER: {message}")
    print(f"\nWORLD V0 SAW (as-of, current-state approximation): {len(snapshot.current_plan)} upcoming sessions")
    print(f"  {plan_preview or '(none in current-plan window)'}")
    if snapshot.active_facts:
        print("  facts: " + " ; ".join(fact.text[:60] for fact in snapshot.active_facts[:4]))

    print("\n--- V0 ---")
    print(f"  proposal={runtime.proposal_type}  policy={runtime.policy_action}  pending={'yes' if runtime.pending else 'no'}")
    if runtime.committed_events:
        for committed in runtime.committed_events:
            print(f"  committed: {committed.command_type} {committed.target_type}:{committed.target_id} [{committed.status}] {committed.reason[:70]}")
    else:
        print("  committed: (none)")
    if runtime.blocked_reasons:
        print(f"  blocked: {', '.join(runtime.blocked_reasons)}")
    print(f"  reply: {result.reply}")
    print(f"  cost: {latency_ms}ms  tokens_in={meter.tokens_in} tokens_out={meter.tokens_out}")
    print(f"  >> safety read: {_safety_read(result)}")

    print("\n--- APP (ground truth from conversation_turns) ---")
    print(f"  mutation_applied={turn['mutation_applied']}  pending_confirmation={turn['pending_confirmation']}")
    print(f"  reply: {turn['assistant_message']}")


def run_spike(real_db: Path, turn_ids: list[int], provider: str, out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        client = build_provider_client(provider)
    except ProviderConfigError as exc:
        print(f"provider_config_error: {exc}")
        print("Hint: load the provider key first — `set -a && . ./.env && set +a`")
        return 2
    model = getattr(getattr(client, "profile", None), "model", "unknown")
    print(f"spike: real_db={real_db} provider={provider}/{model} turns={turn_ids} out={out_dir}")
    for turn_id in turn_ids:
        _run_one(real_db, turn_id, provider, client, model, out_dir)
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Replay a real conversation turn through Runtime V0 and compare to the app.")
    parser.add_argument("--real-db", default=".tmp-prod-fitmas.db", type=Path)
    parser.add_argument("--turn-ids", default="151,129", help="comma-separated conversation_turn ids")
    parser.add_argument("--provider", default="deepseek")
    parser.add_argument("--out-dir", default=None, help="where to write shadow DBs (default: a temp dir)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    turn_ids = [int(token) for token in str(args.turn_ids).split(",") if token.strip()]
    out_dir = Path(args.out_dir) if args.out_dir else Path(tempfile.mkdtemp(prefix="v0-spike-"))
    return run_spike(args.real_db, turn_ids, args.provider, out_dir)


if __name__ == "__main__":
    raise SystemExit(main())
