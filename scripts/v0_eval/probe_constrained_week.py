"""Couche-2 probe: does propose_week RESPECT an active constraint, regenerate to
honor it, and still commit cleanly through pending validation?

Seeds an active health fact (an intensity-restricting injury) alongside recent
training, then for N reps drives a two-turn session:

  turn 1: "fais-moi ma semaine prochaine" -> propose. The proposed week is read
          from the pending payload and checked by an INDEPENDENT oracle: NO hard
          intensity, NO quality-key session (threshold/intervals) — the active
          constraint forbids hard work. The generator `source` (llm vs
          template_fallback) is reported so we can see whether the LLM honored the
          constraint directly or the generate->verify loop fell back to the
          deterministic net (i.e. regeneration in action).
  turn 2: "oui, valide" -> commit. The COMMITTED week (v0_planned_weeks) is
          re-checked against the constraint; pending must be 'accepted'; guard ok.

The probe judges constraint respect from the actual session data, NOT from the
verifier's verdict — so a verifier gap would surface here, not hide.

Run (requires provider creds):
    set -a && . ./.env && set +a
    .venv/bin/python scripts/v0_eval/probe_constrained_week.py --provider deepseek --reps 3

This is a couche-2 probe: run manually with creds. Not a pytest test.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _path in (ROOT, ROOT / "backend" / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from fitmas.runtime_v0.db import connect, init_db  # noqa: E402
from fitmas.runtime_v0.runtime import handle_event  # noqa: E402

from scripts.v0_eval.probe_resolve_pending import (  # noqa: E402
    _build_deps,
    _count_planned_weeks,
    _make_event,
    _pending_status,
    _print_turn,
    _seed_recent_training,
)
from scripts.v0_eval.provider_clients import (  # noqa: E402
    ProviderConfigError,
    build_provider_client,
)

# A quality-key session is inherently hard work; an intensity restriction forbids it.
_QUALITY_KEYS = {"threshold", "intervals"}
_INJURY = "Douleur au genou droit, pas d'intensité ni de fractionné cette semaine"


def _seed_health_fact(db_path: Path, text: str, confidence: float = 0.8, user_id: int = 1) -> None:
    """Seed an ACTIVE health fact (no expiry, not resolved) so the snapshot maps it
    to an intensity-restricting TypedConstraint in the context-pack."""
    with connect(db_path) as conn:
        conn.execute(
            "insert into v0_facts (user_id, kind, text, confidence, expires_at, resolved_at) values (?,?,?,?,?,?)",
            (user_id, "health", text, confidence, None, None),
        )
        conn.commit()


def _constraint_violations(sessions: list[dict]) -> list[dict]:
    """Sessions that breach an intensity restriction: hard intensity OR a quality key."""
    return [
        s for s in sessions
        if s.get("intensity") == "hard" or s.get("type") in _QUALITY_KEYS
    ]


def _proposed_week(db_path: Path, user_id: int = 1) -> tuple[list[dict] | None, str | None]:
    """The week sitting in the latest pending payload (before commit)."""
    with connect(db_path) as conn:
        row = conn.execute(
            "select payload_json from v0_pending_confirmations where user_id = ? order by id desc limit 1",
            (user_id,),
        ).fetchone()
    if row is None:
        return None, None
    week = (json.loads(row["payload_json"]) or {}).get("week_proposal") or {}
    return week.get("sessions"), week.get("source")


def _committed_week(db_path: Path, user_id: int = 1) -> tuple[list[dict] | None, str | None]:
    """The latest committed typed week (after accept)."""
    with connect(db_path) as conn:
        row = conn.execute(
            "select sessions_json, source from v0_planned_weeks where user_id = ? order by id desc limit 1",
            (user_id,),
        ).fetchone()
    if row is None:
        return None, None
    return json.loads(row["sessions_json"]), row["source"]


def _fmt_week(sessions: list[dict]) -> str:
    return " | ".join(
        f"{s.get('date','?')[-5:]} {s.get('type','?')} {s.get('duration_min','?')}m {s.get('intensity','?')}"
        for s in sessions
    )


def _run_rep(rep: int, provider: str, now: datetime) -> dict:
    print(f"\n{'-' * 70}\n  REP {rep}  (constraint active: {_INJURY!r})")
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)
    outcome: dict = {"rep": rep, "pass": False, "notes": []}
    try:
        init_db(db_path)
        _seed_recent_training(db_path, now.date())
        _seed_health_fact(db_path, _INJURY)
        deps, coach_m, gen_m, _ = _build_deps(db_path, provider)

        # Turn 1 — propose
        r1 = handle_event(_make_event("fais-moi ma semaine prochaine", now, f"c-{rep}-t1"), deps, f"c-{rep}-t1")
        _print_turn("turn 1", r1)
        outcome["t1_action"] = r1.policy.action

        if r1.policy.action != "create_pending":
            outcome["notes"].append(f"coach did not propose (action={r1.policy.action})")
            print(f"    -> no week proposed; cannot test constraint respect this rep")
            return outcome

        proposed, src = _proposed_week(db_path)
        outcome["source"] = src
        if not proposed:
            outcome["notes"].append("pending had no week_proposal payload")
            return outcome
        print(f"    proposed (source={src}): {_fmt_week(proposed)}")
        prop_bad = _constraint_violations(proposed)
        if prop_bad:
            outcome["notes"].append(f"PROPOSED week violates constraint: {[ (b.get('type'), b.get('intensity')) for b in prop_bad ]}")
            print(f"    !! proposed week breaks the constraint: {prop_bad}")

        # Turn 2 — accept
        r2 = handle_event(_make_event("oui, valide", now + timedelta(minutes=1), f"c-{rep}-t2"), deps, f"c-{rep}-t2")
        _print_turn("turn 2", r2)
        outcome["t2_action"] = r2.policy.action

        weeks = _count_planned_weeks(db_path)
        pending_st = _pending_status(db_path)
        committed, csrc = _committed_week(db_path)
        comm_bad = _constraint_violations(committed) if committed else None
        if committed:
            print(f"    committed (source={csrc}): {_fmt_week(committed)}")
        print(f"    DB: weeks={weeks} pending={pending_st} guard_ok={r2.guard.ok}")
        print(f"    cost: coach_out={coach_m.tokens_out} gen_out={gen_m.tokens_out}")

        ok = (
            not prop_bad
            and weeks == 1
            and pending_st == "accepted"
            and r2.guard.ok
            and committed is not None
            and not comm_bad
        )
        if not ok:
            if weeks != 1:
                outcome["notes"].append(f"committed weeks={weeks} != 1")
            if pending_st != "accepted":
                outcome["notes"].append(f"pending={pending_st} != accepted")
            if not r2.guard.ok:
                outcome["notes"].append(f"guard failed: {r2.guard.blocked_reasons}")
            if comm_bad:
                outcome["notes"].append(f"COMMITTED week violates constraint: {[ (b.get('type'), b.get('intensity')) for b in comm_bad ]}")
        outcome["pass"] = ok
        print(f"    REP {rep}: {'PASS' if ok else 'FAIL'}" + (f" — {'; '.join(outcome['notes'])}" if outcome["notes"] else ""))
        return outcome
    finally:
        db_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Couche-2 probe: constrained week generation + commit")
    parser.add_argument("--provider", default="deepseek")
    parser.add_argument("--reps", type=int, default=3)
    args = parser.parse_args()

    try:
        build_provider_client(args.provider, max_tokens=1024)
    except ProviderConfigError as exc:
        print(f"provider_config_error: {exc}\nHint: set -a && . ./.env && set +a")
        return 2

    now = datetime(2026, 6, 9, 18, 0, tzinfo=timezone.utc)  # a Tuesday evening
    print(f"{'=' * 70}\nCONSTRAINED-WEEK PROBE  |  provider={args.provider}  |  reps={args.reps}")
    print("Constraint: active health fact restricts intensity -> the proposed AND")
    print("committed week must contain NO hard session and NO threshold/intervals.")

    outcomes = [_run_rep(rep, args.provider, now) for rep in range(1, args.reps + 1)]

    print(f"\n{'=' * 70}\nSUMMARY")
    passed = sum(1 for o in outcomes if o["pass"])
    sources = [o.get("source") for o in outcomes if o.get("source")]
    proposed_count = sum(1 for o in outcomes if o.get("t1_action") == "create_pending")
    print(f"  reps={len(outcomes)} pass={passed}")
    print(f"  coach proposed a week: {proposed_count}/{len(outcomes)}")
    print(f"  generation source per rep: {sources}  (llm = LLM honored constraint; template_fallback = net caught it)")
    for o in outcomes:
        tag = "PASS" if o["pass"] else "FAIL"
        print(f"    rep {o['rep']}: {tag}" + (f" — {'; '.join(o['notes'])}" if o["notes"] else ""))
    overall = passed == len(outcomes)
    print(f"\nOVERALL: {'PASS' if overall else 'FAIL'}")
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
