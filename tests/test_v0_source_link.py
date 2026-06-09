import sqlite3
import importlib
from fitmas.runtime_v0.db import init_db


def _seed(db):
    init_db(db)
    con = sqlite3.connect(db)
    con.execute("insert into v0_activities (id,user_id,date,sport,duration_min,distance_km,notes,source,scheduled_session_id) "
                "values (3,77,'2026-06-08','running',50,9.0,'r','strava',12)")
    con.commit(); con.close()


def test_get_activities_exposes_scheduled_session_id(tmp_path, monkeypatch):
    db = tmp_path / "v0.db"; _seed(db)
    monkeypatch.setenv("FITMAS_V0_DB_PATH", str(db))
    from fitmas.legacy.app.api import v0_source
    importlib.reload(v0_source)
    acts = v0_source.get_activities()
    assert acts[0].scheduled_session_id == 12
    assert v0_source.v0_user_id() == 77
