from __future__ import annotations

import os
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# DB path: env var (for prod/Docker) or repo root (for dev)
_DB_PATH = Path(os.getenv("FITMAS_DB_PATH", Path(__file__).resolve().parents[4] / "fitmas.db"))
DATABASE_URL = f"sqlite:///{_DB_PATH}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from fitmas import schema  # noqa: F401 — registers all ORM models with Base
    Base.metadata.create_all(bind=engine)
    _ensure_sqlite_columns()


def _ensure_sqlite_columns() -> None:
    if engine.dialect.name != "sqlite":
        return

    migrations = {
        "users": [
            ("timezone", "ALTER TABLE users ADD COLUMN timezone VARCHAR(64) DEFAULT 'Europe/Paris'"),
            ("telegram_chat_id", "ALTER TABLE users ADD COLUMN telegram_chat_id INTEGER"),
            ("primary_objective", "ALTER TABLE users ADD COLUMN primary_objective TEXT DEFAULT ''"),
            ("weekly_structure_notes", "ALTER TABLE users ADD COLUMN weekly_structure_notes TEXT DEFAULT ''"),
            ("coach_name", "ALTER TABLE users ADD COLUMN coach_name VARCHAR(64) DEFAULT 'FitMAS'"),
            ("coach_style", "ALTER TABLE users ADD COLUMN coach_style VARCHAR(32) DEFAULT 'direct'"),
            ("coach_relationship", "ALTER TABLE users ADD COLUMN coach_relationship TEXT DEFAULT ''"),
            ("coach_do", "ALTER TABLE users ADD COLUMN coach_do TEXT DEFAULT ''"),
            ("coach_dont", "ALTER TABLE users ADD COLUMN coach_dont TEXT DEFAULT ''"),
            ("coach_soul", "ALTER TABLE users ADD COLUMN coach_soul TEXT DEFAULT ''"),
            ("onboarding_status", "ALTER TABLE users ADD COLUMN onboarding_status VARCHAR(32) DEFAULT 'not_started'"),
        ],
        "weekly_plans": [
            ("created_at", "ALTER TABLE weekly_plans ADD COLUMN created_at DATETIME"),
            ("mesocycle_week", "ALTER TABLE weekly_plans ADD COLUMN mesocycle_week INTEGER DEFAULT 1"),
            ("mesocycle_number", "ALTER TABLE weekly_plans ADD COLUMN mesocycle_number INTEGER DEFAULT 1"),
        ],
        "day_plans": [
            ("sport_type", "ALTER TABLE day_plans ADD COLUMN sport_type VARCHAR(32) DEFAULT 'running'"),
            ("session_type", "ALTER TABLE day_plans ADD COLUMN session_type VARCHAR(32) DEFAULT 'easy'"),
            ("duration_min", "ALTER TABLE day_plans ADD COLUMN duration_min INTEGER"),
            ("intensity", "ALTER TABLE day_plans ADD COLUMN intensity VARCHAR(16) DEFAULT 'easy'"),
            ("load_score", "ALTER TABLE day_plans ADD COLUMN load_score INTEGER DEFAULT 1"),
            ("completion_status", "ALTER TABLE day_plans ADD COLUMN completion_status VARCHAR(16) DEFAULT 'planned'"),
            ("session_description", "ALTER TABLE day_plans ADD COLUMN session_description TEXT DEFAULT ''"),
        ],
        "activities": [
            ("external_id", "ALTER TABLE activities ADD COLUMN external_id VARCHAR(64)"),
            ("scheduled_session_id", "ALTER TABLE activities ADD COLUMN scheduled_session_id INTEGER"),
            ("distance_m", "ALTER TABLE activities ADD COLUMN distance_m FLOAT"),
            ("elevation_m", "ALTER TABLE activities ADD COLUMN elevation_m FLOAT"),
            ("perceived_load", "ALTER TABLE activities ADD COLUMN perceived_load INTEGER"),
            ("started_at", "ALTER TABLE activities ADD COLUMN started_at DATETIME"),
            ("matched_day", "ALTER TABLE activities ADD COLUMN matched_day VARCHAR(16)"),
            ("match_reason", "ALTER TABLE activities ADD COLUMN match_reason TEXT DEFAULT ''"),
            ("avg_hr", "ALTER TABLE activities ADD COLUMN avg_hr FLOAT"),
            ("max_hr", "ALTER TABLE activities ADD COLUMN max_hr FLOAT"),
            ("avg_speed", "ALTER TABLE activities ADD COLUMN avg_speed FLOAT"),
            ("calories", "ALTER TABLE activities ADD COLUMN calories FLOAT"),
            ("suffer_score", "ALTER TABLE activities ADD COLUMN suffer_score INTEGER"),
            ("tss", "ALTER TABLE activities ADD COLUMN tss FLOAT"),
            ("map_polyline", "ALTER TABLE activities ADD COLUMN map_polyline TEXT"),
            ("start_latlng", "ALTER TABLE activities ADD COLUMN start_latlng VARCHAR(64)"),
        ],
        "user_facts": [
            ("urgency", "ALTER TABLE user_facts ADD COLUMN urgency VARCHAR(16) DEFAULT 'medium'"),
            ("ttl", "ALTER TABLE user_facts ADD COLUMN ttl VARCHAR(16) DEFAULT 'medium'"),
            ("affects_json", "ALTER TABLE user_facts ADD COLUMN affects_json TEXT DEFAULT '[]'"),
            ("expires_at", "ALTER TABLE user_facts ADD COLUMN expires_at DATETIME"),
        ],
        "coach_messages": [
            ("proactive", "ALTER TABLE coach_messages ADD COLUMN proactive BOOLEAN DEFAULT 0"),
        ],
    }

    with engine.begin() as connection:
        for table_name, statements in migrations.items():
            tables = {
                row[0]
                for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
            }
            if table_name not in tables:
                continue
            existing = {
                row[1]
                for row in connection.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
            }
            for column_name, statement in statements:
                if column_name not in existing:
                    connection.execute(text(statement))
