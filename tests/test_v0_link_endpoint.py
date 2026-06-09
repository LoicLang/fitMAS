import sqlite3
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fitmas.runtime_v0.db import init_db


def _app(db, monkeypatch):
    monkeypatch.setenv("FITMAS_V0_DB_PATH", str(db))
    monkeypatch.setenv("FITMAS_APP_SOURCE", "v0")
    import importlib
    from fitmas.legacy.app.api import v0_source, routes_v0_link
    importlib.reload(v0_source)
    importlib.reload(routes_v0_link)
    app = FastAPI()
    app.include_router(routes_v0_link.router)
    return TestClient(app)


def _seed(db):
    init_db(db)
    con = sqlite3.connect(db)
    con.execute("insert into v0_scheduled_sessions (id,user_id,date,sport,title,duration_min,intensity_label,priority,status) "
                "values (1,5,'2026-06-08','running','Seuil',45,'hard','key','planned')")
    con.execute("insert into v0_activities (id,user_id,date,sport,duration_min,distance_km,notes,source) "
                "values (2,5,'2026-06-08','running',50,9.0,'r','strava')")
    con.commit(); con.close()


def test_link_then_unlink_endpoint(tmp_path, monkeypatch):
    db = tmp_path / "v0.db"; _seed(db)
    client = _app(db, monkeypatch)

    r = client.post("/api/v0/activities/2/link", json={"session_id": 1})
    assert r.status_code == 200, r.text
    assert r.json()["session_status"] == "done"

    con = sqlite3.connect(db)
    assert con.execute("select scheduled_session_id from v0_activities where id=2").fetchone()[0] == 1
    con.close()

    r = client.post("/api/v0/activities/2/unlink", json={})
    assert r.status_code == 200, r.text
    assert r.json()["session_status"] == "planned"
