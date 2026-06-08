#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MESSAGES = [
    "ok merci",
    "salut",
    "C'etait quoi ma plus longue sortie recente ?",
    "Je suis motive cette semaine",
    "Je ne suis pas dispo demain soir",
    "Cette semaine je voyage de mercredi a vendredi",
    "J'ai mal a l'epaule quand je nage, ca tire",
]


def _word_count(text: str) -> int:
    return len([part for part in text.strip().split() if part])


def _verbosity_label(words: int) -> str:
    if words <= 4:
        return "terse"
    if words <= 16:
        return "tight"
    if words <= 32:
        return "acceptable"
    return "verbose"


def _copy_source_db(source_db: Path) -> Path:
    temp_db = ROOT / f".tmp-profile-smoke-{os.getpid()}.db"
    shutil.copy2(source_db, temp_db)
    return temp_db


load_dotenv(ROOT / ".env", override=False)

parser = argparse.ArgumentParser(description="Run real conversation smokes on a copy of an existing FitMAS profile DB.")
parser.add_argument("--source-db", default=os.getenv("FITMAS_DB_PATH", str(ROOT / "fitmas.db")))
parser.add_argument("--user-id", type=int, default=None)
parser.add_argument("--message", action="append", dest="messages", help="Custom message to send. Repeatable.")
parser.add_argument("--keep-db", action="store_true", help="Keep the temporary copied DB.")
args = parser.parse_args()

source_db = Path(args.source_db).expanduser().resolve()
if not source_db.exists():
    print(f"Source DB not found: {source_db}", file=sys.stderr)
    raise SystemExit(2)

if not os.getenv("ANTHROPIC_API_KEY"):
    print("ANTHROPIC_API_KEY missing. Load .env or export the key first.", file=sys.stderr)
    raise SystemExit(2)

runtime_db = _copy_source_db(source_db)
os.environ["FITMAS_DB_PATH"] = str(runtime_db)
sys.path.insert(0, str(ROOT / "backend" / "src"))

from fastapi.testclient import TestClient
from sqlalchemy import text

from fitmas.legacy.api import app
from fitmas.legacy.core import orm as s
from fitmas.legacy.core.db import SessionLocal, engine, init_db
from fitmas.legacy.domain.athlete import repository as athlete_repo
from fitmas.legacy.domain.coaching import repo_conversation
from fitmas.legacy.domain.memory import repository as memory_repo
from fitmas.legacy.domain.planning import repository as planning_repo


@dataclass(slots=True)
class Snapshot:
    memory: dict[tuple[str, str], str]
    sessions: dict[int, tuple[str, str, str, str]]
    latest_agent_text: str | None


def _print_header(db, user) -> None:
    print(f"Source DB: {source_db}")
    print(f"Runtime DB: {runtime_db}")
    print(f"User: {user.id} | {user.name} | tz={user.timezone}")
    print(f"Coach: {user.coach_name} | style={user.coach_style}")
    print("Next sessions:")
    sessions = planning_repo.get_scheduled_sessions(db, user.id, limit=8)
    for session in sessions[:8]:
        when = session.scheduled_date.isoformat()[:16] if session.scheduled_date else "n/a"
        print(f"- {when} | {session.sport_type} | {session.session_title} | {session.completion_status}")
    print("")


def _snapshot(db, user_id: int) -> Snapshot:
    memory = memory_repo.get_active_memory_items(db, user_id, include_patterns=True, total_limit=40)
    sessions = planning_repo.get_scheduled_sessions(db, user_id, limit=16)
    messages = repo_conversation.get_messages(db, user_id)
    latest_agent = next((message.text for message in reversed(messages) if message.role == "agent"), None)
    return Snapshot(
        memory={
            (str(getattr(item, "category", "")), str(getattr(item, "key", ""))): str(getattr(item, "value", ""))
            for item in memory
        },
        sessions={
            int(session.id): (
                session.scheduled_date.isoformat() if session.scheduled_date else "",
                session.session_title,
                session.completion_status,
                session.sport_type,
            )
            for session in sessions
        },
        latest_agent_text=latest_agent,
    )


def _print_turn(label: str, response: dict, before: Snapshot, after: Snapshot) -> None:
    text = response["assistant_message"]["text"]
    words = _word_count(text)
    print(f"TURN: {label}")
    print(f"assistant: {text}")
    print(f"tone: words={words} | verbosity={_verbosity_label(words)}")
    print(f"extraction_confidence: {(response.get('extraction') or {}).get('confidence')}")

    memory_changes = []
    for key, value in after.memory.items():
        if before.memory.get(key) != value:
            memory_changes.append(f"{key[0]}:{key[1]}")
    print(f"memory_changes: {', '.join(memory_changes) if memory_changes else '-'}")

    session_changes = []
    for session_id, payload in after.sessions.items():
        if before.sessions.get(session_id) != payload:
            when, title, status, sport = payload
            session_changes.append(f"{session_id}:{title} [{sport}/{status}] {when[:16]}")
    print(f"session_changes: {', '.join(session_changes) if session_changes else '-'}")
    print("")


def _resolve_user(db):
    if args.user_id is not None:
        user = db.get(s.User, args.user_id)
        if user is None:
            raise RuntimeError(f"user_id={args.user_id} not found")
        return user
    user = athlete_repo.get_user_optional(db)
    if user is None:
        raise RuntimeError("No user found in source DB")
    return user


def main() -> int:
    try:
        init_db()
        with engine.begin() as connection:
            connection.execute(text("PRAGMA journal_mode=WAL"))

        db = SessionLocal()
        try:
            user = _resolve_user(db)
            _print_header(db, user)
            messages = args.messages or DEFAULT_MESSAGES
            with TestClient(app) as client:
                for message in messages:
                    before = _snapshot(db, user.id)
                    response = client.post("/api/v0/messages", json={"text": message})
                    payload = response.json()
                    db.expire_all()
                    after = _snapshot(db, user.id)
                    _print_turn(message, payload, before, after)
        finally:
            db.close()
    finally:
        if not args.keep_db and runtime_db.exists():
            runtime_db.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
