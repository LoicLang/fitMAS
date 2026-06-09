from __future__ import annotations

import os
from pathlib import Path
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS v0_input_events (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    source TEXT NOT NULL,
    type TEXT NOT NULL,
    text TEXT,
    payload_json TEXT NOT NULL,
    occurred_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS v0_turns (
    id TEXT PRIMARY KEY,
    event_id TEXT,
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    proposal_json TEXT NOT NULL DEFAULT '{}',
    policy_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    reply TEXT NOT NULL DEFAULT '',
    reply_source TEXT NOT NULL DEFAULT 'test',
    provider TEXT NOT NULL DEFAULT 'fake',
    model TEXT NOT NULL DEFAULT 'fake',
    latency_ms INTEGER NOT NULL DEFAULT 0,
    tokens_in INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0,
    guard_ok INTEGER NOT NULL DEFAULT 1,
    guard_reasons_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(event_id) REFERENCES v0_input_events(id)
);

CREATE TABLE IF NOT EXISTS v0_command_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    turn_id TEXT NOT NULL REFERENCES v0_turns(id),
    command_type TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    status TEXT NOT NULL,
    before_json TEXT NOT NULL DEFAULT '{}',
    after_json TEXT NOT NULL DEFAULT '{}',
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(turn_id, command_type, target_id)
);

CREATE TABLE IF NOT EXISTS v0_scheduled_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    sport TEXT NOT NULL,
    title TEXT NOT NULL,
    duration_min INTEGER NOT NULL,
    intensity_label TEXT NOT NULL,
    priority TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'planned',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS v0_planned_weeks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    week_start TEXT NOT NULL,
    source TEXT NOT NULL,
    week_load REAL NOT NULL,
    key_type TEXT NOT NULL,
    sessions_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'committed',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS v0_activities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    sport TEXT NOT NULL,
    duration_min INTEGER NOT NULL,
    distance_km REAL,
    notes TEXT,
    source TEXT NOT NULL DEFAULT 'manual',
    scheduled_session_id INTEGER
);

CREATE TABLE IF NOT EXISTS v0_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    confidence REAL NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TEXT,
    resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS v0_conversation_state (
    user_id INTEGER PRIMARY KEY,
    last_unresolved_intent_json TEXT,
    last_execution_event_id INTEGER,
    last_pending_id INTEGER,
    last_user_turn_id TEXT,
    expires_at TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS v0_pending_confirmations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    summary TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',  -- open | accepted | rejected | superseded
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS v0_idempotency_locks (
    event_id TEXT PRIMARY KEY,
    turn_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

V0_TABLES = (
    "v0_idempotency_locks",
    "v0_pending_confirmations",
    "v0_conversation_state",
    "v0_planned_weeks",
    "v0_facts",
    "v0_activities",
    "v0_scheduled_sessions",
    "v0_command_events",
    "v0_turns",
    "v0_input_events",
)

def db_path_from_env() -> Path:
    return Path(os.getenv("FITMAS_V0_DB_PATH", "fitmas_v0.db"))

def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or db_path_from_env()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection

def init_db(db_path: Path | None = None) -> None:
    with connect(db_path) as connection:
        connection.executescript(SCHEMA)
        _ensure_fact_columns(connection)
        _ensure_activity_columns(connection)
        connection.commit()

def _ensure_fact_columns(connection: sqlite3.Connection) -> None:
    # Idempotent migration: older v0 DBs predate resolved_at. CREATE TABLE IF NOT
    # EXISTS won't add the column, so add it here when missing.
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(v0_facts)")}
    if "resolved_at" not in columns:
        connection.execute("ALTER TABLE v0_facts ADD COLUMN resolved_at TEXT")

def _ensure_activity_columns(connection: sqlite3.Connection) -> None:
    # Older v0 DBs predate the activity<->session link. CREATE TABLE IF NOT EXISTS
    # won't add the column, so add it here when missing.
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(v0_activities)")}
    if "scheduled_session_id" not in columns:
        connection.execute("ALTER TABLE v0_activities ADD COLUMN scheduled_session_id INTEGER")

def reset_db(db_path: Path | None = None) -> None:
    with connect(db_path) as connection:
        for table in V0_TABLES:
            connection.execute(f"DROP TABLE IF EXISTS {table}")
        connection.commit()
    init_db(db_path)
