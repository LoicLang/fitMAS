import sqlite3
import pytest
from fitmas.runtime_v0.db import init_db
from fitmas.runtime_v0.executor import CommandExecutor
from fitmas.runtime_v0.policy import LinkActivityToSessionCommand, UnlinkActivityCommand

USER = 555


def _seed(db):
    init_db(db)
    con = sqlite3.connect(db)
    con.execute(
        "insert into v0_scheduled_sessions (id, user_id, date, sport, title, duration_min, "
        "intensity_label, priority, status) values (10, ?, '2026-06-08', 'running', 'Seuil', 45, 'hard', 'key', 'planned')",
        (USER,),
    )
    con.execute(
        "insert into v0_activities (id, user_id, date, sport, duration_min, distance_km, notes, source) "
        "values (900, ?, '2026-06-08', 'running', 50, 9.5, 'run', 'strava')",
        (USER,),
    )
    con.commit()
    con.close()


def _row(db, sql, args=()):
    con = sqlite3.connect(db); con.row_factory = sqlite3.Row
    r = con.execute(sql, args).fetchone(); con.close()
    return r


def test_link_sets_fk_and_marks_session_done_and_audits(tmp_path):
    db = tmp_path / "v0.db"; _seed(db)
    events = CommandExecutor(db).execute(
        (LinkActivityToSessionCommand(activity_id=900, session_id=10, evidence="app link"),),
        turn_id="app-link-1", user_id=USER,
    )
    assert events[0].status == "applied"
    assert _row(db, "select scheduled_session_id from v0_activities where id=900")[0] == 10
    assert _row(db, "select status from v0_scheduled_sessions where id=10")[0] == "done"
    assert _row(db, "select count(*) from v0_command_events where command_type='LinkActivityToSessionCommand'")[0] == 1


def test_unlink_clears_fk_and_reverts_session(tmp_path):
    db = tmp_path / "v0.db"; _seed(db)
    CommandExecutor(db).execute(
        (LinkActivityToSessionCommand(activity_id=900, session_id=10, evidence="link"),),
        turn_id="t1", user_id=USER,
    )
    CommandExecutor(db).execute(
        (UnlinkActivityCommand(activity_id=900, evidence="undo"),),
        turn_id="t2", user_id=USER,
    )
    assert _row(db, "select scheduled_session_id from v0_activities where id=900")[0] is None
    assert _row(db, "select status from v0_scheduled_sessions where id=10")[0] == "planned"


def test_link_rejects_wrong_user(tmp_path):
    db = tmp_path / "v0.db"; _seed(db)
    events = CommandExecutor(db).execute(
        (LinkActivityToSessionCommand(activity_id=900, session_id=10, evidence="x"),),
        turn_id="t3", user_id=999,   # not the owner
    )
    assert events[0].status == "blocked"
    assert _row(db, "select scheduled_session_id from v0_activities where id=900")[0] is None


def test_link_rejects_sport_mismatch(tmp_path):
    db = tmp_path / "v0.db"; _seed(db)
    # seed an activity of a different sport than session 10 (running)
    con = sqlite3.connect(db)
    con.execute("insert into v0_activities (id,user_id,date,sport,duration_min,distance_km,notes,source) "
                "values (901, ?, '2026-06-08', 'cycling', 60, 25.0, 'ride', 'strava')", (USER,))
    con.commit(); con.close()
    events = CommandExecutor(db).execute(
        (LinkActivityToSessionCommand(activity_id=901, session_id=10, evidence="x"),),
        turn_id="tsm", user_id=USER,
    )
    assert events[0].status == "blocked"
    assert _row(db, "select scheduled_session_id from v0_activities where id=901")[0] is None
    assert _row(db, "select status from v0_scheduled_sessions where id=10")[0] == "planned"
