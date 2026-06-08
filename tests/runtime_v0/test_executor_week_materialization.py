import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fitmas.runtime_v0.db import connect, init_db
from fitmas.runtime_v0.executor import _apply_commit_week
from fitmas.runtime_v0.snapshot import SnapshotBuilder


def _week_payload():
    return {
        "week_proposal": {
            "week_start": "2026-06-15",
            "source": "llm",
            "week_load": 370,
            "key_type": "threshold",
            "sessions": [
                {"date": "2026-06-15", "type": "rest", "duration_min": 0, "intensity": "easy"},
                {"date": "2026-06-16", "type": "threshold", "duration_min": 50, "intensity": "hard"},
                {"date": "2026-06-17", "type": "easy_run", "duration_min": 45, "intensity": "easy"},
                {"date": "2026-06-21", "type": "long_run", "duration_min": 80, "intensity": "moderate"},
            ],
        }
    }


def _rows(conn, user_id=1):
    return [
        dict(r)
        for r in conn.execute(
            "select date, sport, title, duration_min, intensity_label, priority, status "
            "from v0_scheduled_sessions where user_id = ? order by date",
            (user_id,),
        ).fetchall()
    ]


def test_commit_week_materializes_non_rest_sessions():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db = Path(tmp.name)
    try:
        init_db(db)
        with connect(db) as conn:
            _apply_commit_week(_week_payload(), conn, user_id=1)
            conn.commit()
            rows = _rows(conn)
        # rest day dropped -> 3 rows, not 4
        assert [r["date"] for r in rows] == ["2026-06-16", "2026-06-17", "2026-06-21"]
        thr = rows[0]
        assert thr["sport"] == "running"
        assert thr["intensity_label"] == "hard"
        assert thr["priority"] == "key"  # threshold == key_type
        assert thr["status"] == "planned"
        assert thr["title"]  # non-empty label
        assert rows[1]["priority"] == "secondary"  # easy_run != key_type
    finally:
        db.unlink(missing_ok=True)


def test_recommit_replaces_planned_but_preserves_executed():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db = Path(tmp.name)
    try:
        init_db(db)
        with connect(db) as conn:
            conn.execute(
                "insert into v0_scheduled_sessions "
                "(user_id, date, sport, title, duration_min, intensity_label, priority, status) "
                "values (1,'2026-06-17','running','OLD',30,'easy','secondary','planned')"
            )
            conn.execute(
                "insert into v0_scheduled_sessions "
                "(user_id, date, sport, title, duration_min, intensity_label, priority, status) "
                "values (1,'2026-06-16','running','DONE run',40,'easy','secondary','done')"
            )
            _apply_commit_week(_week_payload(), conn, user_id=1)
            conn.commit()
            rows = _rows(conn)
        by_date = {r["date"]: r for r in rows}
        # stale planned 'OLD' on 06-17 replaced by the new easy_run
        assert by_date["2026-06-17"]["title"] != "OLD"
        # executed row on 06-16 preserved (NOT overwritten by the new threshold)
        assert by_date["2026-06-16"]["status"] == "done"
        assert by_date["2026-06-16"]["title"] == "DONE run"
        # no duplicate planned row added on the settled day
        assert sum(1 for r in rows if r["date"] == "2026-06-16") == 1
    finally:
        db.unlink(missing_ok=True)


def test_committed_week_visible_in_current_plan():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db = Path(tmp.name)
    try:
        init_db(db)
        with connect(db) as conn:
            _apply_commit_week(_week_payload(), conn, user_id=1)
            conn.commit()
        snap = SnapshotBuilder(db).build(user_id=1, now=datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc))
        dates = {s.date.isoformat() for s in snap.current_plan}
        assert "2026-06-16" in dates and "2026-06-21" in dates
        assert "2026-06-15" not in dates  # rest day not materialized
    finally:
        db.unlink(missing_ok=True)
