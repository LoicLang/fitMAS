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


def test_v0_overview_serves_v0_sessions_without_crashing(monkeypatch):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db = Path(tmp.name)
    try:
        init_db(db)
        _seed(db)
        monkeypatch.setenv("FITMAS_V0_DB_PATH", str(db))
        monkeypatch.setenv("FITMAS_APP_SOURCE", "v0")
        from fitmas.legacy.app.api import routes_app

        overview = routes_app._v0_overview()
        assert overview["planning_contract"] == {}
        assert "week_context" in overview
        blob = json.dumps(overview, default=str)
        assert "2026-06-16" in blob or "Seuil" in blob
    finally:
        db.unlink(missing_ok=True)


def test_v0_activities_endpoint_serves_v0(monkeypatch):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db = Path(tmp.name)
    try:
        init_db(db)
        _seed(db)
        monkeypatch.setenv("FITMAS_V0_DB_PATH", str(db))
        monkeypatch.setenv("FITMAS_APP_SOURCE", "v0")
        from fitmas.legacy.app.api import routes_read

        acts = routes_read.get_activities(db=None)  # V0 branch returns before touching db
        assert len(acts) == 1
        assert acts[0].duration_min == 44
    finally:
        db.unlink(missing_ok=True)


def test_v0_evolution_serves_v0_without_crashing(monkeypatch):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db = Path(tmp.name)
    try:
        init_db(db)
        _seed(db)
        monkeypatch.setenv("FITMAS_V0_DB_PATH", str(db))
        monkeypatch.setenv("FITMAS_APP_SOURCE", "v0")
        from fitmas.legacy.app.api import routes_app

        evo = routes_app._v0_evolution()
        assert evo["planning_contract"] == {}
        assert "week_context" in evo
    finally:
        db.unlink(missing_ok=True)


def test_v0_session_detail_serves_and_404(monkeypatch):
    import fastapi

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db = Path(tmp.name)
    try:
        init_db(db)
        _seed(db)
        monkeypatch.setenv("FITMAS_V0_DB_PATH", str(db))
        monkeypatch.setenv("FITMAS_APP_SOURCE", "v0")
        from fitmas.legacy.app.api import routes_app

        detail = routes_app._v0_session_detail(1)  # first seeded session
        assert isinstance(detail, dict) and detail
        try:
            routes_app._v0_session_detail(999999)
            raise AssertionError("expected 404 for a missing session id")
        except fastapi.HTTPException as exc:
            assert exc.status_code == 404
    finally:
        db.unlink(missing_ok=True)


def test_v0_today_view_built_for_matching_date(monkeypatch):
    from datetime import date

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db = Path(tmp.name)
    try:
        init_db(db)
        _seed(db)
        monkeypatch.setenv("FITMAS_V0_DB_PATH", str(db))
        from fitmas.legacy.app.api import routes_app, v0_source

        sessions = v0_source.get_scheduled_sessions()
        tv = routes_app._v0_today_view(sessions, date(2026, 6, 16))  # matches seeded threshold
        assert tv is not None
        assert tv["session_title"] == "Seuil"
        assert tv["scheduled_session_id"] == sessions[0].id
        assert routes_app._v0_today_view(sessions, date(2030, 1, 1)) is None  # no session that day
    finally:
        db.unlink(missing_ok=True)


def test_app_source_flag_off_by_default(monkeypatch):
    monkeypatch.delenv("FITMAS_APP_SOURCE", raising=False)
    from fitmas.legacy.app.api import routes_app

    assert routes_app._app_source_is_v0() is False
