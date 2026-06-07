"""Couche-2 probe for Slice 3b: does the coach propose a week (turn 1) then commit or
reject it correctly (turn 2)?

Two scenarios are driven back-to-back:
  ACCEPT — turn 2 phrase "oui, valide", expect: 1 row in v0_planned_weeks + guard ok.
  REJECT — turn 2 phrase "non, pas cette semaine", expect: 0 rows in v0_planned_weeks
           + pending rejected + guard ok.

Both scenarios use a real DB (in-memory temp file) and a real provider so the full
CoachAgent -> policy -> executor -> reply -> guard loop runs. The probe judges PASS/FAIL
from the actual DB state, NOT from the reply text.

Run (requires provider creds):
    set -a && . ./.env && set +a
    .venv/bin/python scripts/v0_eval/probe_resolve_pending.py --provider deepseek

This is a couche-2 probe: run manually with creds. Not a pytest test.
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _path in (ROOT, ROOT / "backend" / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from fitmas.runtime_v0.db import connect, init_db  # noqa: E402
from fitmas.runtime_v0.event import InputEvent  # noqa: E402
from fitmas.runtime_v0.runtime import HandleEventResult, RuntimeDeps, handle_event  # noqa: E402
from fitmas.runtime_v0.snapshot import ActivityView, SessionView, WorldSnapshot  # noqa: E402
from fitmas.runtime_v0.state import ConversationState  # noqa: E402

from scripts.v0_eval.provider_clients import (  # noqa: E402
    MeteredLLMClient,
    ProviderConfigError,
    build_provider_client,
)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _seed_recent_training(db_path: Path, today: date, user_id: int = 1) -> None:
    """Seed last-week training sessions and activities into the DB so the
    SnapshotBuilder surfaces `recent_plan` + `recent_activities` for the coach."""
    sessions = [
        (user_id, (today - timedelta(days=6)).isoformat(), "run", "Footing", 45, "easy", "optional", "done"),
        (user_id, (today - timedelta(days=4)).isoformat(), "run", "Seuil 3x8", 60, "hard", "key", "done"),
        (user_id, (today - timedelta(days=2)).isoformat(), "run", "Footing", 50, "easy", "secondary", "done"),
        (user_id, (today - timedelta(days=1)).isoformat(), "run", "Sortie longue", 90, "moderate", "key", "done"),
    ]
    activities = [
        (user_id, (today - timedelta(days=6)).isoformat(), "run", 45, 8.0, None, "strava"),
        (user_id, (today - timedelta(days=4)).isoformat(), "run", 60, 12.0, "seuil", "strava"),
        (user_id, (today - timedelta(days=1)).isoformat(), "run", 90, 18.0, "longue", "strava"),
    ]
    with connect(db_path) as conn:
        conn.executemany(
            "insert into v0_scheduled_sessions (user_id, date, sport, title, duration_min, intensity_label, priority, status) values (?,?,?,?,?,?,?,?)",
            sessions,
        )
        conn.executemany(
            "insert into v0_activities (user_id, date, sport, duration_min, distance_km, notes, source) values (?,?,?,?,?,?,?)",
            activities,
        )
        conn.commit()


def _count_planned_weeks(db_path: Path, user_id: int = 1) -> int:
    with connect(db_path) as conn:
        row = conn.execute(
            "select count(*) as n from v0_planned_weeks where user_id = ?", (user_id,)
        ).fetchone()
    return row["n"]


def _pending_status(db_path: Path, user_id: int = 1) -> str | None:
    """Return the status of the most recent pending confirmation for user_id."""
    with connect(db_path) as conn:
        row = conn.execute(
            "select status from v0_pending_confirmations where user_id = ? order by id desc limit 1",
            (user_id,),
        ).fetchone()
    return row["status"] if row else None


# ---------------------------------------------------------------------------
# Build RuntimeDeps (mirrors probe_propose_week.py pattern)
# ---------------------------------------------------------------------------

def _build_deps(db_path: Path, provider: str) -> tuple[RuntimeDeps, MeteredLLMClient, MeteredLLMClient, MeteredLLMClient]:
    coach_raw = build_provider_client(provider, max_tokens=1024)
    generation_raw = build_provider_client(provider, max_tokens=4096)
    reply_raw = build_provider_client(provider, max_tokens=4096)

    model = getattr(getattr(coach_raw, "profile", None), "model", "unknown")
    coach_m = MeteredLLMClient(coach_raw, provider=provider, model=model)
    generation_m = MeteredLLMClient(generation_raw, provider=provider, model=model)
    reply_m = MeteredLLMClient(reply_raw, provider=provider, model=model)

    deps = RuntimeDeps(
        db_path=db_path,
        coach_llm=coach_m,
        reply_llm=reply_m,
        generation_llm=generation_m,
        max_steps=6,
    )
    return deps, coach_m, generation_m, reply_m


# ---------------------------------------------------------------------------
# Run one two-turn scenario
# ---------------------------------------------------------------------------

def _make_event(text: str, now: datetime, event_id: str, user_id: int = 1) -> InputEvent:
    return InputEvent(
        id=event_id,
        user_id=user_id,
        source="telegram",
        type="user_message",
        text=text,
        payload={},
        occurred_at=now,
    )


def _print_turn(label: str, result: HandleEventResult) -> None:
    print(f"  [{label}]")
    print(f"    proposal.type = {result.proposal.type}")
    tools = [c.get("name") for c in result.proposal.tool_trace]
    print(f"    tools called  = {tools or '(none)'}")
    print(f"    policy.action = {result.policy.action}")
    print(f"    guard.ok      = {result.guard.ok}  reasons={result.guard.blocked_reasons}")
    print(f"    reply excerpt = {result.reply[:120]!r}")


def _run_scenario(
    label: str,
    turn2_phrase: str,
    provider: str,
    now: datetime,
    expected_weeks: int,
) -> bool:
    """
    Drive a two-turn session in a fresh DB:
      turn 1: propose next week
      turn 2: accept or reject phrase

    Returns True if the DB state matches expectations.
    """
    print(f"\n{'=' * 70}")
    print(f"SCENARIO: {label}  |  provider={provider}  |  today={now.date()}")
    print(f"  turn-1: 'fais-moi ma semaine prochaine'")
    print(f"  turn-2: {turn2_phrase!r}")
    print(f"  expected committed weeks: {expected_weeks}")
    print("-" * 70)

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)

    try:
        init_db(db_path)
        _seed_recent_training(db_path, now.date())

        deps, coach_m, generation_m, reply_m = _build_deps(db_path, provider)

        # Turn 1: propose week
        ev1 = _make_event("fais-moi ma semaine prochaine", now, "probe-3b-t1")
        r1 = handle_event(ev1, deps, "probe-3b-t1")
        _print_turn("turn 1", r1)

        # Verify turn 1 landed a pending
        if r1.policy.action != "create_pending":
            print(f"  WARN: turn 1 policy={r1.policy.action}, expected create_pending — turn 2 may fail")

        # Turn 2: resolve (accept or reject)
        now2 = now + timedelta(minutes=1)
        ev2 = _make_event(turn2_phrase, now2, "probe-3b-t2")
        r2 = handle_event(ev2, deps, "probe-3b-t2")
        _print_turn("turn 2", r2)

        # Judge outcome
        weeks = _count_planned_weeks(db_path)
        pending_st = _pending_status(db_path)
        guard_ok = r2.guard.ok

        print(f"\n  DB state: v0_planned_weeks={weeks}  pending_status={pending_st}")
        print(f"  cost: coach_in={coach_m.tokens_in} coach_out={coach_m.tokens_out} gen_out={generation_m.tokens_out}")

        if weeks == expected_weeks and guard_ok:
            print(f"\n  PASS — committed_weeks={weeks} == {expected_weeks} and guard ok")
            return True
        else:
            reasons = []
            if weeks != expected_weeks:
                reasons.append(f"committed_weeks={weeks} != {expected_weeks}")
            if not guard_ok:
                reasons.append(f"guard_failed reasons={r2.guard.blocked_reasons}")
            print(f"\n  FAIL — {'; '.join(reasons)}")
            return False

    finally:
        db_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Couche-2 probe for pending_resolution (Slice 3b)")
    parser.add_argument("--provider", default="deepseek")
    parser.add_argument("--accept-phrase", default="oui, valide")
    parser.add_argument("--reject-phrase", default="non, pas cette semaine")
    args = parser.parse_args()

    try:
        # Validate creds early with a cheap instantiation
        build_provider_client(args.provider, max_tokens=1024)
    except ProviderConfigError as exc:
        print(f"provider_config_error: {exc}\nHint: set -a && . ./.env && set +a")
        return 2

    now = datetime(2026, 6, 9, 18, 0, tzinfo=timezone.utc)  # Monday evening

    results = []

    results.append(
        _run_scenario(
            label="ACCEPT",
            turn2_phrase=args.accept_phrase,
            provider=args.provider,
            now=now,
            expected_weeks=1,
        )
    )

    results.append(
        _run_scenario(
            label="REJECT",
            turn2_phrase=args.reject_phrase,
            provider=args.provider,
            now=now,
            expected_weeks=0,
        )
    )

    print(f"\n{'=' * 70}")
    passed = sum(results)
    total = len(results)
    print(f"RESULT: {passed}/{total} scenarios PASS")
    if passed == total:
        print("OVERALL: PASS")
        return 0
    print("OVERALL: FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
