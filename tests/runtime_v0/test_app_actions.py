import sqlite3
from fitmas.runtime_v0.db import init_db
from fitmas.runtime_v0.adapters.app_actions import link_activity_to_session, unlink_activity

USER = 7


def _seed(db):
    init_db(db)
    con = sqlite3.connect(db)
    con.execute("insert into v0_scheduled_sessions (id,user_id,date,sport,title,duration_min,intensity_label,priority,status) "
                "values (1,?,'2026-06-08','running','Seuil',45,'hard','key','planned')", (USER,))
    con.execute("insert into v0_activities (id,user_id,date,sport,duration_min,distance_km,notes,source) "
                "values (2,?,'2026-06-08','running',50,9.0,'r','strava')", (USER,))
    con.commit(); con.close()


def _val(db, sql):
    con = sqlite3.connect(db); v = con.execute(sql).fetchone()[0]; con.close(); return v


def test_link_then_unlink(tmp_path):
    db = tmp_path / "v0.db"; _seed(db)
    ev = link_activity_to_session(db, user_id=USER, activity_id=2, session_id=1)
    assert ev.status == "applied"
    assert _val(db, "select scheduled_session_id from v0_activities where id=2") == 1
    assert _val(db, "select status from v0_scheduled_sessions where id=1") == "done"

    unlink_activity(db, user_id=USER, activity_id=2)
    assert _val(db, "select scheduled_session_id from v0_activities where id=2") is None
    assert _val(db, "select status from v0_scheduled_sessions where id=1") == "planned"
