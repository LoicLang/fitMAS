"""Seed a V0 store for the e2e UI test.

Creates today's planned running session + an off-plan running activity on the same
day, so the webapp calendar (FITMAS_APP_SOURCE=v0) shows an off-plan activity with a
"Lier à ..." control and a planned session target.

Usage: .venv/bin/python scripts/e2e_seed_v0.py <db_path>
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import date
from pathlib import Path

from fitmas.runtime_v0.db import init_db


def seed(db_path: str) -> None:
    path = Path(db_path)
    if path.exists():
        path.unlink()
    init_db(path)
    today = date.today().isoformat()
    con = sqlite3.connect(path)
    con.execute(
        "insert into v0_scheduled_sessions (id,user_id,date,sport,title,duration_min,intensity_label,priority,status) "
        "values (1,1,?,'running','Footing du jour',45,'easy','secondary','planned')",
        (today,),
    )
    con.execute(
        "insert into v0_activities (id,user_id,date,sport,duration_min,distance_km,notes,source) "
        "values (1001,1,?,'running',47,9.2,'Sortie e2e','strava')",
        (today,),
    )
    con.commit()
    con.close()
    print(f"seeded {db_path} for {today} (session 1 planned, activity 1001 off-plan)")


if __name__ == "__main__":
    seed(sys.argv[1])
