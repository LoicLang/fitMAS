#!/usr/bin/env python3
"""One-shot: remove duplicate Strava activities from the V0 store.

Why this exists
---------------
The one-shot bootstrap (`materialize_v0_db`, 8 juin) wrote each activity into
`v0_activities` under the *legacy* `Activity.id` (a small autoincrement), while the
live Strava sync (`sync_strava_to_v0`) writes each run under its *Strava* id (huge).
The two used different id spaces and the Strava `external_id` was not carried into
`v0_activities`, so every Strava run that was both bootstrapped AND later synced
exists twice. `INSERT OR IGNORE` can't catch it (different ids), so the coach's
`recent_training` is double-counted and the `propose_week` seed is biased.

What it does
------------
Reads the legacy `activities` table to map `Activity.id -> external_id` (the Strava
id). For each run present under BOTH ids in `v0_activities`, it deletes the bootstrap
row (the legacy-id, source='strava' copy) and keeps the Strava-id row that the live
sync maintains. Dry-run by default; idempotent (a second run finds nothing).

The forward fix (bootstrap now keys Strava activities by their Strava id) lives in
`runtime_v0/adapters/current_db_snapshot.py`; this script cleans the store that was
already bootstrapped the old way.

Usage (run against the live Fly store — dry-run first!)
-------------------------------------------------------
    python scripts/cleanup_duplicate_activities.py \
        --v0-db /data/fitmas_v0_dogfood.db --legacy-db /data/fitmas.db --user 1
    # once the report looks right:
    python scripts/cleanup_duplicate_activities.py \
        --v0-db /data/fitmas_v0_dogfood.db --legacy-db /data/fitmas.db --user 1 --apply
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


def find_duplicates(
    v0_db: Path, legacy_db: Path, legacy_user_id: int
) -> list[tuple[int, int]]:
    """Return (legacy_id, strava_id) pairs duplicated in v0_activities."""
    legacy = sqlite3.connect(legacy_db)
    try:
        rows = legacy.execute(
            "select id, external_id from activities "
            "where user_id = ? and source = 'strava' and external_id is not null",
            (legacy_user_id,),
        ).fetchall()
    finally:
        legacy.close()

    pairs: list[tuple[int, int]] = []
    for legacy_id, external_id in rows:
        try:
            strava_id = int(external_id)
        except (TypeError, ValueError):
            continue
        if int(legacy_id) == strava_id:
            continue  # already aligned (forward fix) — nothing to dedupe
        pairs.append((int(legacy_id), strava_id))

    v0 = sqlite3.connect(v0_db)
    try:
        present = {r[0] for r in v0.execute("select id from v0_activities").fetchall()}
    finally:
        v0.close()

    # A duplicate exists only when BOTH the bootstrap (legacy-id) row and the
    # synced (strava-id) row are present.
    return [(l, s) for (l, s) in pairs if l in present and s in present]


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Remove bootstrap/sync duplicate Strava activities from the V0 store."
    )
    ap.add_argument("--v0-db", required=True, type=Path, help="V0 store (v0_activities)")
    ap.add_argument("--legacy-db", required=True, type=Path, help="legacy store (activities)")
    ap.add_argument("--user", required=True, type=int, help="legacy user id (e.g. 1)")
    ap.add_argument(
        "--apply",
        action="store_true",
        help="delete the duplicate bootstrap rows (default: dry-run)",
    )
    args = ap.parse_args()

    dups = find_duplicates(args.v0_db, args.legacy_db, args.user)
    print(
        f"found {len(dups)} duplicated Strava activities "
        f"(bootstrap legacy-id rows shadowing synced strava-id rows)"
    )
    for legacy_id, strava_id in dups:
        print(f"  delete legacy id {legacy_id}  (keep strava id {strava_id})")

    if not dups:
        print("nothing to clean.")
        return

    if not args.apply:
        print("\ndry-run: pass --apply to delete the bootstrap rows.")
        return

    v0 = sqlite3.connect(args.v0_db)
    try:
        v0.executemany(
            "delete from v0_activities where id = ? and source = 'strava'",
            [(legacy_id,) for (legacy_id, _) in dups],
        )
        v0.commit()
        deleted = v0.total_changes
    finally:
        v0.close()
    print(f"\ndeleted {deleted} duplicate bootstrap rows. Strava-id rows kept.")


if __name__ == "__main__":
    main()
