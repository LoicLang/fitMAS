import sqlite3
from fitmas.runtime_v0.db import init_db


def test_init_db_adds_scheduled_session_id_to_old_activities(tmp_path):
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    # old-shape v0_activities (no scheduled_session_id)
    con.execute(
        "create table v0_activities (id integer primary key, user_id integer, date text, "
        "sport text, duration_min integer, distance_km real, notes text, source text)"
    )
    con.commit()
    con.close()

    init_db(db)            # must add the column, idempotently
    init_db(db)

    con = sqlite3.connect(db)
    cols = {r[1] for r in con.execute("PRAGMA table_info(v0_activities)")}
    con.close()
    assert "scheduled_session_id" in cols


def test_fresh_db_has_scheduled_session_id(tmp_path):
    db = tmp_path / "fresh.db"
    init_db(db)
    con = sqlite3.connect(db)
    cols = {r[1] for r in con.execute("PRAGMA table_info(v0_activities)")}
    con.close()
    assert "scheduled_session_id" in cols
