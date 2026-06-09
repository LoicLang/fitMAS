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


def _encode_polyline(points: list[tuple[float, float]]) -> str:
    """Google-encoded polyline from (lat, lng) points (for a synthetic demo route)."""
    out: list[str] = []
    prev_lat = prev_lng = 0

    def _chunk(value: int) -> str:
        value = ~(value << 1) if value < 0 else (value << 1)
        s = ""
        while value >= 0x20:
            s += chr((0x20 | (value & 0x1F)) + 63)
            value >>= 5
        return s + chr(value + 63)

    for lat, lng in points:
        ilat, ilng = round(lat * 1e5), round(lng * 1e5)
        out.append(_chunk(ilat - prev_lat))
        out.append(_chunk(ilng - prev_lng))
        prev_lat, prev_lng = ilat, ilng
    return "".join(out)


# A synthetic ~loop (generic coordinates — NOT a real location) so the demo route
# map looks like a real run without exposing anyone's GPS data.
_DEMO_ROUTE = _encode_polyline([
    (48.000, 2.000), (48.004, 2.001), (48.007, 2.005), (48.009, 2.011),
    (48.008, 2.018), (48.004, 2.022), (47.999, 2.021), (47.996, 2.016),
    (47.995, 2.009), (47.997, 2.003), (48.000, 2.000),
])


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
        "insert into v0_activities "
        "(id,user_id,date,sport,duration_min,distance_km,notes,source,avg_speed,avg_hr,elevation_m,calories,map_polyline) "
        "values (1001,1,?,'running',47,9.2,'Sortie e2e','strava',2.8,148,120,520,?)",
        (today, _DEMO_ROUTE),
    )
    con.commit()
    con.close()
    print(f"seeded {db_path} for {today} (session 1 planned, activity 1001 off-plan)")


if __name__ == "__main__":
    seed(sys.argv[1])
