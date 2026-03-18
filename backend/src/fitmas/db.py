from __future__ import annotations

import os
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine
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
