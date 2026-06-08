"""Seed the V0 dogfood store with a "last week" anchor.

The Meso engine forward-chains: it seeds next week from the last committed week
(`v0_planned_weeks`). Run this ONCE before the dogfood runner so the coach proposes
from a known load + key instead of cold-starting. After that, every confirmed week
becomes the seed of the next — you never re-seed.

It reads:
  FITMAS_V0_DB_PATH            the dogfood store (default fitmas_v0.db)
  FITMAS_V0_DOGFOOD_CHAT_IDS   your Telegram chat id (the runner uses it as user_id)

Idempotent: skips if a committed week already exists for that user.

Usage:
    export FITMAS_V0_DOGFOOD_CHAT_IDS="<your telegram chat id>"
    export FITMAS_V0_DB_PATH="fitmas_v0_dogfood.db"
    .venv/bin/python scripts/seed_dogfood.py            # load 88, key long_run
    .venv/bin/python scripts/seed_dogfood.py --load 125 --key threshold
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "backend" / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fitmas.runtime_v0.db import connect, db_path_from_env, init_db  # noqa: E402

# Loïc's real last week (Strava, 2026-06-01..07): a 73-min deload, all easy.
# week_load is set to the chosen seed (boosted), key_type to the chosen forward key.
_WEEK_START = "2026-06-01"
_SESSIONS = [
    {"date": "2026-06-03", "type": "easy_run", "duration_min": 29, "intensity": "easy", "detail": "réel (Strava)"},
    {"date": "2026-06-07", "type": "easy_run", "duration_min": 44, "intensity": "easy", "detail": "réel (Strava)"},
]


def main() -> None:
    ap = argparse.ArgumentParser(description="Seed the V0 dogfood store with a last-week anchor")
    ap.add_argument("--load", type=float, default=88.0, help="seed week load (duration-weighted)")
    ap.add_argument("--key", default="long_run", help="prescribed key session type going forward")
    args = ap.parse_args()

    ids = [x.strip() for x in os.getenv("FITMAS_V0_DOGFOOD_CHAT_IDS", "").split(",") if x.strip()]
    if not ids:
        raise SystemExit("Set FITMAS_V0_DOGFOOD_CHAT_IDS to your Telegram chat id first.")
    user_id = int(ids[0])

    db_path = db_path_from_env()
    init_db(db_path)

    with connect(db_path) as conn:
        existing = conn.execute(
            "select count(*) as n from v0_planned_weeks where user_id = ? and status = 'committed'",
            (user_id,),
        ).fetchone()["n"]
        if existing:
            print(f"seed skipped: user {user_id} already has {existing} committed week(s) in {db_path}")
            return
        conn.execute(
            "insert into v0_planned_weeks (user_id, week_start, source, week_load, key_type, sessions_json, status) "
            "values (?, ?, 'seed', ?, ?, ?, 'committed')",
            (user_id, _WEEK_START, args.load, args.key, json.dumps(_SESSIONS, ensure_ascii=False)),
        )
        conn.commit()
    print(f"seeded anchor: user={user_id} week_start={_WEEK_START} load={args.load} key={args.key} -> {db_path}")


if __name__ == "__main__":
    main()
