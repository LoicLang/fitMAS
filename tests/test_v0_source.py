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
            "values (1,'2026-06-15','running',44,9.3,'Sortie tranquille','strava')"
        )
        conn.commit()


def test_v0_source_maps_sessions_and_activities(monkeypatch):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db = Path(tmp.name)
    try:
        init_db(db)
        _seed(db)
        monkeypatch.setenv("FITMAS_V0_DB_PATH", str(db))
        from fitmas.legacy.app.api import v0_source

        sessions = v0_source.get_scheduled_sessions()
        assert [s.scheduled_date for s in sessions] == ["2026-06-16", "2026-06-17"]
        thr = sessions[0]
        assert thr.day == "tuesday"  # 2026-06-16 is a Tuesday
        assert thr.intensity == "hard" and thr.priority == "key"
        assert thr.completion_status == "planned"
        assert thr.session_title == "Seuil"

        acts = v0_source.get_activities()
        assert len(acts) == 1
        assert acts[0].sport_type == "running"
        assert acts[0].duration_min == 44
        assert acts[0].distance_m == 9300.0
        assert acts[0].source == "strava"
        assert acts[0].tss == round(44 * 0.8, 1)  # duration-based load proxy
    finally:
        db.unlink(missing_ok=True)


def test_v0_source_empty_when_db_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("FITMAS_V0_DB_PATH", str(tmp_path / "nope.db"))
    from fitmas.legacy.app.api import v0_source

    assert v0_source.get_scheduled_sessions() == []
    assert v0_source.get_activities() == []
