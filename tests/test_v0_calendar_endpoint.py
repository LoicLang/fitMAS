import json
import tempfile
from pathlib import Path

from fitmas.runtime_v0.db import connect, init_db


def _seed(db: Path) -> None:
    with connect(db) as conn:
        conn.execute(
            "insert into v0_scheduled_sessions "
            "(user_id,date,sport,title,duration_min,intensity_label,priority,status) "
            "values (1,'2026-06-16','running','Seuil',50,'hard','key','planned')"
        )
        conn.execute(
            "insert into v0_scheduled_sessions "
            "(user_id,date,sport,title,duration_min,intensity_label,priority,status) "
            "values (1,'2026-06-17','running','Footing facile',45,'easy','secondary','planned')"
        )
        conn.execute(
            "insert into v0_activities "
            "(user_id,date,sport,duration_min,distance_km,notes,source) "
            "values (1,'2026-06-08','running',44,9.3,'Sortie','strava')"
        )
        conn.commit()


def test_v0_calendar_serves_v0_sessions_without_crashing(monkeypatch):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db = Path(tmp.name)
    try:
        init_db(db)
        _seed(db)
        monkeypatch.setenv("FITMAS_V0_DB_PATH", str(db))
        monkeypatch.setenv("FITMAS_APP_SOURCE", "v0")
        from fitmas.legacy.app.api import routes_app

        assert routes_app._app_source_is_v0() is True
        cal = routes_app._v0_calendar("2026-06")
        # legacy-only aggregates stubbed neutrally (no crash on missing V0 concepts)
        assert cal["planning_contract"] == {}
        assert cal["recent_adaptations"] == []
        assert cal["last_adaptation"] is None
        # the V0 session flowed through the real builder into the response
        blob = json.dumps(cal, default=str)
        assert "2026-06-16" in blob or "Seuil" in blob
    finally:
        db.unlink(missing_ok=True)


def test_app_source_flag_off_by_default(monkeypatch):
    monkeypatch.delenv("FITMAS_APP_SOURCE", raising=False)
    from fitmas.legacy.app.api import routes_app

    assert routes_app._app_source_is_v0() is False
